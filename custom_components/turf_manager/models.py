"""Data models for Turf Manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ACTIVE_INGREDIENT,
    CONF_AREA,
    CONF_BASE_TEMP,
    CONF_DENSITY,
    CONF_GDD_INTERVAL,
    CONF_GDD_TARGET,
    CONF_GRASS_TYPE,
    CONF_K,
    CONF_MOA_GROUP,
    CONF_N,
    CONF_NOTES,
    CONF_P,
    CONF_PGR_MODEL,
    CONF_PGR_PRODUCT,
    CONF_PRODUCT_TYPE,
    CONF_RATE,
    CONF_RATE_UNIT,
    DEFAULT_BASE_TEMPS,
    DEFAULT_GDD_TARGET,
    GRASS_WARM,
    KIND_ACTIVITY,
    KIND_APPLICATION,
    KIND_MOW,
    PGR_MODEL_NONE,
    PRODUCT_PGR,
)
from .units import HEIGHT_UNIT_IN, mm_to_unit


@dataclass(frozen=True, slots=True)
class Lawn:
    """A lawn area (config subentry)."""

    id: str
    name: str
    grass_type: str
    base_temp: float
    area_m2: float | None
    gdd_target: float
    pgr_product_id: str | None

    @classmethod
    def from_subentry(cls, subentry: ConfigSubentry) -> Lawn:
        data = subentry.data
        grass = data.get(CONF_GRASS_TYPE, GRASS_WARM)
        return cls(
            id=subentry.subentry_id,
            name=subentry.title,
            grass_type=grass,
            base_temp=float(data.get(CONF_BASE_TEMP, DEFAULT_BASE_TEMPS[grass])),
            area_m2=data.get(CONF_AREA),
            gdd_target=float(data.get(CONF_GDD_TARGET, DEFAULT_GDD_TARGET)),
            pgr_product_id=data.get(CONF_PGR_PRODUCT) or None,
        )


@dataclass(frozen=True, slots=True)
class Product:
    """A product in the library (config subentry)."""

    id: str
    name: str
    product_type: str
    active_ingredient: str | None = None
    rate: float | None = None
    rate_unit: str | None = None
    n: float | None = None
    p: float | None = None
    k: float | None = None
    density: float | None = None
    gdd_interval: float | None = None
    pgr_model: str | None = None
    moa_group: str | None = None
    notes: str | None = None

    @property
    def is_pgr(self) -> bool:
        return self.product_type == PRODUCT_PGR

    @classmethod
    def from_subentry(cls, subentry: ConfigSubentry) -> Product:
        data = subentry.data
        model = data.get(CONF_PGR_MODEL)
        return cls(
            id=subentry.subentry_id,
            name=subentry.title,
            product_type=data.get(CONF_PRODUCT_TYPE, "other"),
            active_ingredient=data.get(CONF_ACTIVE_INGREDIENT),
            rate=data.get(CONF_RATE),
            rate_unit=data.get(CONF_RATE_UNIT),
            n=data.get(CONF_N),
            p=data.get(CONF_P),
            k=data.get(CONF_K),
            density=data.get(CONF_DENSITY),
            gdd_interval=data.get(CONF_GDD_INTERVAL),
            pgr_model=None if model in (None, PGR_MODEL_NONE) else model,
            moa_group=data.get(CONF_MOA_GROUP),
            notes=data.get(CONF_NOTES),
        )


@dataclass(slots=True)
class LawnState:
    """Calculated state for one lawn, produced by the coordinator."""

    lawn_id: str
    target: float
    base_temp: float
    last_pgr: dict[str, Any] | None = None
    pgr_product: Product | None = None
    gdd_completed: float | None = None
    gdd_today: float = 0.0
    gdd_total: float | None = None
    progress: float | None = None
    due: bool = False
    days_since_pgr: int | None = None
    projected_due: date | None = None
    projection_method: str | None = None
    projection: list[tuple[date, float, str]] = field(default_factory=list)
    relative_growth: float | None = None
    model_validated: bool = False
    incomplete_days: list[str] = field(default_factory=list)
    missing_days: list[str] = field(default_factory=list)
    # The same count by other sensors and methods, for comparison
    # (keys from coordinator.COMPARISONS: main_mean, main_minmax, fallback_mean, ...).
    comparisons: dict[str, float] = field(default_factory=dict)
    fallback_missing_days: list[str] = field(default_factory=list)
    last_mow: dict[str, Any] | None = None
    last_application: dict[str, Any] | None = None
    last_activity: dict[str, dict[str, Any]] = field(default_factory=dict)
    nitrogen_season: float = 0.0
    season_start: date | None = None
    log_count: int = 0
    log_modified: datetime | None = None


@dataclass(slots=True)
class SiteState:
    """Calculated state for the whole site."""

    today: dict[str, Any] | None
    yesterday: dict[str, Any] | None
    lawns: dict[str, LawnState]
    forecast_days: int = 0


# --- Log entry helpers ----------------------------------------------------


def entry_start(entry: dict[str, Any]) -> datetime:
    """Aware start datetime of a log entry."""
    parsed = dt_util.parse_datetime(entry["start"])
    if parsed is None:  # pragma: no cover - entries are always written with a start
        raise ValueError(f"Bad start in entry {entry.get('id')}")
    return parsed


def entry_date(entry: dict[str, Any]) -> date:
    """Local date of a log entry."""
    return date.fromisoformat(entry["date"])


def format_height(height_mm: float | None, unit: str) -> str:
    """Human-readable cut height in the preferred unit."""
    if height_mm is None:
        return ""
    if unit == HEIGHT_UNIT_IN:
        return f'{mm_to_unit(height_mm, unit):.2g}"'
    return f"{height_mm:g} mm"


def _rate_text(item: dict[str, Any]) -> str:
    if item.get("rate") is None:
        return ""
    return f" {item['rate']:g} {item.get('rate_unit') or ''}".rstrip()


def entry_summary(entry: dict[str, Any], height_unit: str) -> str:
    """One-line summary used for calendar events and the logbook."""
    kind = entry.get("kind")
    if kind == KIND_APPLICATION:
        if components := entry.get("products"):
            label = "PGR mix" if entry.get("is_pgr") else "Mix"
            return f"{label}: " + " + ".join(
                f"{c.get('product_name', '?')}{_rate_text(c)}" for c in components
            )
        prefix = "PGR: " if entry.get("is_pgr") else ""
        return f"{prefix}{entry.get('product_name') or 'Application'}{_rate_text(entry)}"
    if kind == KIND_MOW:
        parts = ["Mow"]
        if entry.get("height_mm") is not None:
            parts.append(format_height(entry["height_mm"], height_unit))
        if entry.get("mower_type"):
            parts.append(f"({entry['mower_type'].replace('_', ' ')})")
        return " ".join(parts)
    if kind == KIND_ACTIVITY:
        label = (entry.get("activity") or "activity").replace("_", " ").capitalize()
        return f"{label}: {entry['details']}" if entry.get("details") else label
    return "Lawn care"


def entry_description(entry: dict[str, Any]) -> str:
    """Multi-line details for calendar event descriptions."""
    lines: list[str] = []
    if entry.get("kind") == KIND_APPLICATION:
        for item in entry.get("products") or [entry]:
            name = f"{item.get('product_name')}: " if entry.get("products") else ""
            if item.get("active_ingredient"):
                lines.append(f"{name}Active: {item['active_ingredient']}")
            if item.get("total_amount") is not None:
                lines.append(
                    f"{name}Total {item['total_amount']:.0f} {item.get('total_unit', '')}"
                    f" over {entry.get('area_m2', 0):g} m²"
                )
            if item.get("moa_group"):
                lines.append(f"{name}MoA group: {item['moa_group']}")
        if entry.get("n_g_m2"):
            lines.append(f"N: {entry['n_g_m2']:.2f} g/m²")
    if entry.get("clippings_l") is not None:
        lines.append(f"Clippings: {entry['clippings_l']:g} L")
    if weather := entry.get("weather"):
        bits = [f"{k.replace('_', ' ')} {v['value']}{v.get('unit') or ''}" for k, v in weather.items()]
        lines.append("Weather: " + ", ".join(bits))
    if entry.get("notes"):
        lines.append(entry["notes"])
    lines.append(f"Entry id: {entry['id']}")
    return "\n".join(lines)
