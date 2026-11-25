"""Date entity: the last PGR application date, editable from the dashboard."""

from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TurfConfigEntry
from .const import SUBENTRY_LAWN
from .coordinator import TurfCoordinator
from .entity import TurfLawnEntity
from .models import entry_date


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TurfConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type == SUBENTRY_LAWN:
            async_add_entities(
                [LastPgrApplicationDate(coordinator, subentry_id), LogDate(coordinator, subentry_id)],
                config_subentry_id=subentry_id,
            )


class LastPgrApplicationDate(TurfLawnEntity, DateEntity):
    """Pick a later date to log a new application, or an earlier one to correct the last."""

    def __init__(self, coordinator: TurfCoordinator, lawn_id: str) -> None:
        super().__init__(coordinator, lawn_id, "last_pgr_application")

    @property
    def native_value(self) -> date | None:
        state = self.lawn_state
        return entry_date(state.last_pgr) if state and state.last_pgr else None

    async def async_set_value(self, value: date) -> None:
        await self.coordinator.async_set_last_pgr_date(self._lawn_id, value)


class LogDate(TurfLawnEntity, DateEntity):
    """The day the dashboard's Log buttons record: today, or an earlier day to catch up.

    A back-dated value lasts until midnight, then returns to today.
    """

    def __init__(self, coordinator: TurfCoordinator, lawn_id: str) -> None:
        super().__init__(coordinator, lawn_id, "log_date")

    @property
    def native_value(self) -> date:
        return self.coordinator.log_date(self._lawn_id)

    async def async_set_value(self, value: date) -> None:
        self.coordinator.async_set_log_date(self._lawn_id, value)
