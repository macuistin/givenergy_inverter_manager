"""
controller_conflict.py: is something other than this integration changing the charge target?

Only this integration should set the charge target. GivTCP's SmartTarget, Predbat, an EMS plant
or the GivEnergy app can set it too, and two controllers fighting over one register leave the
battery on whichever wrote last.

The signal is the write log (core/write_log.py). Its entries for the charge target entity
include the changes the manager did not send, with the Home Assistant user that made them when
one is known. A change with a user is someone using Home Assistant on purpose, so it is not
counted. The manager's own write coming back as a state change is already left out of the log.

Two such changes inside three days raise the suspicion, and it clears after three days with
none. What changed the target is not known: a change made in the GivEnergy app also arrives
with no Home Assistant user, so the wording says "something else" and never names a product.

This only reads the log. It never reverts a change and never raises a repair.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..const import CONFLICT_MIN_CHANGES, CONFLICT_WINDOW_DAYS
from .write_log import EXTERNAL_REASON

STATE_NONE = "none"
STATE_SUSPECTED = "suspected"


@dataclass(frozen=True)
class ConflictStatus:
    """The suspicion, how many changes it rests on, and the newest of them."""

    state: str = STATE_NONE
    count: int = 0
    last_seen_iso: str | None = None
    entity_id: str | None = None


def detect_conflict(
    entries: Iterable[Mapping[str, Any]], entity_id: str | None, now: datetime
) -> ConflictStatus:
    """The conflict status from the write log entries, for the charge target *entity_id*."""
    if not entity_id:
        return ConflictStatus()
    since = now - timedelta(days=CONFLICT_WINDOW_DAYS)
    seen = sorted(
        (at, entry["time"])
        for entry in entries
        if _counts(entry, entity_id)
        if (at := _parse(entry["time"])) is not None and since < at <= now
    )
    if not seen:
        return ConflictStatus(entity_id=entity_id)
    state = STATE_SUSPECTED if len(seen) >= CONFLICT_MIN_CHANGES else STATE_NONE
    return ConflictStatus(state, len(seen), seen[-1][1], entity_id)


def _counts(entry: Mapping[str, Any], entity_id: str) -> bool:
    """An outside change to this entity that no Home Assistant user made."""
    return (
        entry.get("entity_id") == entity_id
        and entry.get("reason") == EXTERNAL_REASON
        and not entry.get("user_id")
    )


def _parse(stamp: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
