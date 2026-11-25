"""Calendar: the lawn care log plus the projected next PGR application."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TurfConfigEntry
from .const import DOMAIN, KIND_ACTIVITY, SUBENTRY_LAWN
from .coordinator import TurfCoordinator
from .entity import TurfLawnEntity
from .models import entry_date, entry_description, entry_start, entry_summary

PROJECTED_UID = "projected_pgr_due"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TurfConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type == SUBENTRY_LAWN:
            async_add_entities(
                [LawnCalendar(coordinator, subentry_id)], config_subentry_id=subentry_id
            )


class LawnCalendar(TurfLawnEntity, CalendarEntity):
    """Every logged entry for a lawn, and the projected PGR due date."""

    _attr_supported_features = CalendarEntityFeature.DELETE_EVENT

    def __init__(self, coordinator: TurfCoordinator, lawn_id: str) -> None:
        super().__init__(coordinator, lawn_id, "lawn_calendar")
        # Calendar entities take the device name, so the entity id is calendar.<lawn>.
        self._attr_name = None

    def _event_for(self, entry: dict[str, Any]) -> CalendarEvent:
        summary = entry_summary(entry, self.coordinator.height_unit)
        description = entry_description(entry)
        if entry.get("all_day"):
            day = entry_date(entry)
            return CalendarEvent(
                start=day,
                end=day + timedelta(days=1),
                summary=summary,
                description=description,
                uid=entry["id"],
            )
        start = entry_start(entry)
        length = timedelta(hours=1) if entry["kind"] == KIND_ACTIVITY else timedelta(minutes=30)
        return CalendarEvent(
            start=start, end=start + length, summary=summary, description=description, uid=entry["id"]
        )

    def _projected_event(self) -> CalendarEvent | None:
        state = self.lawn_state
        if state is None or state.projected_due is None or state.gdd_total is None:
            return None
        if state.due:
            summary = f"PGR due now ({state.gdd_total:.0f}/{state.target:.0f} GDD)"
        else:
            summary = f"PGR due ({state.target:.0f} GDD, {state.projection_method})"
        product = state.pgr_product.name if state.pgr_product else "PGR"
        return CalendarEvent(
            start=state.projected_due,
            end=state.projected_due + timedelta(days=1),
            summary=summary,
            description=(
                f"{product}: {state.gdd_total:.0f} of {state.target:.0f} GDD accumulated "
                f"since {state.last_pgr['date'] if state.last_pgr else '-'}."
            ),
            uid=PROJECTED_UID,
        )

    def _all_events(self) -> list[CalendarEvent]:
        events = [self._event_for(e) for e in self.coordinator.store.entries_for(self._lawn_id)]
        if projected := self._projected_event():
            events.append(projected)
        return events

    @property
    def event(self) -> CalendarEvent | None:
        """The current event, else the next upcoming one."""
        now = dt_util.now()
        upcoming = [e for e in self._all_events() if _as_dt(e.end) > now]
        return min(upcoming, key=lambda e: _as_dt(e.start), default=None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [
            e
            for e in self._all_events()
            if _as_dt(e.start) < end_date and _as_dt(e.end) > start_date
        ]

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        if uid == PROJECTED_UID:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="cannot_delete_projection"
            )
        await self.coordinator.async_delete_entry(uid)


def _as_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return dt_util.start_of_local_day(value)
