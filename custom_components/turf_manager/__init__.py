"""Turf Manager: GDD-based PGR tracking and a lawn care log for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_GRASS_TYPE,
    DOMAIN,
    LOGGER,
    PLATFORMS,
    SUBENTRY_LAWN,
    SUBENTRY_ZONE,
)
from .coordinator import TurfCoordinator, site_config
from .services import async_setup_services
from .store import TurfStore

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

FRONTEND_JS = Path(__file__).parent / "frontend" / "turf-manager.js"
FRONTEND_URL = f"/{DOMAIN}_static/turf-manager.js"


@dataclass
class TurfRuntimeData:
    """Runtime objects for a site."""

    coordinator: TurfCoordinator
    store: TurfStore
    signature: tuple[Any, ...]


type TurfConfigEntry = ConfigEntry[TurfRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions and dashboard."""
    async_setup_services(hass)
    await _async_register_dashboard(hass)
    return True


async def _async_register_dashboard(hass: HomeAssistant) -> None:
    """Serve the frontend script (dashboard strategy and history card) on every page.

    The dashboard then appears under Settings > Dashboards > Add dashboard as
    "Turf Manager", and the history card in the card picker.
    """
    if hass.http is None or "frontend" not in hass.config.components:
        return
    # Imported here so the integration still loads where the frontend isn't installed.
    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    try:
        version = await hass.async_add_executor_job(lambda: int(FRONTEND_JS.stat().st_mtime))
        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL, str(FRONTEND_JS), cache_headers=False)]
        )
    except (OSError, RuntimeError) as err:
        LOGGER.warning("Could not register the Turf Manager dashboard: %s", err)
        return
    add_extra_js_url(hass, f"{FRONTEND_URL}?v={version}")


async def async_setup_entry(hass: HomeAssistant, entry: TurfConfigEntry) -> bool:
    """Set up a site from a config entry."""
    store = TurfStore(hass, entry.entry_id)
    await store.async_load()
    coordinator = TurfCoordinator(hass, entry, store)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = TurfRuntimeData(coordinator, store, _signature(entry))
    coordinator.async_start()
    _async_remove_site_device(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TurfConfigEntry) -> bool:
    """Unload a site."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.store.async_save()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: TurfConfigEntry) -> None:
    """Delete stored data when a site is removed."""
    await TurfStore(hass, entry.entry_id).async_remove()


@callback
def _async_remove_site_device(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the site device used by early versions.

    Its temperature sensors now live on each lawn, so nothing is listed under
    "Devices that don't belong to a sub-entry".
    """
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if (DOMAIN, entry.entry_id) in device.identifiers:
            registry.async_remove_device(device.id)

    # The "water" activity was replaced by irrigation logging; drop its sensor.
    entities = er.async_get(hass)
    for sid, sub in entry.subentries.items():
        if sub.subentry_type == SUBENTRY_LAWN and (
            entity_id := entities.async_get_entity_id("sensor", DOMAIN, f"{sid}_last_water")
        ):
            entities.async_remove(entity_id)


def _signature(entry: ConfigEntry) -> tuple[Any, ...]:
    """Settings that need a reload (entities/devices change) when edited."""
    lawns = tuple(
        sorted(
            (sid, sub.title, sub.data.get(CONF_GRASS_TYPE))
            for sid, sub in entry.subentries.items()
            if sub.subentry_type == SUBENTRY_LAWN
        )
    )
    zones = tuple(
        sorted(
            (sid, sub.title, tuple(sorted(sub.data.items())))
            for sid, sub in entry.subentries.items()
            if sub.subentry_type == SUBENTRY_ZONE
        )
    )
    return (tuple(sorted(site_config(entry).items())), lawns, zones)


async def _async_update_listener(hass: HomeAssistant, entry: TurfConfigEntry) -> None:
    """Reload for structural changes; otherwise just recalculate."""
    if _signature(entry) != entry.runtime_data.signature:
        await hass.config_entries.async_reload(entry.entry_id)
    else:
        entry.runtime_data.coordinator.async_recompute()
