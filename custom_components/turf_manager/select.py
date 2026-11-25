"""Select entities: PGR product choice and staged values for dashboard logging."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import TurfConfigEntry
from .const import (
    ACTIVITY_TYPES,
    CONF_GDD_TARGET,
    CONF_PGR_PRODUCT,
    MOWER_TYPES,
    SUBENTRY_LAWN,
)
from .coordinator import TurfCoordinator
from .entity import TurfLawnEntity


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
                PgrProductSelect(coordinator, subentry_id),
                ProductSelect(coordinator, subentry_id),
                StagedOptionSelect(coordinator, subentry_id, "mower_type", MOWER_TYPES),
                StagedOptionSelect(coordinator, subentry_id, "activity", ACTIVITY_TYPES),
            ],
            config_subentry_id=subentry_id,
        )


class PgrProductSelect(TurfLawnEntity, SelectEntity):
    """The PGR product this lawn is on. Choosing one also sets its GDD interval."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: TurfCoordinator, lawn_id: str) -> None:
        super().__init__(coordinator, lawn_id, "pgr_product")

    @property
    def options(self) -> list[str]:
        return sorted(p.name for p in self.coordinator.products().values() if p.is_pgr)

    @property
    def current_option(self) -> str | None:
        product = self.coordinator.lawn_pgr_product(self.lawn)
        return product.name if product else None

    async def async_select_option(self, option: str) -> None:
        product = self.coordinator.find_product(option)
        if product is None:
            return
        entry = self.coordinator.config_entry
        subentry = entry.subentries[self._lawn_id]
        data = {**subentry.data, CONF_PGR_PRODUCT: product.id}
        if product.gdd_interval:
            data[CONF_GDD_TARGET] = product.gdd_interval
        self.hass.config_entries.async_update_subentry(entry, subentry, data=data)


class ProductSelect(TurfLawnEntity, SelectEntity, RestoreEntity):
    """Product staged for the 'Log application' button."""

    def __init__(self, coordinator: TurfCoordinator, lawn_id: str) -> None:
        super().__init__(coordinator, lawn_id, "product")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.staged.get("product_id"):
            return
        product = None
        if last := await self.async_get_last_state():
            product = self.coordinator.find_product(last.state)
        if product is None:
            product = next(iter(sorted(self.coordinator.products().values(), key=lambda p: p.name)), None)
        if product is not None:
            self.staged["product_id"] = product.id
            self.staged.setdefault("rate", product.rate)

    @property
    def options(self) -> list[str]:
        return sorted(p.name for p in self.coordinator.products().values())

    @property
    def current_option(self) -> str | None:
        product = self.coordinator.products().get(self.staged.get("product_id") or "")
        return product.name if product else None

    async def async_select_option(self, option: str) -> None:
        product = self.coordinator.find_product(option)
        if product is None:
            return
        self.staged["product_id"] = product.id
        if product.rate is not None:
            self.staged["rate"] = product.rate
        # The rate number shows the new product's unit and default rate.
        self.coordinator.async_update_listeners()


class StagedOptionSelect(TurfLawnEntity, SelectEntity, RestoreEntity):
    """A fixed list (mower type, activity) staged for a log button."""

    def __init__(
        self, coordinator: TurfCoordinator, lawn_id: str, key: str, options: list[str]
    ) -> None:
        super().__init__(coordinator, lawn_id, key)
        self._key = key
        self._attr_options = list(options)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._key in self.staged:
            return
        value = None
        if (last := await self.async_get_last_state()) and last.state in self.options:
            value = last.state
        elif self._key == "mower_type" and self.lawn_state and self.lawn_state.last_mow:
            value = self.lawn_state.last_mow.get("mower_type")
        self.staged[self._key] = value if value in self.options else self.options[0]

    @property
    def current_option(self) -> str | None:
        return self.staged.get(self._key)

    async def async_select_option(self, option: str) -> None:
        self.staged[self._key] = option
        self.async_write_ha_state()
