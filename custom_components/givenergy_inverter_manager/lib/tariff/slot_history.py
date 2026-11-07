"""slot_history.py: the slot days kept, with retention, midnight splitting and storage."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

from ..timeutil import elapsed_seconds
from .defaults import SLOT_MAX_INTERVAL_SECONDS, SLOT_RETENTION_DAYS
from .slots import SlotDay, SlotEnergy, StoredSlotDay


class SlotHistory:
    """Slot days by date, oldest dropped after the retention period."""

    def __init__(self, tz: tzinfo, retention_days: int = SLOT_RETENTION_DAYS) -> None:
        self._tz = tz
        self._retention = retention_days
        self._days: dict[date, SlotDay] = {}
        # Stored days that could not be read the last time the history was restored.
        self.skipped = 0

    def record(self, energy: SlotEnergy, start: datetime, end: datetime) -> bool:
        """Book *energy* used between start and end. False when the interval is a gap or empty.

        An interval that crosses midnight is split between the two days by time. Nothing is
        booked for a gap, and the slots it spans keep their old observed seconds, so coverage
        shows the hole.
        """
        total = elapsed_seconds(start, end)
        if not 0 < total <= SLOT_MAX_INTERVAL_SECONDS:
            return False
        # Two datetimes in one zone compare by their clock fields and ignore which side of a clock
        # change they are on, so an interval in the repeated hour would look empty. UTC compares
        # by real time.
        if start.tzinfo is not None and end.tzinfo is not None:
            start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
        cursor = start
        while cursor < end:
            day = self._day_for(cursor.astimezone(self._tz).date())
            piece_end = min(end, day.end)
            share = elapsed_seconds(cursor, piece_end) / total
            day.add(energy.scaled(share), cursor, piece_end)
            cursor = piece_end
        self._prune(end.astimezone(self._tz).date())
        return True

    def record_soc(self, moment: datetime, percent: float) -> None:
        """Note the battery state of charge in the slot holding *moment*."""
        self._day_for(moment.astimezone(self._tz).date()).set_soc(moment, percent)

    def note_counters(self, day: date, readings: Mapping[str, float]) -> None:
        """Keep the inverter's day totals for *day* as last read."""
        self._day_for(day).note_counters(readings)

    def get(self, day: date) -> SlotDay | None:
        return self._days.get(day)

    def between(self, first: date, last: date) -> list[SlotDay]:
        """The days recorded from *first* to *last* inclusive, oldest first."""
        return [self._days[d] for d in sorted(self._days) if first <= d <= last]

    def summary(self, days: int = 7) -> list[dict[str, Any]]:
        """The newest days, newest first, for diagnostics.

        Each row has the day's coverage and, for each series that has data or an inverter
        total, the slots' total, the inverter's own day total and the gap between them (kWh).
        """
        newest = sorted(self._days, reverse=True)[:days]
        return [_day_summary(self._days[d]) for d in newest]

    def to_storage(self) -> list[StoredSlotDay]:
        return [self._days[d].to_storage() for d in sorted(self._days)]

    def restore(self, stored: list[Any]) -> None:
        """Load stored days, skipping and counting any that cannot be read."""
        self._days = {}
        self.skipped = 0
        for item in stored:
            try:
                day = SlotDay.from_storage(item, self._tz)
            except ValueError, TypeError, AttributeError:
                self.skipped += 1
                continue
            self._days[day.day] = day

    def _day_for(self, day: date) -> SlotDay:
        if day not in self._days:
            self._days[day] = SlotDay(day, self._tz)
        return self._days[day]

    def _prune(self, today: date) -> None:
        oldest = today - timedelta(days=self._retention - 1)
        for day in [d for d in self._days if d < oldest]:
            del self._days[day]


def _series_summary(day: SlotDay, name: str) -> dict[str, float | None]:
    counter = day.counters_kwh.get(name)
    gap = day.gap_kwh(name)
    return {
        "slots_kwh": round(day.total(name), 3),
        "inverter_kwh": None if counter is None else round(counter, 3),
        "gap_kwh": None if gap is None else round(gap, 3),
    }


def _day_summary(day: SlotDay) -> dict[str, Any]:
    names = [n for n in (*day.flows, *day.loads) if day.total(n) or n in day.counters_kwh]
    return {
        "date": day.day.isoformat(),
        "coverage": round(day.coverage, 3),
        "series": {n: _series_summary(day, n) for n in names},
    }
