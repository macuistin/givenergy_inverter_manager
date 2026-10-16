"""
battery_pause.py: a window in which the battery serves no load.

The inverter can pause battery discharge for a time of day window. While it is paused the grid
serves the house and the battery holds its charge. Charging can still happen. Every estimate
that runs the battery down on the house load has to leave that load out for the paused part of
its span. PauseWindow answers "how much of this span is paused", in minutes and in the 48 half
hour slots the charge plan uses, and it handles a window that wraps midnight.

A backend turns what its inverter integration publishes into a PauseWindow, or None when there
is no pause that stops discharge. Nothing here knows an entity name or an option string.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

MINUTES_PER_DAY = 24 * 60
SLOT_MINUTES = 30
SLOTS_PER_DAY = MINUTES_PER_DAY // SLOT_MINUTES
_HALF = 0.5


def _minute_of_day(at: time) -> int:
    return at.hour * 60 + at.minute


@dataclass(frozen=True)
class PauseWindow:
    """The local time window in which the battery does not discharge, wrapping midnight.

    The window runs from start up to end. A start after the end wraps midnight, so 23:00 to
    08:00 is the night. A start equal to the end is an empty window that pauses nothing.
    """

    start: time
    end: time

    @property
    def text(self) -> str:
        """The window as words, for example '23:00 to 08:00'."""
        return f"{self.start:%H:%M} to {self.end:%H:%M}"

    @property
    def note(self) -> str:
        """The window as a sentence for a reason or an explanation."""
        return f"The battery is paused from {self.text}."

    def _intervals(self) -> tuple[tuple[int, int], ...]:
        """The window as intervals of minutes inside one day."""
        start, end = _minute_of_day(self.start), _minute_of_day(self.end)
        if start == end:
            return ()
        if start < end:
            return ((start, end),)
        return ((start, MINUTES_PER_DAY), (0, end))

    def _paused_within(self, from_minute: float, minutes: float) -> list[tuple[float, float]]:
        """The paused parts of a span as (start, end), in order. The span may pass midnight.

        The span starts at a minute of the day and may be longer than a day. Minutes past
        1440 are the next day.
        """
        span_end = from_minute + minutes
        found: list[tuple[float, float]] = []
        day = int(from_minute // MINUTES_PER_DAY)
        while day * MINUTES_PER_DAY < span_end:
            for begin, finish in self._intervals():
                low = max(from_minute, day * MINUTES_PER_DAY + begin)
                high = min(span_end, day * MINUTES_PER_DAY + finish)
                if high > low:
                    found.append((low, high))
            day += 1
        return found

    def paused_minutes(self, from_minute: float, minutes: float) -> float:
        """How many minutes of the span the battery is paused."""
        return sum(high - low for low, high in self._paused_within(from_minute, minutes))

    def paused_hours(self, from_minute: float, hours: float) -> float:
        """How many hours of the span the battery is paused."""
        return self.paused_minutes(from_minute, hours * 60) / 60

    def unpaused_spans(self, from_minute: float, minutes: float) -> list[tuple[float, float]]:
        """The parts of the span in which the battery serves the house, as (start, minutes)."""
        span_end = from_minute + minutes
        spans: list[tuple[float, float]] = []
        cursor = from_minute
        for low, high in self._paused_within(from_minute, minutes):
            if low > cursor:
                spans.append((cursor, low - cursor))
            cursor = high
        if span_end > cursor:
            spans.append((cursor, span_end - cursor))
        return spans

    def paused_fraction(self, slot: int) -> float:
        """The share of one half hour slot that is paused, 0.0 to 1.0. Slot 0 starts at 00:00."""
        return self.paused_minutes(slot * SLOT_MINUTES, SLOT_MINUTES) / SLOT_MINUTES

    def is_slot_paused(self, slot: int) -> bool:
        """True when more than half of the slot is paused."""
        return self.paused_fraction(slot) > _HALF


def with_note(text: str, pause: PauseWindow | None) -> str:
    """The text with the pause sentence after it, once. Unchanged without a pause."""
    if pause is None or pause.note in text:
        return text
    sentence = text if text.endswith((".", "!", "?")) else f"{text}."
    return f"{sentence} {pause.note}"
