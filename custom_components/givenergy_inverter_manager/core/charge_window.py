"""
charge_window.py — size the charge window to the plan.

The integration writes slot 1 for the cheapest rate period. The inverter charges from the
window start and stops at the target, so the cheapest hours come first. When the plan needs
more hours than that period has, the window end is moved later, but never past the end of
the run of periods that are cheaper than the base rate straight after the cheapest period.
Extra window time at a cheaper-than-base rate costs nothing when the battery stops at its
target before the window closes.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from ..const import CHARGE_WINDOW_MARGIN, CHARGE_WINDOW_ROUND_MINUTES
from ..lib.tariff import RatePeriod, TariffConfig, cheapest_period
from .timeutil import elapsed_seconds, local_time_on

_MINUTES_PER_DAY = 24 * 60
# A window that ran the whole day would end where it starts, which the inverter reads as unused.
_MAX_WINDOW_MINUTES = _MINUTES_PER_DAY - 1


@dataclass(frozen=True)
class ChargeNeed:
    """How much the battery has to take in, and how fast it can."""

    soc: float
    target_soc: float
    capacity_kwh: float
    charge_power_w: float | None = None

    @property
    def deficit_kwh(self) -> float:
        """Energy that has to reach the battery to get from the current SoC to the target."""
        return max(0.0, self.capacity_kwh * (self.target_soc - self.soc) / 100)

    @property
    def charge_power_kw(self) -> float:
        """The charge rate in kW, or 0.0 when it is not known."""
        power_w = self.charge_power_w
        return power_w / 1000 if power_w is not None and power_w > 0 else 0.0


@dataclass(frozen=True)
class ChargeWindow:
    """The window to write, and what the plan expects from it."""

    start: time
    end: time
    extended: bool
    # Energy the battery should take in within the window, None when the charge rate is unknown.
    expected_kwh: float | None
    # When the battery should reach the target, None when it is already there, the rate is
    # unknown or the window ends first.
    finish_time: time | None

    @property
    def text(self) -> str:
        return f"{self.start.strftime('%H:%M')} to {self.end.strftime('%H:%M')}"


def _minute_of_day(at: time) -> int:
    return at.hour * 60 + at.minute


def _time_of(minute: int) -> time:
    minute %= _MINUTES_PER_DAY
    return time(minute // 60, minute % 60)


def _minutes_from(start: int, to: int) -> int:
    """Minutes forward on the clock from one minute of the day to another, wrapping midnight."""
    return (to - start) % _MINUTES_PER_DAY


def _span(period: RatePeriod) -> int:
    return _minutes_from(_minute_of_day(period.start), _minute_of_day(period.end))


def _reach_from(period: RatePeriod, minute: int) -> int:
    """Minutes the period still runs from this minute, 0 when it is not active then."""
    start = _minute_of_day(period.start)
    elapsed = _minutes_from(start, minute)
    return _span(period) - elapsed if elapsed < _span(period) else 0


def _cheaper_than_base(tariff: TariffConfig) -> list[RatePeriod]:
    return [p for p in tariff.rate_periods if p.rate < tariff.base_rate]


def _extend_run(cheaper: list[RatePeriod], start: int, length: int) -> int:
    """Grow a run of *length* minutes from minute *start* while a cheaper period carries on."""
    while length < _MAX_WINDOW_MINUTES:
        reach = max((_reach_from(p, start + length) for p in cheaper), default=0)
        if reach == 0:
            break
        length += reach
    return min(length, _MAX_WINDOW_MINUTES)


def cheap_run_minutes(tariff: TariffConfig) -> int:
    """Minutes from the cheapest period's start to the end of the cheaper-than-base run after it.

    Periods can overlap, for example a Night period around a shorter, cheaper one. The run
    follows whichever period reaches furthest at each end point and stops where no period
    cheaper than the base rate is active. It is never longer than a day less a minute.
    """
    cheapest = cheapest_period(tariff)
    return _extend_run(_cheaper_than_base(tariff), _minute_of_day(cheapest.start), _span(cheapest))


def window_stays_cheap(tariff: TariffConfig, start: time, end: time) -> bool:
    """True when every minute from *start* to *end* is at a rate below the base rate.

    A window whose start equals its end is unused and counts as cheap. A tariff with no period
    below the base rate has no cheap hours to protect, so any window counts as cheap too.
    """
    cheaper = _cheaper_than_base(tariff)
    first, last = _minute_of_day(start), _minute_of_day(end)
    if not cheaper or first == last:
        return True
    return all(
        any(_reach_from(period, first + offset) > 0 for period in cheaper)
        for offset in range(_minutes_from(first, last))
    )


def cheap_run_remaining_minutes(tariff: TariffConfig, now: datetime) -> float | None:
    """Minutes from *now* to the end of the cheaper-than-base run *now* sits in, else None.

    The run is the same as in cheap_run_minutes, so inside a short cheap period within a longer
    one, it ends with the longer one. The end is a wall-clock time, so a clock change inside
    the run shortens or lengthens the wait by the real hour.
    """
    cheaper = _cheaper_than_base(tariff)
    minute = _minute_of_day(now.time())
    reach = max((_reach_from(p, minute) for p in cheaper), default=0)
    if reach == 0:
        return None
    end_at = _time_of(minute + _extend_run(cheaper, minute, reach))
    end = local_time_on(now, end_at)
    if elapsed_seconds(now, end) <= 0:
        end = local_time_on(now + timedelta(days=1), end_at)
    return round(elapsed_seconds(now, end) / 60, 1)


def in_extended_cheap_window(
    tariff: TariffConfig, now: datetime, hours_before: float, hours_after: float
) -> bool:
    """True inside a cheaper-than-base period, or in the hours the owner added around one.

    *hours_before* come before each such period starts and *hours_after* after it ends. A tariff
    with no period below the base rate has none, so the answer is always False.
    """
    minute = _minute_of_day(now.time())
    before, after = round(hours_before * 60), round(hours_after * 60)
    for period in _cheaper_than_base(tariff):
        total = min(before + _span(period) + after, _MINUTES_PER_DAY)
        if (minute - (_minute_of_day(period.start) - before)) % _MINUTES_PER_DAY < total:
            return True
    return False


def _join_once(runs: list[tuple[int, int]]) -> list[tuple[int, int]] | None:
    """The runs with one overlapping pair joined, None when no two overlap."""
    for i, (start, length) in enumerate(runs):
        for j, (other, other_length) in enumerate(runs):
            gap = _minutes_from(start, other)
            if i != j and gap <= length:
                joined = (start, min(max(length, gap + other_length), _MAX_WINDOW_MINUTES))
                return [r for k, r in enumerate(runs) if k not in (i, j)] + [joined]
    return None


def _merge_runs(runs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Runs of (start minute, length) with any that overlap or touch joined into one."""
    merged = list(runs)
    while (joined := _join_once(merged)) is not None:
        merged = joined
    return merged


def ev_charge_window(
    tariff: TariffConfig, now: datetime, hours_before: float, hours_after: float
) -> tuple[time, time] | None:
    """The window the car may charge from the grid: the one holding *now*, else the next.

    It is the cheaper-than-base periods widened by the owner's hours before and after, with any
    that overlap joined. None when the tariff has no period below the base rate.
    """
    before, after = round(hours_before * 60), round(hours_after * 60)
    runs = [
        ((_minute_of_day(p.start) - before) % _MINUTES_PER_DAY, before + _span(p) + after)
        for p in _cheaper_than_base(tariff)
    ]
    if not runs:
        return None
    minute = _minute_of_day(now.time())
    merged = _merge_runs([(s, min(n, _MAX_WINDOW_MINUTES)) for s, n in runs])
    current = [r for r in merged if _minutes_from(r[0], minute) < r[1]]
    start, length = current[0] if current else min(
        merged, key=lambda r: _minutes_from(minute, r[0])
    )
    return _time_of(start), _time_of(start + length)


def _minutes_needed(need: ChargeNeed) -> int:
    """Window minutes the plan needs, with the safety margin, rounded up to a whole step."""
    hours = need.deficit_kwh / need.charge_power_kw
    step = CHARGE_WINDOW_ROUND_MINUTES
    return math.ceil(hours * 60 * (1 + CHARGE_WINDOW_MARGIN) / step) * step


def _window_minutes(tariff: TariffConfig, need: ChargeNeed) -> int:
    """The window length: the cheapest period, longer when the plan needs it and the run allows."""
    own = _span(cheapest_period(tariff))
    if need.deficit_kwh <= 0 or need.charge_power_kw <= 0:
        return own
    needed = _minutes_needed(need)
    if needed <= own:
        return own
    return min(needed, cheap_run_minutes(tariff))


def _expected_kwh(need: ChargeNeed, window_minutes: int) -> float | None:
    if need.charge_power_kw <= 0:
        return None
    return round(min(need.deficit_kwh, need.charge_power_kw * window_minutes / 60), 2)


def _finish_time(need: ChargeNeed, start: int, window_minutes: int) -> time | None:
    if need.deficit_kwh <= 0 or need.charge_power_kw <= 0:
        return None
    minutes = math.ceil(need.deficit_kwh / need.charge_power_kw * 60)
    return _time_of(start + minutes) if minutes <= window_minutes else None


def plan_charge_window(tariff: TariffConfig, need: ChargeNeed) -> ChargeWindow:
    """The charge window for the plan.

    The start is the cheapest period's start. The end is the cheapest period's end when the
    plan fits it, and otherwise as late as the plan needs, within the run of periods cheaper
    than the base rate. An unknown charge rate leaves the window as the cheapest period.
    Needs at least one timed rate period.
    """
    cheapest = cheapest_period(tariff)
    start = _minute_of_day(cheapest.start)
    minutes = _window_minutes(tariff, need)
    extended = minutes > _span(cheapest)
    return ChargeWindow(
        start=cheapest.start,
        end=_time_of(start + minutes) if extended else cheapest.end,
        extended=extended,
        expected_kwh=_expected_kwh(need, minutes),
        finish_time=_finish_time(need, start, minutes),
    )


# Any date does: a rate period is matched on the time of day alone.
_RATE_DAY = datetime(2000, 1, 1)


def _rate_at(tariff: TariffConfig, minute: int) -> float:
    """The rate in force at this minute of the day, the cheapest of the periods active then."""
    return tariff.get_current_rate(_RATE_DAY + timedelta(minutes=minute)).rate


def window_charge_cost(
    tariff: TariffConfig, window: ChargeWindow, need: ChargeNeed
) -> float | None:
    """What the charge costs when it is paid at the rate in force while it runs.

    The battery charges at its own pace from the window start, so the cheapest hours come first
    and an extended window pays the rate of the periods after them for what is left. Energy the
    window cannot deliver is priced at the rate of its last minute. None when the charge rate is
    unknown, which leaves no way to say how long the charge runs in each period.
    """
    if need.charge_power_kw <= 0:
        return None
    start = _minute_of_day(window.start)
    last = max(_minutes_from(start, _minute_of_day(window.end)) - 1, 0)
    per_minute = need.charge_power_kw / 60
    left, cost = need.deficit_kwh, 0.0
    for offset in range(last + 1):
        taken = min(left, per_minute)
        cost += taken * _rate_at(tariff, start + offset)
        left -= taken
    return cost + left * _rate_at(tariff, start + last)
