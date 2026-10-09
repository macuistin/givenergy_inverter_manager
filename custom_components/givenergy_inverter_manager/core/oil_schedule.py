"""
oil_schedule.py: a recurring oil schedule, learned from when the immersion heats the water.

The immersion sometimes heats the water from the grid at a rate that costs more than oil, for
example a top-up after the midday showers. This module keeps a rolling record of that heating
and, once it has seen a week of it, suggests the hours when running the oil instead would have
saved money.

The record (ImmersionHeatLog) holds, for each local hour of the last 14 complete days and the
day in progress, the grid energy the immersion used and what it cost. Cost is stored, not the
rate, so an hour that mixed two rates keeps its exact total. Only energy that solar surplus did
not cover is recorded. The oil price is not stored: it is read when the suggestion is worked
out, so a price change applies to the whole record at once.

The suggestion:

  1. An hour of the day counts as a habit when the immersion used at least
     OIL_SCHEDULE_MIN_HOUR_KWH from the grid in it, at a cost per kWh above oil, on at least one
     day in OIL_SCHEDULE_REPEAT_ONE_IN.
  2. Adjacent habit hours are joined into one block.
  3. Each block becomes an oil window that ends where the immersion started, the start of the
     block's first hour, so the oil runs just before it and the immersion finds the water at
     the target. The run is as long as the immersion took on the days it ran, at the
     immersion's heating rate (the oil_start.py assumption: an oil coil heats at least as fast).
  4. The saving of a window is what the dearer-than-oil grid heat in its hours would have saved
     at the oil price. Windows under OIL_SCHEDULE_MIN_SAVING_PER_WEEK are dropped, and the best
     OIL_SCHEDULE_MAX_WINDOWS stay.

Advice only. The integration never switches the oil system. Pure Python, no Home Assistant
imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import groupby

from ..const import (
    OIL_SCHEDULE_MAX_WINDOWS,
    OIL_SCHEDULE_MIN_DAYS,
    OIL_SCHEDULE_MIN_HOUR_KWH,
    OIL_SCHEDULE_MIN_SAVING_PER_WEEK,
    OIL_SCHEDULE_RECORD_DAYS,
    OIL_SCHEDULE_REPEAT_ONE_IN,
)
from .oil_start import round_up_run_minutes

HOURS_PER_DAY = 24
_MINUTES_PER_HOUR = 60
_MINUTES_PER_DAY = HOURS_PER_DAY * _MINUTES_PER_HOUR
_DAYS_PER_WEEK = 7
_STORED_DECIMALS = 4
_BIG_KWH = 10  # from here the energy in the sentence needs no decimal place


def _empty_day() -> list[float]:
    return [0.0] * HOURS_PER_DAY


@dataclass
class HeatDay:
    """One local day: grid energy (kWh) and its cost for each hour of the day."""

    date: str
    kwh: list[float] = field(default_factory=_empty_day)
    cost: list[float] = field(default_factory=_empty_day)


def _is_hour_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == HOURS_PER_DAY
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
    )


def _restore_day(entry: object) -> HeatDay | None:
    """A day from its stored form, None when the entry is damaged."""
    if not isinstance(entry, dict):
        return None
    stored_date = entry.get("date")
    if not isinstance(stored_date, str) or not _is_hour_list(entry.get("kwh")):
        return None
    if not _is_hour_list(entry.get("cost")):
        return None
    try:
        date.fromisoformat(stored_date)
    except ValueError:
        return None
    return HeatDay(stored_date, [float(v) for v in entry["kwh"]], [float(v) for v in entry["cost"]])


@dataclass
class ImmersionHeatLog:
    """The rolling record of the immersion's grid heating, oldest day first."""

    days: list[HeatDay] = field(default_factory=list)

    def add(self, now: datetime, kwh: float, cost: float) -> None:
        """Add grid energy and its cost to the local hour of *now*. Zero still notes the day."""
        day = self._day(now.date().isoformat())
        day.kwh[now.hour] += kwh
        day.cost[now.hour] += cost
        self._forget_old_days()

    def completed(self, today: date) -> list[HeatDay]:
        """The complete days within the record, today's still in progress left out."""
        oldest = (today - timedelta(days=OIL_SCHEDULE_RECORD_DAYS)).isoformat()
        return [d for d in self.days if oldest <= d.date < today.isoformat()]

    def to_storage(self) -> list[dict]:
        return [
            {
                "date": day.date,
                "kwh": [round(v, _STORED_DECIMALS) for v in day.kwh],
                "cost": [round(v, _STORED_DECIMALS) for v in day.cost],
            }
            for day in self.days
        ]

    @classmethod
    def from_storage(cls, stored: object) -> ImmersionHeatLog:
        """The record from its stored form. Damaged entries are skipped."""
        entries = stored if isinstance(stored, list) else []
        days = [day for day in map(_restore_day, entries) if day is not None]
        return cls(sorted(days, key=lambda day: day.date))

    def _day(self, iso_date: str) -> HeatDay:
        for day in self.days:
            if day.date == iso_date:
                return day
        day = HeatDay(iso_date)
        self.days = sorted([*self.days, day], key=lambda d: d.date)
        return day

    def _forget_old_days(self) -> None:
        newest = date.fromisoformat(self.days[-1].date)
        oldest = (newest - timedelta(days=OIL_SCHEDULE_RECORD_DAYS)).isoformat()
        self.days = [d for d in self.days if d.date >= oldest]


@dataclass(frozen=True)
class ScheduleQuery:
    """What the suggestion needs besides the record: the oil price per kWh of heat, the heater."""

    today: date
    oil_cost_per_kwh: float
    heater_kw: float
    currency_symbol: str


@dataclass(frozen=True)
class OilSchedule:
    """What the record says. windows are "HH:MM to HH:MM", empty when there is nothing to suggest.

    days is how many complete days were read. saving is over those days, in the configured
    currency. sentence is None when there are no windows.
    """

    days: int
    windows: tuple[str, ...] = ()
    saving: float = 0.0
    sentence: str | None = None


@dataclass(frozen=True)
class _Hour:
    """One hour of the day over the record: the days it was dearer than oil, and what that was."""

    dear_days: int
    kwh: float
    saving: float


@dataclass(frozen=True)
class _Window:
    start_minute: int
    end_minute: int
    kwh: float
    saving: float
    busiest_hour: int

    @property
    def label(self) -> str:
        return f"{_clock(self.start_minute)} to {_clock(self.end_minute)}"


def _clock(minute: int) -> str:
    return f"{minute // _MINUTES_PER_HOUR:02d}:{minute % _MINUTES_PER_HOUR:02d}"


def _is_dear(day: HeatDay, hour: int, oil: float) -> bool:
    """True when the immersion heated from the grid this hour at a rate above oil."""
    kwh = day.kwh[hour]
    return kwh >= OIL_SCHEDULE_MIN_HOUR_KWH and day.cost[hour] > kwh * oil


def _summarise_hour(days: list[HeatDay], hour: int, oil: float) -> _Hour:
    dear = [day for day in days if _is_dear(day, hour, oil)]
    kwh = sum(day.kwh[hour] for day in dear)
    cost = sum(day.cost[hour] for day in dear)
    return _Hour(len(dear), kwh, cost - kwh * oil)


def _runs(flags: list[bool]) -> list[range]:
    """The stretches of consecutive true flags, as ranges of hours."""
    runs = []
    for is_set, group in groupby(enumerate(flags), key=lambda item: item[1]):
        hours = [hour for hour, _ in group]
        if is_set:
            runs.append(range(hours[0], hours[-1] + 1))
    return runs


def _window(
    days: list[HeatDay], hours: list[_Hour], block: range, query: ScheduleQuery
) -> _Window:
    """The oil window for a block, ending at the block's first hour. Its start is not set here."""
    kwh = sum(hours[h].kwh for h in block)
    ran_on = sum(1 for d in days if any(_is_dear(d, h, query.oil_cost_per_kwh) for h in block))
    run = round_up_run_minutes(kwh / ran_on / query.heater_kw)
    end = block.start * _MINUTES_PER_HOUR
    return _Window(
        start_minute=end - run,
        end_minute=end,
        kwh=kwh,
        saving=sum(hours[h].saving for h in block),
        busiest_hour=max(block, key=lambda h: hours[h].kwh),
    )


def _after_earlier_heating(window: _Window, earlier_end: int | None) -> _Window:
    """The window cut so it starts no earlier than the heating before it ended, and as a clock."""
    start = window.start_minute if earlier_end is None else max(window.start_minute, earlier_end)
    return _Window(
        start % _MINUTES_PER_DAY,
        window.end_minute % _MINUTES_PER_DAY,
        window.kwh,
        window.saving,
        window.busiest_hour,
    )


def _all_windows(days: list[HeatDay], query: ScheduleQuery) -> list[_Window]:
    oil = query.oil_cost_per_kwh
    hours = [_summarise_hour(days, hour, oil) for hour in range(HOURS_PER_DAY)]
    needed = -(-len(days) // OIL_SCHEDULE_REPEAT_ONE_IN)
    windows, earlier_end = [], None
    for block in _runs([hour.dear_days >= needed for hour in hours]):
        windows.append(_after_earlier_heating(_window(days, hours, block, query), earlier_end))
        earlier_end = block.stop * _MINUTES_PER_HOUR
    return windows


def _best_windows(days: list[HeatDay], query: ScheduleQuery) -> list[_Window]:
    """The windows worth setting up, the biggest savings first kept, then in time order."""
    if query.heater_kw <= 0:
        return []
    weeks = len(days) / _DAYS_PER_WEEK
    worth = [
        w
        for w in _all_windows(days, query)
        if w.saving / weeks >= OIL_SCHEDULE_MIN_SAVING_PER_WEEK
    ]
    best = sorted(worth, key=lambda w: w.saving, reverse=True)[:OIL_SCHEDULE_MAX_WINDOWS]
    return sorted(best, key=lambda w: w.end_minute)


def _list_in_words(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _kwh_text(kwh: float) -> str:
    return f"{kwh:.0f}" if kwh >= _BIG_KWH else f"{kwh:.1f}"


def _sentence(days: int, windows: list[_Window], symbol: str) -> str:
    around = _list_in_words([f"{w.busiest_hour:02d}:00" for w in windows])
    runs = _list_in_words([w.label for w in windows])
    kwh = _kwh_text(sum(w.kwh for w in windows))
    saving = sum(w.saving for w in windows)
    return (
        f"Over the last {days} days the immersion used about {kwh} kWh of grid electricity "
        f"that cost more than oil, mostly around {around}. Running the oil from {runs} "
        f"would have saved about {symbol}{saving:.2f} over those days."
    )


def suggest_oil_schedule(log: ImmersionHeatLog, query: ScheduleQuery) -> OilSchedule | None:
    """The suggested oil windows, None until the record holds OIL_SCHEDULE_MIN_DAYS days."""
    days = log.completed(query.today)
    if len(days) < OIL_SCHEDULE_MIN_DAYS:
        return None
    windows = _best_windows(days, query)
    if not windows:
        return OilSchedule(len(days))
    return OilSchedule(
        days=len(days),
        windows=tuple(w.label for w in windows),
        saving=sum(w.saving for w in windows),
        sentence=_sentence(len(days), windows, query.currency_symbol),
    )
