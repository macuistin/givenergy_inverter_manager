"""
charge_retry.py: when to try the nightly charge write again, and whether a restart missed it.

The charge target and window are written once, one minute before the cheapest timed rate period
starts. If that write fails, because the inverter integration is not publishing or the inverter
did not take a setting, the night would be lost. The write is tried again at set offsets after
the trigger, and stops when too little of the window is left for a charge to matter.

A restart inside the window loses the pending retries. The write log says whether the manager
wrote the target since the trigger, so a restart can catch up without a stored field.

Nothing here reads the clock. Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from ..const import CHARGE_WRITE_RETRY_OFFSETS_MIN, CHARGE_WRITE_RETRY_STOP_BEFORE_END_MIN
from .write_log import is_manager_write, is_retry_note

_ONE_MINUTE = timedelta(minutes=1)
_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class WriteWindow:
    """One night's write: when it fires and when the cheap window ends."""

    trigger: datetime
    end: datetime


@dataclass(frozen=True)
class Attempt:
    """One try at tonight's write: the window it belongs to (None when unknown) and its number."""

    window: WriteWindow | None = None
    number: int = 1

    def next(self) -> Attempt:
        return Attempt(self.window, self.number + 1)


def latest_write_window(start: time, end: time, now: datetime) -> WriteWindow:
    """The newest window whose trigger (one minute before *start*) is at or before *now*.

    The window runs from *start* to *end* and may cross midnight. A window whose end equals
    its start is a whole day, which the inverter cannot be given, so it is treated as one day.
    """
    begin = now.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
    if begin - _ONE_MINUTE > now:
        begin -= _ONE_DAY
    length = timedelta(
        minutes=((end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)) % (24 * 60)
    )
    return WriteWindow(begin - _ONE_MINUTE, begin + (length or _ONE_DAY))


def retry_times(window: WriteWindow) -> list[datetime]:
    """The retry times: each offset after the trigger, while enough of the window remains."""
    stop = timedelta(minutes=CHARGE_WRITE_RETRY_STOP_BEFORE_END_MIN)
    times = (window.trigger + timedelta(minutes=m) for m in CHARGE_WRITE_RETRY_OFFSETS_MIN)
    return [at for at in times if window.end - at >= stop]


def next_retry(window: WriteWindow, now: datetime) -> datetime | None:
    """The first retry time after *now*, or None when the retries are used up."""
    return next((at for at in retry_times(window) if at > now), None)


def needs_catch_up(
    window: WriteWindow, now: datetime, entries: Iterable[Mapping[str, Any]], entity_id: str
) -> bool:
    """True when a restart finds the window open and tonight's write not done.

    It is open when *now* is after the trigger and at least the stop margin before the end.
    The write is done when the manager wrote the target entity since the trigger and no retry
    note came after that write. A note after the last write means that attempt failed.
    """
    stop = timedelta(minutes=CHARGE_WRITE_RETRY_STOP_BEFORE_END_MIN)
    if not (window.trigger < now and window.end - now >= stop):
        return False
    since = [
        (at, entry)
        for entry in entries
        if entry.get("entity_id") == entity_id
        if (at := _parse(entry.get("time"))) is not None and at >= window.trigger
    ]
    last_write = max((at for at, e in since if is_manager_write(e)), default=None)
    last_note = max((at for at, e in since if is_retry_note(e)), default=None)
    if last_write is None:
        return True
    return last_note is not None and last_note > last_write


def _parse(stamp: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
