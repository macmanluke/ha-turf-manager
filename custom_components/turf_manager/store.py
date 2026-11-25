"""Persistent storage: the daily temperature ledger and the lawn care log."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION
from .models import entry_start


class TurfStore:
    """Wraps a Home Assistant Store (.storage/turf_manager.<entry_id>)."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}", private=True
        )
        self.temps: dict[str, dict[str, Any]] = {}
        self.entries: list[dict[str, Any]] = []
        # Sprinkler zones currently running: zone id -> ISO start time.
        self.running: dict[str, str] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.temps = data.get("temps", {})
        self.entries = data.get("entries", [])
        self.running = data.get("running", {})

    def _data_to_save(self) -> dict[str, Any]:
        return {"temps": self.temps, "entries": self.entries, "running": self.running}

    def schedule_save(self) -> None:
        self._store.async_delay_save(self._data_to_save, 2)

    async def async_save(self) -> None:
        await self._store.async_save(self._data_to_save())

    async def async_remove(self) -> None:
        await self._store.async_remove()

    # --- Temperature ledger ------------------------------------------------

    def get_day(self, day: date) -> dict[str, Any] | None:
        return self.temps.get(day.isoformat())

    def set_day(self, day: date, record: dict[str, Any]) -> None:
        self.temps[day.isoformat()] = record

    def clear_days(self, start: date, end: date, keep: Callable[[dict], bool]) -> int:
        """Remove ledger days in [start, end] unless ``keep(record)``. Returns count."""
        removed = 0
        for key in list(self.temps):
            if start.isoformat() <= key <= end.isoformat() and not keep(self.temps[key]):
                del self.temps[key]
                removed += 1
        return removed

    def prune(self, before: date) -> None:
        cutoff = before.isoformat()
        for key in [k for k in self.temps if k < cutoff]:
            del self.temps[key]

    # --- Log entries -------------------------------------------------------

    def add_entry(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)
        self.entries.sort(key=entry_start)

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        return next((e for e in self.entries if e["id"] == entry_id), None)

    def replace_entry(self, entry: dict[str, Any]) -> None:
        self.entries = [entry if e["id"] == entry["id"] else e for e in self.entries]
        self.entries.sort(key=entry_start)

    def delete_entry(self, entry_id: str) -> dict[str, Any] | None:
        entry = self.get_entry(entry_id)
        if entry is not None:
            self.entries.remove(entry)
        return entry

    def entries_for(self, lawn_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        """Entries for a lawn (oldest first), optionally filtered by kind."""
        return [
            e
            for e in self.entries
            if e["lawn_id"] == lawn_id and (kind is None or e["kind"] == kind)
        ]
