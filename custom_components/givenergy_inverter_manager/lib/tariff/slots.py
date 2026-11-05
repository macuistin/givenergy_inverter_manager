"""slots.py: one local day of energy in half-hour slots.

A day starts at local midnight and runs to the next local midnight. Slots are counted in real
elapsed time, so a spring-forward day has 46 and a fall-back day has 50 (never assume 48).

Two kinds of energy are kept apart. Flows are the supply side at the grid and the inverter
(FLOWS). Loads are the consumers, by name: the house, the EV and the immersion are always
there and another can be added by name. Every figure is a reading, never derived from the
others, so a drift in one source shows up instead of being absorbed by another. The loads
overlap: "house" is the whole-house load as the inverter reports it, which includes the EV and
the immersion, and those are recorded on their own as well.

Each slot also keeps the seconds actually observed, so a slot with no data can be told from a
slot that used nothing, and the battery state of charge at the end of the slot.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any, NotRequired, TypedDict

from ..timeutil import elapsed_seconds
from .defaults import SLOT_SECONDS

FLOWS = ("import", "export", "solar", "battery_charge", "battery_discharge", "grid_to_battery")
DEFAULT_LOADS = ("house", "ev", "immersion")
STORAGE_VERSION = 1

_WH_PER_KWH = 1000
_LOAD_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class SlotEnergy:
    """Energy in kWh over one interval, as it is handed to SlotDay.add.

    flows: kWh by name, names from FLOWS only (a typo is refused, not stored).
    loads: kWh by name. Any lowercase name is allowed, so a new consumer needs no schema change.
    "house" is the whole-house load and includes the "ev" and "immersion" loads, so loads do not
    add up to a total.
    Both are readings from the inverter or the device, never worked out from each other.
    """

    flows: Mapping[str, float] = field(default_factory=dict)
    loads: Mapping[str, float] = field(default_factory=dict)

    def scaled(self, share: float) -> SlotEnergy:
        return SlotEnergy(
            {k: v * share for k, v in self.flows.items()},
            {k: v * share for k, v in self.loads.items()},
        )

    def check(self) -> None:
        """Refuse an unknown flow, a bad load name, or a negative or non-finite figure."""
        for name in self.flows:
            if name not in FLOWS:
                raise ValueError(f"unknown flow {name!r}")
        for name in self.loads:
            if not _LOAD_NAME.match(name):
                raise ValueError(f"load names are lowercase letters, digits and _, not {name!r}")
        for name, value in (*self.flows.items(), *self.loads.items()):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite number of kWh, 0 or more")


def local_midnight(day: date, tz: tzinfo) -> datetime:
    """Midnight at the start of *day* in *tz*."""
    return datetime.combine(day, time(0), tzinfo=tz)


def _slots_in_day(day: date, tz: tzinfo) -> int:
    start = local_midnight(day, tz)
    end = local_midnight(day + timedelta(days=1), tz)
    return round(elapsed_seconds(start, end) / SLOT_SECONDS)


class StoredSlotDay(TypedDict):
    """The saved form of one SlotDay, as written to storage and read back.

    The only definition of the stored shape. Change it only with a new `version`, and give
    from_storage a way to read the old one. Watt-hours are whole numbers to keep a year small.
    """

    version: int  # STORAGE_VERSION when written. An unknown version is skipped on load.
    date: str  # local calendar day, ISO 8601, e.g. "2026-06-01"
    start: str  # that day's local midnight with its UTC offset. A different offset is skipped.
    slots: int  # 48, or 46 and 50 on a clock-change day. Every list below has this length.
    flows_wh: dict[str, list[int]]  # name from FLOWS -> Wh in each slot
    # load name -> Wh per slot. house is the whole-house load and includes ev and immersion.
    loads_wh: dict[str, list[int]]
    soc_pct: list[float | None]  # battery state of charge at the end of each slot, null if unseen
    seconds: list[int]  # seconds of the slot actually observed, 0 to 1800
    # The inverter's own total for the day, in Wh, by name, as last read. Compare it with the sum
    # of the slots to see drift or missed time. Absent in a day saved before it was kept.
    counters_wh: NotRequired[dict[str, int]]


@dataclass
class SlotDay:
    """Energy in each slot of one local day, in memory.

    Slot i is the i-th half hour of real elapsed time since local midnight. Every list below has
    one entry per slot. StoredSlotDay is the saved form of this class.
    """

    day: date  # the local calendar day
    tz: tzinfo  # the zone whose midnight starts and ends the day
    flows: dict[str, list[float]] = field(default_factory=dict)  # FLOWS name -> kWh per slot
    loads: dict[str, list[float]] = field(default_factory=dict)  # load name -> kWh per slot
    seconds: list[float] = field(default_factory=list)  # observed time per slot, 0 to 1800
    soc_pct: list[float | None] = field(default_factory=list)  # end-of-slot charge, None unseen
    # The inverter's own total for the day by name, in kWh, as last read. Not part of the slots:
    # it is what they should add up to, kept so a drift can be seen. See `gap_kwh`.
    counters_kwh: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        count = _slots_in_day(self.day, self.tz)
        if not self.seconds:
            self.seconds = [0.0] * count
        if not self.soc_pct:
            self.soc_pct = [None] * count
        for name in FLOWS:
            self.flows.setdefault(name, [0.0] * count)
        for name in DEFAULT_LOADS:
            self.loads.setdefault(name, [0.0] * count)
        series: list[Sequence[object]] = [
            *self.flows.values(),
            *self.loads.values(),
            self.seconds,
            self.soc_pct,
        ]
        if any(len(s) != count for s in series):
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

    def total(self, name: str) -> float:
        """The day's total in kWh for a flow or a load."""
        return sum(self.flows[name] if name in self.flows else self.loads[name])

    def add(self, energy: SlotEnergy, start: datetime, end: datetime) -> None:
        """Spread *energy* evenly over [start, end), in proportion to the time in each slot.

        The interval must lie inside this day. Bad figures are refused before anything is booked.
        """
        energy.check()
        first, last = self._offset(start), self._offset(end)
        if not 0 <= first < last <= self.slot_count * SLOT_SECONDS:
            raise ValueError("the interval must be non-empty and inside the day")
        for load in energy.loads:
            self.loads.setdefault(load, [0.0] * self.slot_count)
        for index in range(int(first // SLOT_SECONDS), math.ceil(last / SLOT_SECONDS)):
            share = _overlap(first, last, index) / (last - first)
            self.seconds[index] += share * (last - first)
            _book(self.flows, energy.flows, index, share)
            _book(self.loads, energy.loads, index, share)

    def note_counters(self, readings: Mapping[str, float]) -> None:
        """Keep the inverter's day totals as last read. A later reading replaces an earlier one."""
        for name, value in readings.items():
            if name not in FLOWS and not _LOAD_NAME.match(name):
                raise ValueError(f"unknown series {name!r}")
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite number of kWh, 0 or more")
        self.counters_kwh.update(readings)

    def gap_kwh(self, name: str) -> float | None:
        """The inverter's day total less what the slots hold, None without a counter.

        Positive means the slots hold less than the inverter counted, for example time when
        Home Assistant was not running. It is never adjusted away.
        """
        if name not in self.counters_kwh:
            return None
        return self.counters_kwh[name] - self.total(name)

    def set_soc(self, moment: datetime, percent: float) -> None:
        """Note the battery state of charge in the slot holding *moment*. The last one wins."""
        offset = self._offset(moment)
        if not 0 <= percent <= 100 or not 0 <= offset < self.slot_count * SLOT_SECONDS:
            raise ValueError("a state of charge is 0 to 100 and must be inside the day")
        self.soc_pct[int(offset // SLOT_SECONDS)] = round(percent, 1)

    def _offset(self, moment: datetime) -> float:
        return elapsed_seconds(self.start, moment)

    def to_storage(self) -> StoredSlotDay:
        """JSON-safe form: whole watt-hours and whole seconds, to keep a year small."""
        return {
            "version": STORAGE_VERSION,
            "date": self.day.isoformat(),
            "start": self.start.isoformat(),
            "slots": self.slot_count,
            "flows_wh": _to_wh(self.flows),
            "loads_wh": _to_wh(self.loads),
            "soc_pct": list(self.soc_pct),
            "seconds": [round(s) for s in self.seconds],
            "counters_wh": {n: round(v * _WH_PER_KWH) for n, v in self.counters_kwh.items()},
        }

    @classmethod
    def from_storage(cls, data: Mapping[str, Any], tz: tzinfo) -> SlotDay:  # data: untrusted
        """Rebuild a day. Raises ValueError for anything that does not fit this day's slots.

        A day saved under another time zone or format version is refused, not converted.
        """
        try:
            if data["version"] != STORAGE_VERSION:
                raise ValueError(f"format version {data['version']}")
            day = date.fromisoformat(data["date"])
            flows = _from_wh(data["flows_wh"])
            loads = _from_wh(data["loads_wh"])
            seconds = [float(s) for s in data["seconds"]]
            soc = [None if v is None else float(v) for v in data["soc_pct"]]
            counters = _from_wh_values(data.get("counters_wh", {}))
            result = cls(day, tz, flows, loads, seconds, soc, counters)
            if data["start"] != result.start.isoformat():
                raise ValueError("saved under another time zone")
        except (KeyError, TypeError, ValueError) as err:
            raise ValueError(f"unreadable slot day: {err}") from err
        return result


def _book(
    target: dict[str, list[float]], kwh: Mapping[str, float], index: int, share: float
) -> None:
    for name, value in kwh.items():
        target[name][index] += value * share


def _to_wh(series: Mapping[str, list[float]]) -> dict[str, list[int]]:
    return {n: [round(v * _WH_PER_KWH) for v in vals] for n, vals in series.items()}


def _from_wh(stored: Mapping[str, list[Any]]) -> dict[str, list[float]]:
    return {n: [float(v) / _WH_PER_KWH for v in vals] for n, vals in stored.items()}


def _from_wh_values(stored: Mapping[str, Any]) -> dict[str, float]:
    return {n: float(v) / _WH_PER_KWH for n, v in stored.items()}


def _overlap(first: float, last: float, index: int) -> float:
    """Seconds of [first, last) that fall in slot *index*."""
    lo, hi = index * SLOT_SECONDS, (index + 1) * SLOT_SECONDS
    return max(0.0, min(last, hi) - max(first, lo))
