"""Binary sensors for Turf Manager."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TurfConfigEntry
from .const import SUBENTRY_LAWN
from .coordinator import TurfCoordinator
from .entity import TurfLawnEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TurfConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type == SUBENTRY_LAWN:
            async_add_entities(
                [PgrDueBinarySensor(coordinator, subentry_id)], config_subentry_id=subentry_id
            )


class PgrDueBinarySensor(TurfLawnEntity, BinarySensorEntity):
    """On when cumulative GDD since the last PGR application reaches the target."""

    def __init__(self, coordinator: TurfCoordinator, lawn_id: str) -> None:
        super().__init__(coordinator, lawn_id, "pgr_due")

    @property
    def is_on(self) -> bool | None:
        state = self.lawn_state
        if state is None or state.gdd_total is None:
            return None
        return state.due

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        state = self.lawn_state
        if state is None or state.gdd_total is None:
            return None
        return {
            "gdd": state.gdd_total,
            "target": state.target,
            "overdue_gdd": round(max(0.0, state.gdd_total - state.target), 1),
            "projected_due": state.projected_due.isoformat() if state.projected_due else None,
        }
