"""Buttons: one-tap logging from the dashboard."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TurfConfigEntry
from .const import CONF_RATE, DOMAIN, SUBENTRY_LAWN
from .coordinator import TurfCoordinator
from .entity import TurfLawnEntity
from .models import Product


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
                LogButton(coordinator, subentry_id, "log_pgr_today"),
                LogButton(coordinator, subentry_id, "log_mow"),
                LogButton(coordinator, subentry_id, "log_application"),
                LogButton(coordinator, subentry_id, "save_default_rate"),
                LogButton(coordinator, subentry_id, "add_to_mix"),
                LogButton(coordinator, subentry_id, "clear_mix"),
                LogButton(coordinator, subentry_id, "log_activity"),
            ],
            config_subentry_id=subentry_id,
        )


class LogButton(TurfLawnEntity, ButtonEntity):
    """Logs an entry now using the lawn's staged values."""

    def __init__(self, coordinator: TurfCoordinator, lawn_id: str, key: str) -> None:
        super().__init__(coordinator, lawn_id, key)
        self._key = key

    async def async_press(self) -> None:
        coordinator = self.coordinator
        staged = self.staged
        if self._key == "log_pgr_today":
            await coordinator.async_log_pgr(self._lawn_id)
        elif self._key == "log_mow":
            await coordinator.async_log_mow(
                self._lawn_id,
                mower_type=staged.get("mower_type"),
                height_mm=staged.get("height_mm"),
                when=coordinator.log_when(self._lawn_id),
            )
        elif self._key == "log_application":
            # A mix being built is logged as one application; otherwise the selected product.
            if mix := coordinator.mix_products(self._lawn_id):
                await coordinator.async_log_mix(
                    self._lawn_id, mix, when=coordinator.log_when(self._lawn_id)
                )
                coordinator.async_mix_clear(self._lawn_id)
                return
            await coordinator.async_log_application(
                self._lawn_id,
                self._selected_product(),
                rate=staged.get("rate"),
                when=coordinator.log_when(self._lawn_id),
            )
        elif self._key == "add_to_mix":
            coordinator.async_mix_add(
                self._lawn_id, self._selected_product(), staged.get("rate"), None
            )
        elif self._key == "clear_mix":
            coordinator.async_mix_clear(self._lawn_id)
        elif self._key == "save_default_rate":
            product = self._selected_product()
            rate = staged.get("rate")
            if rate is None:
                raise HomeAssistantError(translation_domain=DOMAIN, translation_key="no_rate")
            # Products are config subentries; their default rate lives there.
            entry = coordinator.config_entry
            subentry = entry.subentries[product.id]
            self.hass.config_entries.async_update_subentry(
                entry, subentry, data={**subentry.data, CONF_RATE: rate}
            )
        elif self._key == "log_activity":
            await coordinator.async_log_activity(
                self._lawn_id,
                activity=staged.get("activity") or "other",
                when=coordinator.log_when(self._lawn_id),
            )

    def _selected_product(self) -> Product:
        product = self.coordinator.products().get(self.staged.get("product_id") or "")
        if product is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_product_selected"
            )
        return product
