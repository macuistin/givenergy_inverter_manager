"""
write_log.py: a bounded log of changes to the inverter entities the manager owns.

Pure Python, no Home Assistant imports. Two kinds of entry share one log:

  - a write the manager made (reason says why, for example "charge target"),
  - a change the manager did not make (reason is EXTERNAL_REASON, with the Home
    Assistant user and parent context that caused it when they are known).

Entries are plain dicts so they save to storage and show as sensor attributes
without conversion. The log keeps the newest entries, oldest first.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

EXTERNAL_REASON = "external"
_UNKNOWN_STATES = frozenset({"unavailable", "unknown", ""})


@dataclass(frozen=True)
class WriteRecord:
    """One write the manager sent: which entity, what value, and why."""

    entity_id: str
    value: str
    reason: str


@dataclass(frozen=True)
class WriteLogEntry:
    """One log line. `user_id` and `parent_id` are set on external changes only."""

    time: str
    entity_id: str
    value: str
    reason: str
    user_id: str | None = None
    parent_id: str | None = None

    def as_dict(self) -> dict[str, str]:
        """The entry as a dict, leaving out the context fields that are empty."""
        return {k: v for k, v in asdict(self).items() if v is not None}


def append_bounded(entries: list[dict], entry: WriteLogEntry, limit: int) -> list[dict]:
    """Return the entries with the new one last, keeping only the newest `limit`."""
    return [*entries, entry.as_dict()][-limit:]


def restore_entries(stored: object, limit: int) -> list[dict]:
    """Rebuild the log from stored data. Anything that is not a log entry is dropped."""
    if not isinstance(stored, list):
        return []
    valid = [dict(e) for e in stored if _is_entry(e)]
    return valid[-limit:]


def _is_entry(candidate: object) -> bool:
    return isinstance(candidate, dict) and all(
        isinstance(candidate.get(key), str) for key in ("time", "entity_id", "value", "reason")
    )


def newest_first(entries: list[dict]) -> list[dict]:
    """The entries as the sensor attribute shows them, most recent first."""
    return [dict(e) for e in reversed(entries)]


def is_real_value_change(old_state: str | None, new_state: str | None) -> bool:
    """True when an entity moved from one real value to another.

    A change from or to unavailable or unknown is a connection event, not an edit.
    """
    if old_state in _UNKNOWN_STATES or new_state in _UNKNOWN_STATES:
        return False
    return old_state is not None and new_state is not None and not same_value(old_state, new_state)


def same_value(left: object, right: object) -> bool:
    """Compare two values as numbers when both are numeric (55 equals "55.0"), else as text."""
    try:
        return float(left) == float(right)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(left) == str(right)


class ManagerWriteMemory:
    """Remembers what the manager last wrote to each entity, to tell its echo from an edit.

    The entity reports a written value back as a state change. That change is the
    manager's own when the value matches the last write and arrives within the window.
    A match is used up once, so the same value set again later by someone else counts
    as external.
    """

    def __init__(self, window_s: float) -> None:
        self._window_s = window_s
        self._last: dict[str, tuple[str, float]] = {}

    def remember(self, entity_id: str, value: str, at_s: float) -> None:
        """Note that the manager wrote this value to the entity at this time."""
        self._last[entity_id] = (value, at_s)

    def forget(self, entity_id: str) -> None:
        """Drop what was remembered for the entity, for a write that never happened."""
        self._last.pop(entity_id, None)

    def is_echo(self, entity_id: str, value: str, at_s: float) -> bool:
        """True, and forgets the write, when this change is the manager's own write."""
        written = self._last.get(entity_id)
        if written is None:
            return False
        written_value, written_at = written
        if not same_value(written_value, value) or at_s - written_at > self._window_s:
            return False
        del self._last[entity_id]
        return True
