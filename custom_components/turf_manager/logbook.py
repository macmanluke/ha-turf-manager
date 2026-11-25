"""Describe Turf Manager events for the logbook."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_ENTRY_LOGGED, EVENT_PGR_DUE


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, Any]]], None],
) -> None:
    """Describe logbook events."""

    @callback
    def describe_logged(event: Event) -> dict[str, Any]:
        return {"name": event.data.get("lawn", "Lawn"), "message": f"logged {event.data.get('summary')}"}

    @callback
    def describe_due(event: Event) -> dict[str, Any]:
        return {
            "name": event.data.get("lawn", "Lawn"),
            "message": f"PGR due ({event.data.get('gdd', 0):.0f} of {event.data.get('target', 0):.0f} GDD)",
        }

    async_describe_event(DOMAIN, EVENT_ENTRY_LOGGED, describe_logged)
    async_describe_event(DOMAIN, EVENT_PGR_DUE, describe_due)
