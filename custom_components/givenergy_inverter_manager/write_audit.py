"""
write_audit.py: who changed the charge target and the charge window.

The manager reports each write it sends, and watches the entities it manages for
changes it did not send. Both go into one bounded log that is saved with the
accumulation store and shown as an attribute of the register write count sensor.

The audit never reverts a change and never raises a repair. It only records.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import GIVTCP_MIN_WRITE_INTERVAL_S, REGISTER_WRITE_LOG_MAX_ENTRIES
from .core.write_log import (
    EXTERNAL_REASON,
    ManagerWriteMemory,
    WriteLogEntry,
    WriteRecord,
    append_bounded,
    is_real_value_change,
)
from .logging import get_logger

if TYPE_CHECKING:
    from homeassistant.core import EventStateChangedData

    from .accumulation import AccumulationStore

_LOG = get_logger(__name__)


class WriteAudit:
    """Keeps the write log and tells the manager's own writes from outside changes."""

    def __init__(self, acc: AccumulationStore, now: Callable[[], datetime]) -> None:
        self._acc = acc
        self._now = now
        self._memory = ManagerWriteMemory(GIVTCP_MIN_WRITE_INTERVAL_S)

    def before_write(self, record: WriteRecord) -> None:
        """Remember the value before the call, since the entity can report it back at once."""
        self._memory.remember(record.entity_id, record.value, time.monotonic())

    def write_failed(self, record: WriteRecord) -> None:
        """Forget the value, because nothing was written."""
        self._memory.forget(record.entity_id)

    def after_write(self, record: WriteRecord) -> None:
        """Log a write the manager sent."""
        self._append(
            WriteLogEntry(self._now().isoformat(), record.entity_id, record.value, record.reason)
        )

    def watch(self, hass: HomeAssistant, entity_ids: Iterable[str]) -> Callable[[], None]:
        """Listen for outside changes to these entities. Returns the function that stops it."""
        return async_track_state_change_event(hass, list(entity_ids), self._on_state_change)

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if old is None or new is None or not is_real_value_change(old.state, new.state):
            return
        entity_id = event.data["entity_id"]
        if self._memory.is_echo(entity_id, new.state, time.monotonic()):
            return
        context = new.context
        _LOG.info(
            "%s changed from %s to %s outside the manager (user_id=%s, parent_id=%s)",
            entity_id,
            old.state,
            new.state,
            context.user_id,
            context.parent_id,
        )
        self._append(
            WriteLogEntry(
                self._now().isoformat(),
                entity_id,
                new.state,
                EXTERNAL_REASON,
                user_id=context.user_id,
                parent_id=context.parent_id,
            )
        )

    def _append(self, entry: WriteLogEntry) -> None:
        state = self._acc.state
        state.register_write_log = append_bounded(
            state.register_write_log, entry, REGISTER_WRITE_LOG_MAX_ENTRIES
        )
        self._acc.schedule_save()
