"""Actions (services) for Turf Manager."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    ACTIVITY_TYPES,
    DOMAIN,
    ENTRY_KINDS,
    MOWER_TYPES,
    SUBENTRY_LAWN,
)
from .models import entry_summary
from .units import HEIGHT_UNIT_IN, HEIGHT_UNIT_MM, RATE_UNITS, unit_to_mm

if TYPE_CHECKING:
    from .coordinator import TurfCoordinator
    from .models import Product

ATTR_DEVICE_ID = "device_id"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

_DEVICES = vol.All(cv.ensure_list, [cv.string])
_WHEN = {
    vol.Optional("date"): cv.date,
    vol.Optional("datetime"): cv.datetime,
}

_MIX_ITEM = vol.Schema(
    {
        vol.Required("product"): cv.string,
        vol.Optional("rate"): vol.Coerce(float),
        vol.Optional("rate_unit"): vol.In(RATE_UNITS),
    }
)


def _one_product_or_mix(data: dict[str, Any]) -> dict[str, Any]:
    if ("product" in data) == ("products" in data):
        raise vol.Invalid("Give either 'product' or 'products' (for a mix), not both")
    if "products" in data and ("rate" in data or "rate_unit" in data):
        raise vol.Invalid("For a mix, give each product's rate inside 'products'")
    return data


LOG_APPLICATION_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(ATTR_DEVICE_ID): _DEVICES,
            vol.Optional("product"): cv.string,
            vol.Optional("products"): vol.All(cv.ensure_list, [_MIX_ITEM], vol.Length(min=1)),
            vol.Optional("rate"): vol.Coerce(float),
            vol.Optional("rate_unit"): vol.In(RATE_UNITS),
            vol.Optional("area"): vol.Coerce(float),
            vol.Optional("notes"): cv.string,
            **_WHEN,
        }
    ),
    _one_product_or_mix,
)
MIX_ADD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): _DEVICES,
        vol.Optional("product"): cv.string,
        vol.Optional("rate"): vol.Coerce(float),
        vol.Optional("rate_unit"): vol.In(RATE_UNITS),
    }
)
MIX_REMOVE_SCHEMA = vol.Schema(
    {vol.Required(ATTR_DEVICE_ID): _DEVICES, vol.Required("product"): cv.string}
)
MIX_CLEAR_SCHEMA = vol.Schema({vol.Required(ATTR_DEVICE_ID): _DEVICES})
LOG_WATERING_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): _DEVICES,
        vol.Required("minutes"): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=1440)),
        vol.Optional("zone"): cv.string,
        vol.Optional("notes"): cv.string,
        **_WHEN,
    }
)
LOG_PGR_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): _DEVICES,
        vol.Optional("product"): cv.string,
        vol.Optional("rate"): vol.Coerce(float),
        vol.Optional("notes"): cv.string,
        **_WHEN,
    }
)
LOG_MOW_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): _DEVICES,
        vol.Optional("mower_type"): vol.In(MOWER_TYPES),
        vol.Optional("height"): vol.Coerce(float),
        vol.Optional("height_unit"): vol.In([HEIGHT_UNIT_MM, HEIGHT_UNIT_IN]),
        vol.Optional("clippings"): vol.Coerce(float),
        vol.Optional("notes"): cv.string,
        **_WHEN,
    }
)
LOG_ACTIVITY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): _DEVICES,
        vol.Required("activity"): vol.In(ACTIVITY_TYPES),
        vol.Optional("details"): cv.string,
        vol.Optional("notes"): cv.string,
        **_WHEN,
    }
)
UPDATE_ENTRY_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Optional("notes"): cv.string,
        vol.Optional("rate"): vol.Coerce(float),
        vol.Optional("rate_unit"): vol.In(RATE_UNITS),
        vol.Optional("area"): vol.Coerce(float),
        vol.Optional("mower_type"): vol.In(MOWER_TYPES),
        vol.Optional("height"): vol.Coerce(float),
        vol.Optional("height_unit"): vol.In([HEIGHT_UNIT_MM, HEIGHT_UNIT_IN]),
        vol.Optional("clippings"): vol.Coerce(float),
        vol.Optional("details"): cv.string,
        **_WHEN,
    }
)
DELETE_ENTRY_SCHEMA = vol.Schema({vol.Required("entry_id"): cv.string})
SET_TEMPERATURE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required("date"): cv.date,
        vol.Optional("mean"): vol.Coerce(float),
        vol.Optional("min"): vol.Coerce(float),
        vol.Optional("max"): vol.Coerce(float),
    }
)
RECALCULATE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional("start_date"): cv.date,
        vol.Optional("end_date"): cv.date,
    }
)
GET_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): _DEVICES,
        vol.Optional("kind"): vol.All(cv.ensure_list, [vol.In(ENTRY_KINDS)]),
        vol.Optional("start_date"): cv.date,
        vol.Optional("end_date"): cv.date,
        vol.Optional("include_gdd", default=False): cv.boolean,
    }
)
EXPORT_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})


def _loaded_coordinators(hass: HomeAssistant) -> list[TurfCoordinator]:
    return [
        entry.runtime_data.coordinator
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


def _site(hass: HomeAssistant, entry_id: str | None) -> TurfCoordinator:
    coordinators = _loaded_coordinators(hass)
    if entry_id:
        for coordinator in coordinators:
            if coordinator.config_entry.entry_id == entry_id:
                return coordinator
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="site_not_found")
    if len(coordinators) == 1:
        return coordinators[0]
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="site_required")


def _lawns(hass: HomeAssistant, device_ids: list[str]) -> list[tuple[TurfCoordinator, str]]:
    """Resolve lawn device ids to (coordinator, lawn subentry id)."""
    registry = dr.async_get(hass)
    coordinators = _loaded_coordinators(hass)
    result: list[tuple[TurfCoordinator, str]] = []
    for device_id in device_ids:
        device = registry.async_get(device_id)
        lawn_id = next(
            (ident for domain, ident in (device.identifiers if device else ()) if domain == DOMAIN),
            None,
        )
        match = next(
            (
                c
                for c in coordinators
                if lawn_id in c.config_entry.subentries
                and c.config_entry.subentries[lawn_id].subentry_type == SUBENTRY_LAWN
            ),
            None,
        )
        if lawn_id is None or match is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_a_lawn",
                translation_placeholders={"device_id": device_id},
            )
        result.append((match, lawn_id))
    return result


def _entry_owner(hass: HomeAssistant, entry_id: str) -> TurfCoordinator:
    for coordinator in _loaded_coordinators(hass):
        if coordinator.has_entry(entry_id):
            return coordinator
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="entry_not_found",
        translation_placeholders={"entry_id": entry_id},
    )


def _product(coordinator: TurfCoordinator, name_or_id: str) -> Product:
    """A product from the library by name or id, or a helpful error."""
    product = coordinator.find_product(name_or_id)
    if product is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="product_not_found",
            translation_placeholders={
                "product": name_or_id,
                "available": ", ".join(p.name for p in coordinator.products().values()) or "-",
            },
        )
    return product


def _when(data: dict[str, Any]) -> Any:
    return data.get("datetime") or data.get("date")


def _height_mm(coordinator: TurfCoordinator, data: dict[str, Any]) -> float | None:
    if data.get("height") is None:
        return None
    return unit_to_mm(data["height"], data.get("height_unit") or coordinator.height_unit)


def _result(entries: list[dict[str, Any]]) -> ServiceResponse:
    return {"entries": [{"id": e["id"], "lawn_id": e["lawn_id"], "date": e["date"]} for e in entries]}


def async_setup_services(hass: HomeAssistant) -> None:
    """Register Turf Manager actions."""

    async def log_application(call: ServiceCall) -> ServiceResponse:
        entries = []
        if "products" in call.data:
            wanted = call.data["products"]
        else:
            wanted = [
                {"product": call.data["product"], "rate": call.data.get("rate"),
                 "rate_unit": call.data.get("rate_unit")}
            ]
        for coordinator, lawn_id in _lawns(hass, call.data[ATTR_DEVICE_ID]):
            items = [
                (_product(coordinator, item["product"]), item.get("rate"), item.get("rate_unit"))
                for item in wanted
            ]
            entries.append(
                await coordinator.async_log_mix(
                    lawn_id,
                    items,
                    when=_when(call.data),
                    area_m2=call.data.get("area"),
                    notes=call.data.get("notes"),
                )
            )
        return _result(entries)

    async def mix_add(call: ServiceCall) -> None:
        for coordinator, lawn_id in _lawns(hass, call.data[ATTR_DEVICE_ID]):
            staged = coordinator.staged.get(lawn_id, {})
            if name := call.data.get("product"):
                product = _product(coordinator, name)
                rate = call.data.get("rate")
            else:
                # Default to what's selected on the dashboard.
                product = coordinator.products().get(staged.get("product_id") or "")
                if product is None:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN, translation_key="no_product_selected"
                    )
                rate = call.data.get("rate", staged.get("rate"))
            coordinator.async_mix_add(lawn_id, product, rate, call.data.get("rate_unit"))

    async def mix_remove(call: ServiceCall) -> None:
        for coordinator, lawn_id in _lawns(hass, call.data[ATTR_DEVICE_ID]):
            coordinator.async_mix_remove(lawn_id, _product(coordinator, call.data["product"]))

    async def log_watering(call: ServiceCall) -> ServiceResponse:
        entries = []
        for coordinator, lawn_id in _lawns(hass, call.data[ATTR_DEVICE_ID]):
            zone = None
            if name := call.data.get("zone"):
                zone = coordinator.find_zone(name)
                if zone is None:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="zone_not_found",
                        translation_placeholders={
                            "zone": name,
                            "available": ", ".join(z.name for z in coordinator.zones().values()) or "-",
                        },
                    )
            entries.append(
                await coordinator.async_log_watering(
                    lawn_id,
                    minutes=call.data["minutes"],
                    when=_when(call.data),
                    zone=zone,
                    notes=call.data.get("notes"),
                )
            )
        return _result(entries)

    async def mix_clear(call: ServiceCall) -> None:
        for coordinator, lawn_id in _lawns(hass, call.data[ATTR_DEVICE_ID]):
            coordinator.async_mix_clear(lawn_id)

    async def log_pgr_application(call: ServiceCall) -> ServiceResponse:
        entries = []
        for coordinator, lawn_id in _lawns(hass, call.data[ATTR_DEVICE_ID]):
            product = None
            if name := call.data.get("product"):
                product = coordinator.find_product(name)
                if product is None:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="product_not_found",
                        translation_placeholders={
                            "product": name,
                            "available": ", ".join(
                                p.name for p in coordinator.products().values() if p.is_pgr
                            )
                            or "-",
                        },
                    )
            entries.append(
                await coordinator.async_log_pgr(
                    lawn_id,
                    when=_when(call.data),
                    product=product,
                    rate=call.data.get("rate"),
                    notes=call.data.get("notes"),
                )
            )
        return _result(entries)

    async def log_mow(call: ServiceCall) -> ServiceResponse:
        entries = []
        for coordinator, lawn_id in _lawns(hass, call.data[ATTR_DEVICE_ID]):
            entries.append(
                await coordinator.async_log_mow(
                    lawn_id,
                    mower_type=call.data.get("mower_type"),
                    height_mm=_height_mm(coordinator, call.data),
                    when=_when(call.data),
                    clippings_l=call.data.get("clippings"),
                    notes=call.data.get("notes"),
                )
            )
        return _result(entries)

    async def log_activity(call: ServiceCall) -> ServiceResponse:
        entries = []
        for coordinator, lawn_id in _lawns(hass, call.data[ATTR_DEVICE_ID]):
            entries.append(
                await coordinator.async_log_activity(
                    lawn_id,
                    activity=call.data["activity"],
                    when=_when(call.data),
                    details=call.data.get("details"),
                    notes=call.data.get("notes"),
                )
            )
        return _result(entries)

    async def update_entry(call: ServiceCall) -> ServiceResponse:
        coordinator = _entry_owner(hass, call.data["entry_id"])
        changes: dict[str, Any] = {
            "when": _when(call.data),
            "notes": call.data.get("notes"),
            "rate": call.data.get("rate"),
            "rate_unit": call.data.get("rate_unit"),
            "area_m2": call.data.get("area"),
            "mower_type": call.data.get("mower_type"),
            "height_mm": _height_mm(coordinator, call.data),
            "clippings_l": call.data.get("clippings"),
            "details": call.data.get("details"),
        }
        entry = await coordinator.async_update_entry(call.data["entry_id"], changes)
        return _result([entry])

    async def delete_entry(call: ServiceCall) -> None:
        coordinator = _entry_owner(hass, call.data["entry_id"])
        await coordinator.async_delete_entry(call.data["entry_id"])

    async def set_daily_temperature(call: ServiceCall) -> None:
        coordinator = _site(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        await coordinator.async_set_manual_day(
            call.data["date"], call.data.get("mean"), call.data.get("min"), call.data.get("max")
        )

    async def recalculate(call: ServiceCall) -> ServiceResponse:
        coordinator = _site(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        today = dt_util.now().date()
        end = call.data.get("end_date") or today - timedelta(days=1)
        start = call.data.get("start_date") or end - timedelta(days=30)
        cleared = await coordinator.async_recalculate_days(start, end)
        return {"days_refetched": cleared}

    async def get_history(call: ServiceCall) -> ServiceResponse:
        start: date | None = call.data.get("start_date")
        end: date | None = call.data.get("end_date")
        kinds = call.data.get("kind")
        if device_ids := call.data.get(ATTR_DEVICE_ID):
            targets: dict[TurfCoordinator, list[str]] = {}
            for coordinator, lawn_id in _lawns(hass, device_ids):
                targets.setdefault(coordinator, []).append(lawn_id)
        else:
            targets = {c: [] for c in _loaded_coordinators(hass)}

        entries: list[dict[str, Any]] = []
        gdd: dict[str, list[dict[str, Any]]] = {}
        today = dt_util.now().date()
        for coordinator, lawn_ids in targets.items():
            for entry in coordinator.history(lawn_ids or None, kinds, start, end):
                entries.append({**entry, "summary": entry_summary(entry, coordinator.height_unit)})
            if call.data["include_gdd"]:
                for lawn_id in lawn_ids or list(coordinator.lawns()):
                    gdd[coordinator.get_lawn(lawn_id).name] = coordinator.daily_gdd_rows(
                        lawn_id, start or today - timedelta(days=30), end or today - timedelta(days=1)
                    )
        response: dict[str, Any] = {"entries": entries}
        if call.data["include_gdd"]:
            response["gdd"] = gdd
        return response

    async def export_csv(call: ServiceCall) -> ServiceResponse:
        coordinator = _site(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        stamp = dt_util.now().strftime("%Y%m%d_%H%M")
        folder = Path(hass.config.path(DOMAIN))
        log_path = folder / f"log_{stamp}.csv"
        temps_path = folder / f"temperatures_{stamp}.csv"
        rows = [
            {**e, "summary": entry_summary(e, coordinator.height_unit)}
            for e in coordinator.history(None, None, None, None)
        ]
        temps = [{"date": k, **v} for k, v in sorted(coordinator.store.temps.items())]
        await hass.async_add_executor_job(_write_csvs, folder, log_path, rows, temps_path, temps)
        return {"log": str(log_path), "temperatures": str(temps_path)}

    def register(name: str, handler, schema: vol.Schema, response: SupportsResponse) -> None:
        hass.services.async_register(DOMAIN, name, handler, schema=schema, supports_response=response)

    register("log_application", log_application, LOG_APPLICATION_SCHEMA, SupportsResponse.OPTIONAL)
    register("log_pgr_application", log_pgr_application, LOG_PGR_SCHEMA, SupportsResponse.OPTIONAL)
    register("log_mow", log_mow, LOG_MOW_SCHEMA, SupportsResponse.OPTIONAL)
    register("log_activity", log_activity, LOG_ACTIVITY_SCHEMA, SupportsResponse.OPTIONAL)
    register("update_entry", update_entry, UPDATE_ENTRY_SCHEMA, SupportsResponse.OPTIONAL)
    register("delete_entry", delete_entry, DELETE_ENTRY_SCHEMA, SupportsResponse.NONE)
    register("set_daily_temperature", set_daily_temperature, SET_TEMPERATURE_SCHEMA, SupportsResponse.NONE)
    register("recalculate", recalculate, RECALCULATE_SCHEMA, SupportsResponse.OPTIONAL)
    register("get_history", get_history, GET_HISTORY_SCHEMA, SupportsResponse.ONLY)
    register("export_csv", export_csv, EXPORT_SCHEMA, SupportsResponse.OPTIONAL)
    register("mix_add", mix_add, MIX_ADD_SCHEMA, SupportsResponse.NONE)
    register("mix_remove", mix_remove, MIX_REMOVE_SCHEMA, SupportsResponse.NONE)
    register("mix_clear", mix_clear, MIX_CLEAR_SCHEMA, SupportsResponse.NONE)
    register("log_watering", log_watering, LOG_WATERING_SCHEMA, SupportsResponse.OPTIONAL)


_LOG_COLUMNS = [
    "date", "start", "all_day", "lawn", "kind", "summary", "product_name", "product_type",
    "active_ingredient", "is_pgr", "rate", "rate_unit", "area_m2", "total_amount", "total_unit",
    "n_g_m2", "p_g_m2", "k_g_m2", "moa_group", "mower_type", "height_mm", "clippings_l",
    "activity", "details", "zone_name", "duration_min", "source", "notes", "weather", "id",
]
_TEMP_COLUMNS = ["date", "mean", "min", "max", "hours", "source", "final"]


def _write_csvs(
    folder: Path,
    log_path: Path,
    rows: list[dict[str, Any]],
    temps_path: Path,
    temps: list[dict[str, Any]],
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_LOG_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    with temps_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_TEMP_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(temps)
