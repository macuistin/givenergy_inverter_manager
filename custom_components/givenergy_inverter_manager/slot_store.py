"""slot_store.py: the half-hourly energy history, saved in its own Home Assistant store.

It has its own store, apart from the accumulators, because a year of slots is large and the
accumulators are written whole after every change. Here a write is queued only when a new
half hour starts, and Home Assistant also writes it at shutdown from whatever is in memory then.

The model is lib/tariff (SlotDay, SlotHistory). This module adds the storage and the rule that
nothing is written before the saved history has been read.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, datetime, tzinfo
from typing import TYPE_CHECKING, Any

from .lib.tariff.defaults import SLOT_SECONDS
from .lib.tariff.slot_history import SlotHistory
from .lib.tariff.slots import SlotEnergy, local_midnight
from .lib.timeutil import elapsed_seconds

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.storage import Store

_LOG = logging.getLogger(__name__)
_STORAGE_KEY = "givenergy_inverter_manager.energy_slots"
_STORAGE_VERSION = 1
_SAVE_DELAY_SECONDS = 15


def _create_store(hass: HomeAssistant) -> Store[dict[str, Any]]:
    from homeassistant.helpers.storage import Store  # lazy: not available in the unit tests

    return Store(hass, _STORAGE_VERSION, _STORAGE_KEY)


class SlotStore:
    """The slot history and its storage."""

    def __init__(self, hass: HomeAssistant, tz: tzinfo) -> None:
        self._store = _create_store(hass)
        self._tz = tz
        self.history = SlotHistory(tz)
        # Nothing is written until the saved history has been read. A save queued before then
        # would be handed back by the store as if it were on disk, and it would replace it.
        self._loaded = False
        self._saved_slot: tuple[object, int] | None = None

    async def async_load(self) -> None:
        """Read the saved history. Safe when there is none."""
        try:
            data = await self._store.async_load()
            if data is not None:
                self.history.restore(list(data.get("days", [])))
                if self.history.skipped:
                    _LOG.warning("Skipped %d unreadable energy days", self.history.skipped)
        except Exception as err:  # a store boundary: a bad file must not stop setup
            _LOG.warning("Could not restore the energy history: %s: starting fresh", err)
            self.history = SlotHistory(self._tz)
        finally:
            self._loaded = True

    def record(self, energy: SlotEnergy, start: datetime, end: datetime) -> None:
        """Book one cycle's energy. A write is queued when a new half hour has started."""
        if not self.history.record(energy, start, end):
            return
        if (slot := self._slot_of(end)) != self._saved_slot:
            self._saved_slot = slot
            self.schedule_save()

    def _slot_of(self, moment: datetime) -> tuple[object, int]:
        since_midnight = elapsed_seconds(local_midnight(moment.date(), self._tz), moment)
        return moment.date(), int(since_midnight // SLOT_SECONDS)

    def note_counters(self, day: date, readings: Mapping[str, float]) -> None:
        """Keep the inverter's day totals beside the slots, so a drift can be seen."""
        if readings:
            self.history.note_counters(day, readings)

    def record_soc(self, moment: datetime, percent: float) -> None:
        """Note the battery charge. A reading outside 0 to 100 is not a charge and is ignored."""
        if 0 <= percent <= 100:
            self.history.record_soc(moment, percent)

    def schedule_save(self) -> None:
        """Queue a save. Home Assistant writes it after a short delay, or at shutdown."""
        if self._loaded:
            self._store.async_delay_save(self._payload, _SAVE_DELAY_SECONDS)

    async def async_save(self) -> None:
        """Write the history now. Does nothing before the saved history has been read."""
        if not self._loaded:
            return
        try:
            await self._store.async_save(self._payload())
        except Exception as err:  # a store boundary
            _LOG.warning("Could not save the energy history: %s", err)

    def _payload(self) -> dict[str, Any]:
        return {"version": _STORAGE_VERSION, "days": list(self.history.to_storage())}
