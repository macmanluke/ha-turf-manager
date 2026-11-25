"""Diagnostics for Turf Manager."""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import TurfConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TurfConfigEntry
) -> dict[str, Any]:
    """Site config, recent ledger days and calculated state (no personal data stored)."""
    coordinator = entry.runtime_data.coordinator
    store = entry.runtime_data.store
    cutoff = (dt_util.now().date() - timedelta(days=30)).isoformat()
    lawns = {}
    if coordinator.data:
        for lawn_id, state in coordinator.data.lawns.items():
            lawn = asdict(state)
            lawn.pop("last_mow", None)
            lawn.pop("last_application", None)
            lawn.pop("last_activity", None)
            lawns[lawn_id] = lawn
    return {
        "site": {**entry.data, **entry.options},
        "subentries": {
            sid: {"type": sub.subentry_type, "title": sub.title, "data": dict(sub.data)}
            for sid, sub in entry.subentries.items()
        },
        "primary_has_statistics": coordinator.source.primary_has_statistics,
        "today": coordinator.data.today if coordinator.data else None,
        "ledger_last_30_days": {k: v for k, v in store.temps.items() if k >= cutoff},
        "ledger_days": len(store.temps),
        "log_entries": len(store.entries),
        "lawns": lawns,
    }
