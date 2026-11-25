"""Coordinator: keeps the temperature ledger current and calculates lawn state."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    ACTIVITY_TYPES,
    CONF_HEIGHT_UNIT,
    CONF_METHOD,
    CONF_SEASON_START_MONTH,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_METHOD,
    DEFAULT_SEASON_START_MONTH,
    DOMAIN,
    EVENT_ENTRY_LOGGED,
    EVENT_PGR_DUE,
    FINALISE_DELAY,
    FORECAST_INTERVAL,
    HEIGHT_UNIT_AUTO,
    KIND_ACTIVITY,
    KIND_APPLICATION,
    KIND_MOW,
    LEDGER_KEEP_DAYS,
    LOGGER,
    MAX_BACKFILL_DAYS,
    MIN_HOURS_COMPLETE,
    SOURCE_MANUAL,
    SOURCE_NONE,
    SUBENTRY_LAWN,
    SUBENTRY_PRODUCT,
    UPDATE_INTERVAL,
)
from .gdd import (
    METHOD_MEAN,
    METHOD_MINMAX,
    PGR_MODELS,
    daily_gdd,
    daily_temperature,
    project_due_date,
    relative_growth,
    trailing_average,
)
from .models import Lawn, LawnState, Product, SiteState, entry_date, entry_summary
from .store import TurfStore
from .units import HEIGHT_UNIT_IN, HEIGHT_UNIT_MM, nutrient_g_per_m2, total_product
from .weather_source import WeatherSource

# GDD since PGR counted other ways, for comparison: key -> (sensor, method).
COMPARISONS: dict[str, tuple[str, str]] = {
    "main_mean": ("main", METHOD_MEAN),
    "main_minmax": ("main", METHOD_MINMAX),
    "fallback_mean": ("fallback", METHOD_MEAN),
    "fallback_minmax": ("fallback", METHOD_MINMAX),
}


def site_config(entry: ConfigEntry) -> dict[str, Any]:
    """Merged site configuration (options override initial data)."""
    return {**entry.data, **entry.options}


class TurfCoordinator(DataUpdateCoordinator[SiteState]):
    """Owns the ledger and log for one site and calculates every lawn."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, store: TurfStore) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL,
        )
        self.store = store
        self.source = WeatherSource(hass, site_config(entry))
        self._today_record: dict[str, Any] | None = None
        self._today_fallback: dict[str, Any] | None = None
        self._forecast: dict[date, tuple[float, float]] = {}
        self._forecast_fetched: datetime | None = None
        self._due_state: dict[str, bool] = {}
        # When each lawn's log last changed, so dashboards know to reload it.
        self._log_modified: dict[str, datetime] = {}
        # Values staged by the dashboard select/number entities, per lawn.
        self.staged: dict[str, dict[str, Any]] = {}

    # --- Configuration accessors ----------------------------------------------

    @property
    def config(self) -> dict[str, Any]:
        return site_config(self.config_entry)

    @property
    def method(self) -> str:
        return self.config.get(CONF_METHOD, DEFAULT_METHOD)

    @property
    def height_unit(self) -> str:
        unit = self.config.get(CONF_HEIGHT_UNIT, HEIGHT_UNIT_AUTO)
        if unit == HEIGHT_UNIT_AUTO:
            return HEIGHT_UNIT_MM if self.hass.config.units.length_unit == "km" else HEIGHT_UNIT_IN
        return unit

    def lawns(self) -> dict[str, Lawn]:
        return {
            sid: Lawn.from_subentry(sub)
            for sid, sub in self.config_entry.subentries.items()
            if sub.subentry_type == SUBENTRY_LAWN
        }

    def get_lawn(self, lawn_id: str) -> Lawn:
        return Lawn.from_subentry(self.config_entry.subentries[lawn_id])

    def products(self) -> dict[str, Product]:
        return {
            sid: Product.from_subentry(sub)
            for sid, sub in self.config_entry.subentries.items()
            if sub.subentry_type == SUBENTRY_PRODUCT
        }

    def find_product(self, name_or_id: str) -> Product | None:
        products = self.products()
        if name_or_id in products:
            return products[name_or_id]
        wanted = name_or_id.strip().casefold()
        return next((p for p in products.values() if p.name.casefold() == wanted), None)

    def lawn_pgr_product(self, lawn: Lawn) -> Product | None:
        """The lawn's chosen PGR product, else the first PGR in the library."""
        products = self.products()
        if lawn.pgr_product_id and lawn.pgr_product_id in products:
            return products[lawn.pgr_product_id]
        return next((p for p in products.values() if p.is_pgr), None)

    def lawn_device_id(self, lawn_id: str) -> str | None:
        device = dr.async_get(self.hass).async_get_device_by_identifier(
            (DOMAIN, lawn_id), self.config_entry.entry_id
        )
        return device.id if device else None

    # --- Lifecycle ---------------------------------------------------------------

    @callback
    def async_start(self) -> None:
        """Refresh shortly after midnight so yesterday is finalised promptly."""
        minute = int(FINALISE_DELAY.total_seconds() // 60)
        self.config_entry.async_on_unload(
            async_track_time_change(
                self.hass, self._async_midnight, hour=0, minute=minute, second=5
            )
        )

    async def _async_midnight(self, _now: datetime) -> None:
        # A back-dated log date is for catching up today only.
        for staged in self.staged.values():
            staged.pop("log_date", None)
        await self.async_refresh()

    def log_date(self, lawn_id: str) -> date:
        """The date the dashboard's Log buttons record (today unless changed)."""
        return self.staged.get(lawn_id, {}).get("log_date") or dt_util.now().date()

    def log_when(self, lawn_id: str) -> date | None:
        """None (meaning now) for today, else the back-dated day."""
        day = self.staged.get(lawn_id, {}).get("log_date")
        return day if day and day < dt_util.now().date() else None

    @callback
    def async_set_log_date(self, lawn_id: str, day: date) -> None:
        today = dt_util.now().date()
        if day > today:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="log_date_in_future"
            )
        staged = self.staged.setdefault(lawn_id, {})
        if day == today:
            staged.pop("log_date", None)
        else:
            staged["log_date"] = day
        self.async_update_listeners()

    async def _async_update_data(self) -> SiteState:
        try:
            await self._async_sync_ledger()
        except HomeAssistantError as err:
            LOGGER.warning("Could not update temperatures: %s", err)
        await self._async_update_forecast()
        self._update_statistics_issue()
        return self._compute()

    async def _async_sync_ledger(self) -> None:
        today = dt_util.now().date()
        yesterday = today - timedelta(days=1)
        earliest = today - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        for lawn in self.lawns().values():
            if last := self._last_pgr(lawn.id):
                earliest = min(earliest, entry_date(last))
        earliest = max(earliest, today - timedelta(days=MAX_BACKFILL_DAYS))

        missing: list[date] = []
        day = earliest
        while day <= yesterday:
            record = self.store.get_day(day)
            if record is None or not record.get("final"):
                missing.append(day)
            day += timedelta(days=1)

        if missing:
            LOGGER.debug("Fetching %d day(s) of temperatures from %s", len(missing), missing[0])
            fetched = await self.source.async_fetch_days(missing[0], missing[-1])
            now = dt_util.now()
            for day in missing:
                record = fetched.get(day) or {
                    "mean": None,
                    "min": None,
                    "max": None,
                    "hours": 0.0,
                    "source": SOURCE_NONE,
                }
                finalise_at = dt_util.start_of_local_day(day + timedelta(days=1)) + FINALISE_DELAY
                record["final"] = now >= finalise_at
                self.store.set_day(day, record)
            self.store.prune(today - timedelta(days=LEDGER_KEEP_DAYS))
            self.store.schedule_save()

        self._today_record = await self.source.async_fetch_today()
        await self._async_sync_fallback(earliest, yesterday)

    async def _async_sync_fallback(self, earliest: date, yesterday: date) -> None:
        """Keep the fallback sensor's own daily values (record["fb"]) for comparison."""
        if not self.source.fallback:
            self._today_fallback = None
            return
        missing = []
        day = earliest
        while day <= yesterday:
            record = self.store.get_day(day)
            if record is not None and not (record.get("fb") or {}).get("final"):
                missing.append(day)
            day += timedelta(days=1)
        if missing:
            fetched = await self.source.async_fetch_fallback_days(missing[0], missing[-1])
            now = dt_util.now()
            for day in missing:
                record = self.store.get_day(day)
                fb = fetched.get(day) or {"mean": None, "min": None, "max": None, "hours": 0.0}
                finalise_at = dt_util.start_of_local_day(day + timedelta(days=1)) + FINALISE_DELAY
                fb["final"] = now >= finalise_at
                record["fb"] = fb
            self.store.schedule_save()
        self._today_fallback = await self.source.async_fetch_fallback_today()

    async def _async_update_forecast(self) -> None:
        if not self.source.weather:
            self._forecast = {}
            return
        now = dt_util.utcnow()
        if self._forecast_fetched and now - self._forecast_fetched < FORECAST_INTERVAL:
            return
        try:
            self._forecast = await self.source.async_fetch_forecast()
            self._forecast_fetched = now
        except HomeAssistantError as err:
            LOGGER.debug("Forecast unavailable: %s", err)

    def _update_statistics_issue(self) -> None:
        issue_id = f"no_statistics_{self.config_entry.entry_id}"
        if self.source.primary_has_statistics is False:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="no_statistics",
                translation_placeholders={"entity_id": self.source.primary},
            )
        elif self.source.primary_has_statistics:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    async def async_recalculate_days(self, start: date, end: date) -> int:
        """Drop non-manual ledger days in a range so they're fetched again."""
        removed = self.store.clear_days(
            start, end, keep=lambda rec: rec.get("source") == SOURCE_MANUAL
        )
        self._forecast_fetched = None
        await self.async_refresh()
        return removed

    async def async_set_manual_day(
        self, day: date, mean: float | None, t_min: float | None, t_max: float | None
    ) -> None:
        if mean is None and (t_min is None or t_max is None):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="manual_day_needs_values"
            )
        self.store.set_day(
            day,
            {
                "mean": mean,
                "min": t_min,
                "max": t_max,
                "hours": 24.0,
                "source": SOURCE_MANUAL,
                "final": True,
            },
        )
        self.store.schedule_save()
        self.async_set_updated_data(self._compute())

    @callback
    def async_recompute(self) -> None:
        """Recalculate from cached data (after a settings change)."""
        if self.data is not None:
            self.async_set_updated_data(self._compute())

    # --- Calculation ---------------------------------------------------------------

    def _last_pgr(self, lawn_id: str) -> dict[str, Any] | None:
        pgr = [e for e in self.store.entries_for(lawn_id, KIND_APPLICATION) if e.get("is_pgr")]
        return pgr[-1] if pgr else None

    def _day_temp(self, record: dict[str, Any] | None, base: float) -> float | None:
        return self._temp_by(record, self.method, base)

    @staticmethod
    def _temp_by(record: dict[str, Any] | None, method: str, base: float) -> float | None:
        if not record:
            return None
        return daily_temperature(
            record.get("mean"), record.get("min"), record.get("max"), method, base
        )

    def season_start(self, today: date) -> date:
        month = int(self.config.get(CONF_SEASON_START_MONTH, DEFAULT_SEASON_START_MONTH))
        year = today.year if today.month >= month else today.year - 1
        return date(year, month, 1)

    def _compute(self) -> SiteState:
        today = dt_util.now().date()
        lawns = {lawn_id: self._compute_lawn(lawn, today) for lawn_id, lawn in self.lawns().items()}
        self._fire_due_events(lawns)
        return SiteState(
            today=self._today_record,
            yesterday=self.store.get_day(today - timedelta(days=1)),
            lawns=lawns,
            forecast_days=len(self._forecast),
        )

    def _compute_lawn(self, lawn: Lawn, today: date) -> LawnState:
        base = lawn.base_temp
        state = LawnState(lawn_id=lawn.id, target=lawn.gdd_target, base_temp=base)
        products = self.products()

        state.gdd_today = daily_gdd(self._day_temp(self._today_record, base), base)

        last = self._last_pgr(lawn.id)
        state.last_pgr = last
        if last and last.get("product_id") in products:
            state.pgr_product = products[last["product_id"]]
        else:
            state.pgr_product = self.lawn_pgr_product(lawn)

        if last:
            start_day = entry_date(last)
            state.days_since_pgr = (today - start_day).days
            completed = 0.0
            compared = dict.fromkeys(COMPARISONS, 0.0)
            day = start_day
            while day < today:
                record = self.store.get_day(day)
                hours = (record or {}).get("hours", 0)
                if not hours:
                    state.missing_days.append(day.isoformat())
                elif hours < MIN_HOURS_COMPLETE:
                    state.incomplete_days.append(day.isoformat())
                completed += daily_gdd(self._day_temp(record, base), base)
                fb = (record or {}).get("fb")
                if not (fb or {}).get("hours"):
                    state.fallback_missing_days.append(day.isoformat())
                for key, (source, method) in COMPARISONS.items():
                    day_record = record if source == "main" else fb
                    compared[key] += daily_gdd(self._temp_by(day_record, method, base), base)
                day += timedelta(days=1)
            today_part = state.gdd_today if start_day <= today else 0.0
            state.gdd_completed = round(completed, 2)
            state.gdd_total = round(completed + today_part, 2)
            for key, (source, method) in COMPARISONS.items():
                if source == "fallback" and not self.source.fallback:
                    continue
                today_record = self._today_record if source == "main" else self._today_fallback
                today_gdd = daily_gdd(self._temp_by(today_record, method, base), base)
                state.comparisons[key] = round(
                    compared[key] + (today_gdd if start_day <= today else 0.0), 2
                )
            state.progress = round(state.gdd_total / lawn.gdd_target * 100, 1)
            state.due = state.gdd_total >= lawn.gdd_target

            recent = [
                daily_gdd(self._day_temp(rec, base), base)
                for k in range(7, 0, -1)
                if (rec := self.store.get_day(today - timedelta(days=k))) and rec.get("hours")
            ]
            forecast_gdd = {
                day: daily_gdd(daily_temperature(None, low, high, self.method, base), base)
                for day, (low, high) in self._forecast.items()
                if day >= today
            }
            # Beyond the forecast, assume the last week's average; with no recent
            # history (e.g. a new install), the forecast's own average.
            fallback = trailing_average(recent)
            if fallback is None and forecast_gdd:
                fallback = sum(forecast_gdd.values()) / len(forecast_gdd)
            projection = project_due_date(
                completed_gdd=completed,
                target=lawn.gdd_target,
                today=max(today, start_day),
                today_partial_gdd=today_part,
                forecast_gdd=forecast_gdd,
                fallback_daily_gdd=fallback,
            )
            state.projected_due = projection.due_date
            state.projection_method = projection.method
            state.projection = projection.days

            model = PGR_MODELS.get(state.pgr_product.pgr_model) if state.pgr_product else None
            if model is not None:
                state.relative_growth = round(relative_growth(state.gdd_total, model) * 100, 1)
                state.model_validated = base == 0

        mows = self.store.entries_for(lawn.id, KIND_MOW)
        state.last_mow = mows[-1] if mows else None
        apps = self.store.entries_for(lawn.id, KIND_APPLICATION)
        state.last_application = apps[-1] if apps else None
        for entry in self.store.entries_for(lawn.id, KIND_ACTIVITY):
            state.last_activity[entry.get("activity", "other")] = entry

        state.log_count = len(self.store.entries_for(lawn.id))
        state.log_modified = self._log_modified.get(lawn.id)
        state.season_start = self.season_start(today)
        state.nitrogen_season = round(
            sum(e.get("n_g_m2") or 0 for e in apps if entry_date(e) >= state.season_start), 2
        )
        return state

    def _fire_due_events(self, lawns: dict[str, LawnState]) -> None:
        for lawn_id, state in lawns.items():
            previous = self._due_state.get(lawn_id)
            self._due_state[lawn_id] = state.due
            if previous is False and state.due:
                lawn = self.get_lawn(lawn_id)
                self.hass.bus.async_fire(
                    EVENT_PGR_DUE,
                    {
                        "device_id": self.lawn_device_id(lawn_id),
                        "lawn": lawn.name,
                        "gdd": state.gdd_total,
                        "target": state.target,
                    },
                )

    # --- Logging -------------------------------------------------------------------

    def _new_entry(
        self, lawn: Lawn, kind: str, when: datetime | date | None, data: dict[str, Any]
    ) -> dict[str, Any]:
        if when is None:
            start, all_day = dt_util.now(), False
        elif isinstance(when, datetime):
            start = dt_util.as_local(when if when.tzinfo else when.replace(tzinfo=dt_util.get_default_time_zone()))
            all_day = False
        else:
            start, all_day = dt_util.start_of_local_day(when), True
        return {
            "id": uuid4().hex,
            "lawn_id": lawn.id,
            "kind": kind,
            "start": start.isoformat(),
            "date": start.date().isoformat(),
            "all_day": all_day,
            "created": dt_util.now().isoformat(),
            **{k: v for k, v in data.items() if v is not None and v != ""},
        }

    def _weather_for(self, when: datetime | date | None) -> dict[str, Any] | None:
        """Snapshot weather only when logging something happening about now."""
        if when is None or (
            isinstance(when, datetime) and abs(dt_util.now() - dt_util.as_local(when)) < timedelta(hours=1)
        ):
            return self.source.snapshot() or None
        return None

    async def async_log_application(
        self,
        lawn_id: str,
        product: Product,
        *,
        rate: float | None = None,
        rate_unit: str | None = None,
        when: datetime | date | None = None,
        area_m2: float | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Log one product applied on its own."""
        return await self.async_log_mix(
            lawn_id, [(product, rate, rate_unit)], when=when, area_m2=area_m2, notes=notes
        )

    async def async_log_mix(
        self,
        lawn_id: str,
        items: list[tuple[Product, float | None, str | None]],
        *,
        when: datetime | date | None = None,
        area_m2: float | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Log one application of one or more products (a tank mix or blend).

        One product is stored flat, as before. Several are stored as a
        ``products`` list with combined name, PGR flag and nutrient totals, so
        the PGR count, nitrogen and history treat the mix as one application.
        """
        if not items:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="mix_empty")
        lawn = self.get_lawn(lawn_id)
        components = [_product_fields(product, rate, unit) for product, rate, unit in items]
        if len(components) == 1:
            data: dict[str, Any] = dict(components[0])
        else:
            pgr = next((c for c in components if c.get("is_pgr")), None)
            data = {
                "products": components,
                # The PGR in the mix (if any) is the product the GDD count follows.
                "product_id": (pgr or components[0]).get("product_id"),
                "product_name": " + ".join(c["product_name"] for c in components),
                "product_type": "mix",
                "is_pgr": pgr is not None,
            }
        data.update(
            area_m2=area_m2 if area_m2 is not None else lawn.area_m2,
            notes=notes,
            weather=self._weather_for(when),
        )
        entry = self._new_entry(lawn, KIND_APPLICATION, when, data)
        _derive_application(entry)
        await self._async_add(entry)
        return entry

    # --- Mix being built on the dashboard ---------------------------------------

    def mix_items(self, lawn_id: str) -> list[dict[str, Any]]:
        """Products added to the lawn's mix so far: {product_id, rate, rate_unit}."""
        return self.staged.setdefault(lawn_id, {}).setdefault("mix", [])

    @callback
    def async_mix_add(
        self, lawn_id: str, product: Product, rate: float | None, rate_unit: str | None
    ) -> None:
        """Add a product to the mix (replacing it if it's already there)."""
        items = [i for i in self.mix_items(lawn_id) if i["product_id"] != product.id]
        items.append(
            {
                "product_id": product.id,
                "rate": rate if rate is not None else product.rate,
                "rate_unit": rate_unit or product.rate_unit,
            }
        )
        self.staged[lawn_id]["mix"] = items
        self.async_update_listeners()

    @callback
    def async_mix_remove(self, lawn_id: str, product: Product) -> None:
        self.staged.setdefault(lawn_id, {})["mix"] = [
            i for i in self.mix_items(lawn_id) if i["product_id"] != product.id
        ]
        self.async_update_listeners()

    @callback
    def async_mix_clear(self, lawn_id: str) -> None:
        self.staged.setdefault(lawn_id, {})["mix"] = []
        self.async_update_listeners()

    def mix_products(self, lawn_id: str) -> list[tuple[Product, float | None, str | None]]:
        """The mix as (product, rate, unit), skipping products since deleted."""
        products = self.products()
        return [
            (products[i["product_id"]], i.get("rate"), i.get("rate_unit"))
            for i in self.mix_items(lawn_id)
            if i["product_id"] in products
        ]

    async def async_log_pgr(
        self,
        lawn_id: str,
        *,
        when: datetime | date | None = None,
        product: Product | None = None,
        rate: float | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Log a PGR application, defaulting to the lawn's PGR product."""
        lawn = self.get_lawn(lawn_id)
        product = product or self.lawn_pgr_product(lawn)
        if product is None:
            product = Product(id="", name="PGR", product_type="pgr")
        elif not product.is_pgr:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_a_pgr",
                translation_placeholders={"product": product.name},
            )
        day = when.date() if isinstance(when, datetime) else (when or dt_util.now().date())
        last = self._last_pgr(lawn_id)
        if last and entry_date(last) == day:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="pgr_already_logged",
                translation_placeholders={"date": day.isoformat()},
            )
        return await self.async_log_application(
            lawn_id, product, rate=rate, when=when, notes=notes
        )

    async def async_set_last_pgr_date(self, lawn_id: str, day: date) -> None:
        """Date entity: a later date logs a new application, an earlier one corrects the last."""
        last = self._last_pgr(lawn_id)
        if last is None or day > entry_date(last):
            await self.async_log_pgr(lawn_id, when=day)
            return
        if day == entry_date(last):
            return
        start = dt_util.start_of_local_day(day)
        updated = {**last, "start": start.isoformat(), "date": day.isoformat(), "all_day": True}
        updated.pop("weather", None)
        self.store.replace_entry(updated)
        self.store.schedule_save()
        self._touch(lawn_id)
        await self.async_refresh()

    async def async_log_mow(
        self,
        lawn_id: str,
        *,
        mower_type: str | None,
        height_mm: float | None,
        when: datetime | date | None = None,
        clippings_l: float | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        lawn = self.get_lawn(lawn_id)
        entry = self._new_entry(
            lawn,
            KIND_MOW,
            when,
            {
                "mower_type": mower_type,
                "height_mm": round(height_mm, 1) if height_mm is not None else None,
                "clippings_l": clippings_l,
                "notes": notes,
            },
        )
        await self._async_add(entry)
        return entry

    async def async_log_activity(
        self,
        lawn_id: str,
        *,
        activity: str,
        when: datetime | date | None = None,
        details: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if activity not in ACTIVITY_TYPES:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unknown_activity",
                translation_placeholders={"activity": activity},
            )
        lawn = self.get_lawn(lawn_id)
        entry = self._new_entry(
            lawn, KIND_ACTIVITY, when, {"activity": activity, "details": details, "notes": notes}
        )
        await self._async_add(entry)
        return entry

    async def async_update_entry(self, entry_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        entry = self.store.get_entry(entry_id)
        if entry is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="entry_not_found",
                translation_placeholders={"entry_id": entry_id},
            )
        updated = {**entry}
        when = changes.pop("when", None)
        if when is not None:
            moved = self._new_entry(self.get_lawn(entry["lawn_id"]), entry["kind"], when, {})
            updated.update(start=moved["start"], date=moved["date"], all_day=moved["all_day"])
        if entry.get("products") and (
            changes.get("rate") is not None or changes.get("rate_unit") is not None
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="mix_rate_edit"
            )
        updated.update({k: v for k, v in changes.items() if v is not None})
        if updated["kind"] == KIND_APPLICATION:
            _derive_application(updated)
        updated["modified"] = dt_util.now().isoformat()
        self.store.replace_entry(updated)
        self.store.schedule_save()
        self._touch(updated["lawn_id"])
        await self.async_refresh()
        return updated

    async def async_delete_entry(self, entry_id: str) -> dict[str, Any]:
        entry = self.store.delete_entry(entry_id)
        if entry is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="entry_not_found",
                translation_placeholders={"entry_id": entry_id},
            )
        self.store.schedule_save()
        self._touch(entry["lawn_id"])
        await self.async_refresh()
        return entry

    def has_entry(self, entry_id: str) -> bool:
        return self.store.get_entry(entry_id) is not None

    def _touch(self, lawn_id: str) -> None:
        self._log_modified[lawn_id] = dt_util.now()

    async def _async_add(self, entry: dict[str, Any]) -> None:
        self.store.add_entry(entry)
        self.store.schedule_save()
        self._touch(entry["lawn_id"])
        lawn = self.get_lawn(entry["lawn_id"])
        self.hass.bus.async_fire(
            EVENT_ENTRY_LOGGED,
            {
                "entry_id": entry["id"],
                "device_id": self.lawn_device_id(lawn.id),
                "lawn": lawn.name,
                "kind": entry["kind"],
                "date": entry["date"],
                "summary": entry_summary(entry, self.height_unit),
            },
        )
        # A back-dated PGR application may need older temperatures fetched.
        await self.async_refresh()

    def history(
        self,
        lawn_ids: list[str] | None,
        kinds: list[str] | None,
        start: date | None,
        end: date | None,
    ) -> list[dict[str, Any]]:
        out = []
        for entry in self.store.entries:
            if lawn_ids and entry["lawn_id"] not in lawn_ids:
                continue
            if kinds and entry["kind"] not in kinds:
                continue
            day = entry_date(entry)
            if (start and day < start) or (end and day > end):
                continue
            out.append({**entry, "lawn": self._lawn_name(entry["lawn_id"])})
        return out

    def daily_gdd_rows(self, lawn_id: str, start: date, end: date) -> list[dict[str, Any]]:
        lawn = self.get_lawn(lawn_id)
        rows = []
        day = start
        while day <= end:
            record = self.store.get_day(day)
            rows.append(
                {
                    "date": day.isoformat(),
                    "mean": (record or {}).get("mean"),
                    "min": (record or {}).get("min"),
                    "max": (record or {}).get("max"),
                    "hours": (record or {}).get("hours", 0),
                    "source": (record or {}).get("source", SOURCE_NONE),
                    "gdd": round(daily_gdd(self._day_temp(record, lawn.base_temp), lawn.base_temp), 2),
                }
            )
            day += timedelta(days=1)
        return rows

    def _lawn_name(self, lawn_id: str) -> str:
        sub = self.config_entry.subentries.get(lawn_id)
        return sub.title if sub else lawn_id


def _product_fields(product: Product, rate: float | None, rate_unit: str | None) -> dict[str, Any]:
    """What an application records about one product (empty values left out)."""
    fields = {
        "product_id": product.id or None,
        "product_name": product.name,
        "product_type": product.product_type,
        "active_ingredient": product.active_ingredient,
        "is_pgr": product.is_pgr,
        "rate": rate if rate is not None else product.rate,
        "rate_unit": rate_unit or product.rate_unit,
        "moa_group": product.moa_group,
        "analysis": {
            k: v
            for k, v in (("n", product.n), ("p", product.p), ("k", product.k), ("density", product.density))
            if v
        }
        or None,
    }
    return {k: v for k, v in fields.items() if v is not None and v != ""}


def _derive_amounts(target: dict[str, Any], area: float | None) -> None:
    """Total product and nutrients for one product's rate, in place."""
    for key in ("total_amount", "total_unit", "n_g_m2", "p_g_m2", "k_g_m2"):
        target.pop(key, None)
    rate, unit = target.get("rate"), target.get("rate_unit")
    if rate is None or not unit:
        return
    if area:
        amount, total_unit = total_product(rate, unit, area)
        target["total_amount"], target["total_unit"] = round(amount, 1), total_unit
    analysis = target.get("analysis") or {}
    for nutrient in ("n", "p", "k"):
        if pct := analysis.get(nutrient):
            target[f"{nutrient}_g_m2"] = round(
                nutrient_g_per_m2(rate, unit, pct, analysis.get("density")), 3
            )


def _derive_application(entry: dict[str, Any]) -> None:
    """(Re)calculate totals and nutrients for an application entry in place."""
    components = entry.get("products")
    if not components:
        _derive_amounts(entry, entry.get("area_m2"))
        return
    for component in components:
        _derive_amounts(component, entry.get("area_m2"))
    for nutrient in ("n", "p", "k"):
        key = f"{nutrient}_g_m2"
        entry.pop(key, None)
        if total := sum(c.get(key) or 0 for c in components):
            entry[key] = round(total, 3)
