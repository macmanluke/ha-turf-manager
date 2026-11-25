"""Base entities for Turf Manager."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, GRASS_COOL, GRASS_WARM
from .coordinator import TurfCoordinator
from .models import Lawn, LawnState

_GRASS_MODEL = {GRASS_COOL: "Cool-season lawn", GRASS_WARM: "Warm-season lawn"}


class TurfLawnEntity(CoordinatorEntity[TurfCoordinator]):
    """An entity belonging to one lawn (one device per lawn subentry)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TurfCoordinator, lawn_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._lawn_id = lawn_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{lawn_id}_{key}"
        lawn = coordinator.get_lawn(lawn_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, lawn_id)},
            name=lawn.name,
            manufacturer="Turf Manager",
            model=_GRASS_MODEL.get(lawn.grass_type, "Lawn"),
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def lawn(self) -> Lawn:
        return self.coordinator.get_lawn(self._lawn_id)

    @property
    def lawn_state(self) -> LawnState | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.lawns.get(self._lawn_id)

    @property
    def staged(self) -> dict:
        return self.coordinator.staged.setdefault(self._lawn_id, {})

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._lawn_id in self.coordinator.config_entry.subentries
            and self.lawn_state is not None
        )

