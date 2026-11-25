"""Sensors for Turf Manager."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import TurfConfigEntry
from .const import ACTIVITIES_ENABLED_BY_DEFAULT, ACTIVITY_TYPES, DOMAIN, SUBENTRY_LAWN
from .coordinator import COMPARISONS, TurfCoordinator
from .entity import TurfLawnEntity
from .models import IrrigationZone, Lawn, LawnState, entry_start
from .units import HEIGHT_UNIT_IN

GDD_UNIT = "GDD"


@dataclass(frozen=True, kw_only=True)
class LawnSensorDescription(SensorEntityDescription):
    """Describes a lawn sensor."""

    value_fn: Callable[[LawnState], Any]
    attrs_fn: Callable[[LawnState, TurfCoordinator], dict[str, Any]] | None = None
    enabled_fn: Callable[[Lawn], bool] | None = None
    requires_fallback: bool = False


def _start(entry: dict[str, Any] | None) -> datetime | None:
    return entry_start(entry) if entry else None


def _pgr_attrs(state: LawnState, coordinator: TurfCoordinator) -> dict[str, Any]:
    return {
        "last_application": state.last_pgr["date"] if state.last_pgr else None,
        "product": state.pgr_product.name if state.pgr_product else None,
        "target": state.target,
        "gdd_completed_days": state.gdd_completed,
        "gdd_today": round(state.gdd_today, 2),
        "days_since_application": state.days_since_pgr,
        "base_temperature": state.base_temp,
        "method": coordinator.method,
        "incomplete_days": state.incomplete_days,
        "missing_days": state.missing_days,
    }


def _comparison_attrs(key: str) -> Callable[[LawnState, TurfCoordinator], dict[str, Any]]:
    source, method = COMPARISONS[key]

    def attrs(state: LawnState, coordinator: TurfCoordinator) -> dict[str, Any]:
        value = state.comparisons.get(key)
        difference = percent = None
        if state.gdd_total is not None and value is not None:
            difference = round(value - state.gdd_total, 1)
            if state.gdd_total:
                percent = round(difference / state.gdd_total * 100, 1)
        return {
            "difference": difference,
            "difference_percent": percent,
            "main_gdd": state.gdd_total,
            "sensor": coordinator.source.primary if source == "main" else coordinator.source.fallback,
            "method": method,
            "missing_days": state.missing_days if source == "main" else state.fallback_missing_days,
        }

    return attrs


def _comparison(key: str, description_key: str) -> LawnSensorDescription:
    return LawnSensorDescription(
        key=description_key,
        native_unit_of_measurement=GDD_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s, k=key: s.comparisons.get(k),
        attrs_fn=_comparison_attrs(key),
        requires_fallback=COMPARISONS[key][0] == "fallback",
    )


def _watering_attrs(state: LawnState, coordinator: TurfCoordinator) -> dict[str, Any]:
    zones = sorted(
        (z for z in coordinator.zones().values() if z.lawn_id == state.lawn_id),
        key=lambda z: z.name.casefold(),
    )
    registry = er.async_get(coordinator.hass)
    return {
        "runs": state.watering_runs_7d,
        "manual_minutes": state.watering_manual_7d,
        "by_zone": {z.name: round(state.watering_by_zone.get(z.id, 0), 1) for z in zones},
        # Used by the dashboard to show a row per zone.
        "zones": [
            {
                "name": z.name,
                "entity_id": z.entity_id,
                "minutes_entity": registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{z.lawn_id}_{z.id}_zone_minutes_7d"
                ),
                "last_run_entity": registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{z.lawn_id}_{z.id}_zone_last_run"
                ),
            }
            for z in zones
        ],
    }


def _progress_attrs(state: LawnState, coordinator: TurfCoordinator) -> dict[str, Any]:
    return {
        "gdd": state.gdd_total,
        "target": state.target,
        "projected_due": state.projected_due.isoformat() if state.projected_due else None,
        "projection_method": state.projection_method,
        "last_application": state.last_pgr["date"] if state.last_pgr else None,
        "days_since_application": state.days_since_pgr,
    }


def _projection_attrs(state: LawnState, coordinator: TurfCoordinator) -> dict[str, Any]:
    return {
        "projection_method": state.projection_method,
        "forecast_days_available": coordinator.data.forecast_days if coordinator.data else 0,
        "projection": [
            {"date": day.isoformat(), "gdd": gdd, "source": source}
            for day, gdd, source in state.projection[:30]
        ],
    }


def _growth_attrs(state: LawnState, coordinator: TurfCoordinator) -> dict[str, Any]:
    phase = None
    if state.relative_growth is not None:
        phase = "suppression" if state.relative_growth < 100 else "rebound"
        if state.relative_growth == 100:
            phase = "none"
    return {
        "phase": phase,
        "model": state.pgr_product.pgr_model if state.pgr_product else None,
        "model_validated": state.model_validated,
    }


def _mow_attrs(state: LawnState, coordinator: TurfCoordinator) -> dict[str, Any]:
    entry = state.last_mow or {}
    return {
        "mower_type": entry.get("mower_type"),
        "height_mm": entry.get("height_mm"),
        "clippings_l": entry.get("clippings_l"),
        "notes": entry.get("notes"),
        "entry_id": entry.get("id"),
    }


def _application_attrs(state: LawnState, coordinator: TurfCoordinator) -> dict[str, Any]:
    entry = state.last_application or {}
    return {
        "products": [
            " ".join(
                str(part)
                for part in (
                    c.get("product_name"),
                    f"{c['rate']:g}" if c.get("rate") is not None else None,
                    c.get("rate_unit") if c.get("rate") is not None else None,
                )
                if part
            )
            for c in entry.get("products") or []
        ]
        or None,
        "product": entry.get("product_name"),
        "product_type": entry.get("product_type"),
        "rate": entry.get("rate"),
        "rate_unit": entry.get("rate_unit"),
        "notes": entry.get("notes"),
        "entry_id": entry.get("id"),
    }


def _activity_attrs(activity: str) -> Callable[[LawnState, TurfCoordinator], dict[str, Any]]:
    def attrs(state: LawnState, coordinator: TurfCoordinator) -> dict[str, Any]:
        entry = state.last_activity.get(activity) or {}
        return {"details": entry.get("details"), "notes": entry.get("notes"), "entry_id": entry.get("id")}

    return attrs


LAWN_SENSORS: tuple[LawnSensorDescription, ...] = (
    LawnSensorDescription(
        key="gdd_since_pgr",
        native_unit_of_measurement=GDD_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s.gdd_total,
        attrs_fn=_pgr_attrs,
    ),
    # GDD since PGR counted other ways, for the dashboard's comparison box.
    _comparison("main_mean", "gdd_since_pgr_mean"),
    _comparison("main_minmax", "gdd_since_pgr_minmax"),
    _comparison("fallback_mean", "gdd_since_pgr_fallback"),
    _comparison("fallback_minmax", "gdd_since_pgr_fallback_minmax"),
    LawnSensorDescription(
        key="pgr_progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda s: s.progress,
        attrs_fn=_progress_attrs,
    ),
    LawnSensorDescription(
        key="gdd_today",
        native_unit_of_measurement=GDD_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: round(s.gdd_today, 2),
    ),
    LawnSensorDescription(
        key="pgr_next_due",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda s: s.projected_due,
        attrs_fn=_projection_attrs,
    ),
    LawnSensorDescription(
        key="pgr_relative_growth",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda s: s.relative_growth,
        attrs_fn=_growth_attrs,
        enabled_fn=lambda lawn: lawn.base_temp == 0,
    ),
    LawnSensorDescription(
        key="last_mowed",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: _start(s.last_mow),
        attrs_fn=_mow_attrs,
    ),
    LawnSensorDescription(
        key="last_cut_height",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        suggested_display_precision=1,
        value_fn=lambda s: (s.last_mow or {}).get("height_mm"),
    ),
    LawnSensorDescription(
        key="last_application",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: _start(s.last_application),
        attrs_fn=_application_attrs,
    ),
    LawnSensorDescription(
        key="nitrogen_season",
        native_unit_of_measurement="g/m²",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=1,
        value_fn=lambda s: s.nitrogen_season,
    ),
    LawnSensorDescription(
        key="last_watered",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: _start(s.last_watering),
        attrs_fn=lambda s, c: {
            "zone": (s.last_watering or {}).get("zone_name"),
            "minutes": (s.last_watering or {}).get("duration_min"),
            "source": (s.last_watering or {}).get("source"),
            "entry_id": (s.last_watering or {}).get("id"),
        },
    ),
    LawnSensorDescription(
        key="watering_7d",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda s: s.watering_7d,
        attrs_fn=_watering_attrs,
    ),
    LawnSensorDescription(
        key="log_entries",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.log_count,
        attrs_fn=lambda s, c: {
            "last_modified": s.log_modified.isoformat() if s.log_modified else None
        },
    ),
    *(
        LawnSensorDescription(
            key=f"last_{activity}",
            device_class=SensorDeviceClass.TIMESTAMP,
            entity_registry_enabled_default=activity in ACTIVITIES_ENABLED_BY_DEFAULT,
            value_fn=lambda s, a=activity: _start(s.last_activity.get(a)),
            attrs_fn=_activity_attrs(activity),
        )
        for activity in ACTIVITY_TYPES
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TurfConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_LAWN:
            continue
        async_add_entities(
            [
                *(
                    LawnSensor(coordinator, subentry_id, description)
                    for description in LAWN_SENSORS
                    if coordinator.source.fallback or not description.requires_fallback
                ),
                MixSensor(coordinator, subentry_id),
                *(
                    ZoneSensor(coordinator, zone, which)
                    for zone in coordinator.zones().values()
                    if zone.lawn_id == subentry_id
                    for which in ("zone_last_run", "zone_minutes_7d")
                ),
                MeanTemperatureSensor(coordinator, subentry_id, "mean_temperature_today", "today"),
                MeanTemperatureSensor(
                    coordinator, subentry_id, "mean_temperature_yesterday", "yesterday"
                ),
            ],
            config_subentry_id=subentry_id,
        )


class LawnSensor(TurfLawnEntity, SensorEntity):
    """A calculated lawn sensor."""

    entity_description: LawnSensorDescription

    def __init__(
        self, coordinator: TurfCoordinator, lawn_id: str, description: LawnSensorDescription
    ) -> None:
        super().__init__(coordinator, lawn_id, description.key)
        self.entity_description = description
        if description.enabled_fn is not None:
            self._attr_entity_registry_enabled_default = description.enabled_fn(self.lawn)
        if (
            description.device_class == SensorDeviceClass.DISTANCE
            and coordinator.height_unit == HEIGHT_UNIT_IN
        ):
            self._attr_suggested_unit_of_measurement = UnitOfLength.INCHES

    @property
    def native_value(self) -> Any:
        state = self.lawn_state
        return self.entity_description.value_fn(state) if state else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        state = self.lawn_state
        if state is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(state, self.coordinator)

    @property
    def last_reset(self) -> datetime | None:
        if self.entity_description.state_class != SensorStateClass.TOTAL:
            return None
        state = self.lawn_state
        if state is None or state.season_start is None:
            return None
        return dt_util.start_of_local_day(state.season_start)


class ZoneSensor(TurfLawnEntity, SensorEntity):
    """A sprinkler zone's last run, or its minutes over the last 7 days (on its lawn's device)."""

    def __init__(self, coordinator: TurfCoordinator, zone: IrrigationZone, which: str) -> None:
        super().__init__(coordinator, zone.lawn_id, which)
        self._zone_id = zone.id
        self._which = which
        self._attr_unique_id = f"{zone.lawn_id}_{zone.id}_{which}"
        self._attr_translation_placeholders = {"zone": zone.name}
        if which == "zone_last_run":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        else:
            self._attr_device_class = SensorDeviceClass.DURATION
            self._attr_native_unit_of_measurement = UnitOfTime.MINUTES
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_suggested_display_precision = 0

    @property
    def native_value(self) -> Any:
        state = self.lawn_state
        if state is None:
            return None
        if self._which == "zone_last_run":
            return _start(state.last_by_zone.get(self._zone_id))
        return round(state.watering_by_zone.get(self._zone_id, 0), 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._which != "zone_last_run" or self.lawn_state is None:
            return None
        entry = self.lawn_state.last_by_zone.get(self._zone_id) or {}
        return {"minutes": entry.get("duration_min"), "source": entry.get("source")}


class MixSensor(TurfLawnEntity, SensorEntity, RestoreEntity):
    """The mix being built on the dashboard: how many products, and which.

    Its attributes drive the dashboard's mix card. The mix is restored after a
    restart so a half-built mix isn't lost.
    """

    def __init__(self, coordinator: TurfCoordinator, lawn_id: str) -> None:
        super().__init__(coordinator, lawn_id, "application_mix")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.coordinator.mix_items(self._lawn_id):
            return
        if (last := await self.async_get_last_state()) is None:
            return
        products = self.coordinator.products()
        self.staged["mix"] = [
            {"product_id": item["product_id"], "rate": item.get("rate"), "rate_unit": item.get("unit")}
            for item in last.attributes.get("products") or []
            if isinstance(item, dict) and item.get("product_id") in products
        ]

    @property
    def native_value(self) -> int:
        return len(self.coordinator.mix_products(self._lawn_id))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        items = [
            {"product_id": product.id, "product": product.name, "rate": rate, "unit": unit}
            for product, rate, unit in self.coordinator.mix_products(self._lawn_id)
        ]
        return {"products": items}


class MeanTemperatureSensor(TurfLawnEntity, SensorEntity):
    """Daily mean temperature used for the lawn's GDD (today so far, or yesterday).

    The temperature comes from the site's sensors, so every lawn shows the same
    value; it lives on each lawn so no device sits outside a lawn.
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: TurfCoordinator, lawn_id: str, key: str, which: str) -> None:
        super().__init__(coordinator, lawn_id, key)
        self._which = which

    def _record(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        return getattr(self.coordinator.data, self._which)

    @property
    def native_value(self) -> float | None:
        record = self._record()
        return record.get("mean") if record else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        sources = {
            "temperature_sensor": self.coordinator.source.primary,
            "weather_entity": self.coordinator.source.weather,
        }
        record = self._record()
        if not record:
            return sources
        return {
            **sources,
            "min": record.get("min"),
            "max": record.get("max"),
            "hours_of_data": record.get("hours"),
            "source": record.get("source"),
            "date": (
                dt_util.now().date() if self._which == "today" else _yesterday()
            ).isoformat(),
        }


def _yesterday() -> date:
    return date.fromordinal(dt_util.now().date().toordinal() - 1)
