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
from datetime import time

from ..const import CHARGE_WINDOW_MARGIN, CHARGE_WINDOW_ROUND_MINUTES
from .tariff import RatePeriod, TariffConfig

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


def cheapest_period(tariff: TariffConfig) -> RatePeriod:
    """The timed rate period with the lowest rate."""
    return min(tariff.rate_periods, key=lambda p: p.rate)


def cheap_run_minutes(tariff: TariffConfig) -> int:
    """Minutes from the cheapest period's start to the end of the cheaper-than-base run after it.

    Periods can overlap, for example a Night period around a shorter, cheaper one. The run
    follows whichever period reaches furthest at each end point and stops where no period
    cheaper than the base rate is active. It is never longer than a day less a minute.
    """
    cheapest = cheapest_period(tariff)
    start = _minute_of_day(cheapest.start)
    cheaper = [p for p in tariff.rate_periods if p.rate < tariff.base_rate]
    length = _span(cheapest)
    while length < _MAX_WINDOW_MINUTES:
        reach = max((_reach_from(p, start + length) for p in cheaper), default=0)
        if reach == 0:
            break
        length += reach
    return min(length, _MAX_WINDOW_MINUTES)


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
