"""slots.py: one local day of energy in half-hour slots.

A day starts at local midnight and runs to the next local midnight. Slots are counted in real
elapsed time, so a spring-forward day has 46 and a fall-back day has 50 (never assume 48).
Each slot holds kWh for several named series, and the seconds actually observed, so a slot with
no data can be told from a slot that used nothing.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from ..timeutil import elapsed_seconds
from .defaults import SLOT_SECONDS

SERIES = (
    "import_kwh",
    "export_kwh",
    "house_kwh",
    "ev_kwh",
    "immersion_kwh",
    "solar_kwh",
    "grid_to_battery_kwh",
)

_WH_PER_KWH = 1000


def local_midnight(day: date, tz: tzinfo) -> datetime:
    """Midnight at the start of *day* in *tz*."""
    return datetime.combine(day, time(0), tzinfo=tz)


def _slots_in_day(day: date, tz: tzinfo) -> int:
    start = local_midnight(day, tz)
    end = local_midnight(day + timedelta(days=1), tz)
    return round(elapsed_seconds(start, end) / SLOT_SECONDS)


@dataclass
class SlotDay:
    """Energy in each slot of one local day."""

    day: date
    tz: tzinfo
    kwh: dict[str, list[float]] = field(default_factory=dict)
    seconds: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        count = _slots_in_day(self.day, self.tz)
        if not self.seconds:
            self.seconds = [0.0] * count
        for name in SERIES:
            self.kwh.setdefault(name, [0.0] * count)
        if len(self.seconds) != count or any(len(v) != count for v in self.kwh.values()):
            raise ValueError(f"{self.day} has {count} slots here, the data does not match")

    @property
    def start(self) -> datetime:
        return local_midnight(self.day, self.tz)

    @property
    def end(self) -> datetime:
        return local_midnight(self.day + timedelta(days=1), self.tz)

    @property
    def slot_count(self) -> int:
        return len(self.seconds)

    @property
    def coverage(self) -> float:
        """Share of the day that was observed, 0 to 1."""
        observed = sum(min(s, SLOT_SECONDS) for s in self.seconds)
        return observed / (self.slot_count * SLOT_SECONDS)

    def total(self, series: str) -> float:
        """The day's total for one series, in kWh."""
        return sum(self.kwh[series])

    def add(self, kwh: Mapping[str, float], start: datetime, end: datetime) -> None:
        """Spread *kwh* evenly over [start, end), in proportion to the time in each slot.

        The interval must lie inside this day. A negative or non-finite figure and an unknown
        series are refused before anything is booked.
        """
        _check_series(kwh)
        first, last = self._offset(start), self._offset(end)
        if not 0 <= first < last <= self.slot_count * SLOT_SECONDS:
            raise ValueError("the interval must be non-empty and inside the day")
        for index in range(int(first // SLOT_SECONDS), math.ceil(last / SLOT_SECONDS)):
            share = _overlap(first, last, index) / (last - first)
            self.seconds[index] += share * (last - first)
            for name, value in kwh.items():
                self.kwh[name][index] += value * share

    def _offset(self, moment: datetime) -> float:
        return elapsed_seconds(self.start, moment)

    def to_storage(self) -> dict[str, Any]:
        """JSON-safe form: whole watt-hours and whole seconds, to keep a year small."""
        return {
            "date": self.day.isoformat(),
            "slots": self.slot_count,
            "wh": {n: [round(v * _WH_PER_KWH) for v in vals] for n, vals in self.kwh.items()},
            "seconds": [round(s) for s in self.seconds],
        }

    @classmethod
    def from_storage(cls, data: Mapping[str, Any], tz: tzinfo) -> SlotDay:
        """Rebuild a day. Raises ValueError for anything that does not fit this day's slots."""
        try:
            day = date.fromisoformat(data["date"])
            wh = data["wh"]
            kwh = {n: [float(v) / _WH_PER_KWH for v in wh[n]] for n in SERIES}
            seconds = [float(s) for s in data["seconds"]]
        except (KeyError, TypeError, ValueError) as err:
            raise ValueError(f"unreadable slot day: {err}") from err
        return cls(day, tz, kwh, seconds)


def _check_series(kwh: Mapping[str, float]) -> None:
    for name, value in kwh.items():
        if name not in SERIES:
            raise ValueError(f"unknown series {name!r}")
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite number of kWh, 0 or more")


def _overlap(first: float, last: float, index: int) -> float:
    """Seconds of [first, last) that fall in slot *index*."""
    lo, hi = index * SLOT_SECONDS, (index + 1) * SLOT_SECONDS
    return max(0.0, min(last, hi) - max(first, lo))
