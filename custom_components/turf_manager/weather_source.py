"""Read daily temperatures and forecasts from existing Home Assistant entities.

Completed days come from recorder long-term statistics (hourly mean/min/max),
which Home Assistant keeps indefinitely for sensors with
``state_class: measurement``. The daily mean is the average of the hourly
time-weighted means for the local day. Sensors without statistics fall back to
raw state history (limited to the recorder purge window).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_FALLBACK_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_RAIN_SENSOR,
    CONF_TEMP_SENSOR,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SENSOR,
    LOGGER,
    MIN_HOURS_COMPLETE,
    SOURCE_FALLBACK,
    SOURCE_PRIMARY,
)
from .gdd import time_weighted_stats

_CELSIUS = UnitOfTemperature.CELSIUS
_TEMP_UNITS = {"temperature": _CELSIUS}
_PERIOD_HOURS = {"hour": 1.0, "5minute": 5 / 60}


def _local_midnight(day: date) -> datetime:
    return dt_util.start_of_local_day(day)


def _to_celsius(value: float, unit: str | None) -> float:
    if unit in (None, _CELSIUS):
        return value
    return TemperatureConverter.convert(value, unit, _CELSIUS)


def _row_start_ts(row: Mapping[str, Any]) -> float:
    start = row["start"]
    return start.timestamp() if isinstance(start, datetime) else float(start)


class WeatherSource:
    """Fetches temperatures for a site."""

    def __init__(self, hass: HomeAssistant, config: Mapping[str, Any]) -> None:
        self.hass = hass
        self.primary: str = config[CONF_TEMP_SENSOR]
        self.fallback: str | None = config.get(CONF_FALLBACK_SENSOR) or None
        self.weather: str | None = config.get(CONF_WEATHER_ENTITY) or None
        self.snapshot_sensors: dict[str, str] = {
            key: entity_id
            for key, entity_id in (
                ("temperature", self.primary),
                ("humidity", config.get(CONF_HUMIDITY_SENSOR)),
                ("wind_speed", config.get(CONF_WIND_SENSOR)),
                ("rain", config.get(CONF_RAIN_SENSOR)),
            )
            if entity_id
        }
        self.primary_has_statistics: bool | None = None

    # --- Completed days ----------------------------------------------------

    async def async_fetch_days(self, start: date, end: date) -> dict[date, dict[str, Any]]:
        """Daily records for local days start..end inclusive."""
        start_dt = _local_midnight(start)
        end_dt = _local_midnight(end + timedelta(days=1))
        days = await self._async_entity_days(self.primary, start_dt, end_dt, "hour")
        if days is None:
            self.primary_has_statistics = False
            days = await self._async_history_days(self.primary, start_dt, end_dt)
        else:
            self.primary_has_statistics = True
        for record in days.values():
            record["source"] = SOURCE_PRIMARY

        if self.fallback:
            short = [
                d
                for d in _date_range(start, end)
                if days.get(d, {}).get("hours", 0) < MIN_HOURS_COMPLETE
            ]
            if short:
                fb = await self._async_entity_days(
                    self.fallback,
                    _local_midnight(min(short)),
                    _local_midnight(max(short) + timedelta(days=1)),
                    "hour",
                )
                if fb is None:
                    fb = await self._async_history_days(
                        self.fallback,
                        _local_midnight(min(short)),
                        _local_midnight(max(short) + timedelta(days=1)),
                    )
                for day in short:
                    candidate = fb.get(day)
                    if candidate and candidate["hours"] > days.get(day, {}).get("hours", 0):
                        candidate["source"] = SOURCE_FALLBACK
                        days[day] = candidate
        return days

    async def async_fetch_fallback_days(
        self, start: date, end: date
    ) -> dict[date, dict[str, Any]]:
        """Daily records from the fallback sensor alone, for comparison."""
        if not self.fallback:
            return {}
        start_dt = _local_midnight(start)
        end_dt = _local_midnight(end + timedelta(days=1))
        days = await self._async_entity_days(self.fallback, start_dt, end_dt, "hour")
        if days is None:
            days = await self._async_history_days(self.fallback, start_dt, end_dt)
        return days

    async def async_fetch_fallback_today(self) -> dict[str, Any] | None:
        """Today so far from the fallback sensor alone."""
        if not self.fallback:
            return None
        return await self._today_for(
            self.fallback, _local_midnight(dt_util.now().date()), dt_util.utcnow()
        )

    async def async_fetch_today(self) -> dict[str, Any] | None:
        """Running record for today so far (5-minute statistics)."""
        today = dt_util.now().date()
        start_dt = _local_midnight(today)
        end_dt = dt_util.utcnow()
        record = await self._today_for(self.primary, start_dt, end_dt)
        source = SOURCE_PRIMARY
        if self.fallback and (record is None or record["hours"] < 1):
            fb = await self._today_for(self.fallback, start_dt, end_dt)
            if fb and fb["hours"] > (record or {}).get("hours", 0):
                record, source = fb, SOURCE_FALLBACK
        if record is None:
            return None
        record["source"] = source
        record["final"] = False
        return record

    async def _today_for(
        self, entity_id: str, start_dt: datetime, end_dt: datetime
    ) -> dict[str, Any] | None:
        days = await self._async_entity_days(entity_id, start_dt, end_dt, "5minute")
        if days is None:
            days = await self._async_history_days(entity_id, start_dt, end_dt)
        return days.get(dt_util.as_local(start_dt).date())

    async def _async_entity_days(
        self, entity_id: str, start_dt: datetime, end_dt: datetime, period: str
    ) -> dict[date, dict[str, Any]] | None:
        """Group recorder statistics by local day. None if the entity has none."""
        try:
            result = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                dt_util.as_utc(start_dt),
                dt_util.as_utc(end_dt),
                {entity_id},
                period,
                _TEMP_UNITS,
                {"mean", "min", "max"},
            )
        except HomeAssistantError as err:
            LOGGER.warning("Could not read statistics for %s: %s", entity_id, err)
            return None
        rows = result.get(entity_id)
        if not rows:
            if self._has_statistics(entity_id):
                return {}
            return None

        grouped: dict[date, list[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            if row.get("mean") is None:
                continue
            local = dt_util.as_local(dt_util.utc_from_timestamp(_row_start_ts(row)))
            grouped[local.date()].append(row)

        step = _PERIOD_HOURS[period]
        days: dict[date, dict[str, Any]] = {}
        for day, day_rows in grouped.items():
            means = [r["mean"] for r in day_rows]
            mins = [r["min"] for r in day_rows if r.get("min") is not None]
            maxes = [r["max"] for r in day_rows if r.get("max") is not None]
            days[day] = {
                "mean": round(sum(means) / len(means), 3),
                "min": round(min(mins), 2) if mins else None,
                "max": round(max(maxes), 2) if maxes else None,
                "hours": round(len(day_rows) * step, 2),
            }
        return days

    def _has_statistics(self, entity_id: str) -> bool:
        """Whether the recorder keeps long-term statistics for this entity."""
        state = self.hass.states.get(entity_id)
        return bool(state and state.attributes.get("state_class"))

    async def _async_history_days(
        self, entity_id: str, start_dt: datetime, end_dt: datetime
    ) -> dict[date, dict[str, Any]]:
        """Time-weighted daily stats from raw state history."""
        unit = None
        if state := self.hass.states.get(entity_id):
            unit = state.attributes.get("unit_of_measurement")
        history = await get_instance(self.hass).async_add_executor_job(
            partial(
                state_changes_during_period,
                self.hass,
                dt_util.as_utc(start_dt),
                dt_util.as_utc(end_dt),
                entity_id,
                no_attributes=True,
                include_start_time_state=True,
            )
        )
        samples: list[tuple[float, float]] = []
        for hist_state in history.get(entity_id, []):
            if hist_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                continue
            try:
                value = _to_celsius(float(hist_state.state), unit)
            except ValueError:
                continue
            samples.append((hist_state.last_changed.timestamp(), value))

        days: dict[date, dict[str, Any]] = {}
        day = dt_util.as_local(start_dt).date()
        end_local = dt_util.as_local(end_dt)
        while _local_midnight(day) < end_local:
            day_start = _local_midnight(day)
            day_end = min(_local_midnight(day + timedelta(days=1)), end_local)
            stats = time_weighted_stats(samples, day_start.timestamp(), day_end.timestamp())
            if stats.mean is not None:
                days[day] = {
                    "mean": round(stats.mean, 3),
                    "min": round(stats.minimum, 2) if stats.minimum is not None else None,
                    "max": round(stats.maximum, 2) if stats.maximum is not None else None,
                    "hours": round(stats.hours, 2),
                }
            day += timedelta(days=1)
        return days

    # --- Forecast ------------------------------------------------------------

    async def async_fetch_forecast(self) -> dict[date, tuple[float, float]]:
        """Forecast (low, high) °C per local day from the weather entity."""
        if not self.weather or self.hass.states.get(self.weather) is None:
            return {}
        state = self.hass.states.get(self.weather)
        unit = state.attributes.get("temperature_unit", self.hass.config.units.temperature_unit)
        for forecast_type in ("daily", "twice_daily", "hourly"):
            try:
                response = await self.hass.services.async_call(
                    "weather",
                    "get_forecasts",
                    {"entity_id": self.weather, "type": forecast_type},
                    blocking=True,
                    return_response=True,
                )
            except HomeAssistantError:
                continue
            forecast = (response or {}).get(self.weather, {}).get("forecast") or []
            if forecast:
                return _group_forecast(forecast, unit, hourly=forecast_type == "hourly")
        LOGGER.debug("No forecast available from %s", self.weather)
        return {}

    # --- Weather snapshot ------------------------------------------------------

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Current readings of the configured sensors, for spray records."""
        result: dict[str, dict[str, Any]] = {}
        for key, entity_id in self.snapshot_sensors.items():
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                continue
            try:
                value = round(float(state.state), 1)
            except ValueError:
                continue
            result[key] = {"value": value, "unit": state.attributes.get("unit_of_measurement")}
        return result


def _group_forecast(
    forecast: list[dict[str, Any]], unit: str, *, hourly: bool
) -> dict[date, tuple[float, float]]:
    """Collapse forecast entries into one (low, high) per local day."""
    highs: dict[date, list[float]] = defaultdict(list)
    lows: dict[date, list[float]] = defaultdict(list)
    for item in forecast:
        when = dt_util.parse_datetime(str(item.get("datetime", "")))
        temp = item.get("temperature")
        if when is None or temp is None:
            continue
        day = dt_util.as_local(when).date()
        highs[day].append(_to_celsius(float(temp), unit))
        low = item.get("templow")
        lows[day].append(_to_celsius(float(low if low is not None else temp), unit))
    today = dt_util.now().date()
    result: dict[date, tuple[float, float]] = {}
    for day, day_highs in highs.items():
        # Hourly forecasts only describe a whole day when most hours are present.
        if hourly and day != today and len(day_highs) < 18:
            continue
        result[day] = (min(lows[day]), max(day_highs))
    return result


def _date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


async def async_entity_history(
    hass: HomeAssistant, entity_id: str, start: datetime
) -> list[Any]:
    """Recorded states of an entity from ``start`` to now (oldest first)."""
    history = await get_instance(hass).async_add_executor_job(
        partial(
            state_changes_during_period,
            hass,
            dt_util.as_utc(start),
            None,
            entity_id,
            no_attributes=True,
            include_start_time_state=True,
        )
    )
    return history.get(entity_id, [])
