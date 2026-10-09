"""
immersion_window.py: the cheapest rate window the immersion heats in.

The window is the cheapest timed rate period, the one the battery charge also starts in. It
counts only when its rate is below the base rate, so a tariff whose only timed period is
dearer than the base rate has no window. Whether to heat in it, and until when, is decided
by `rules.should_divert_to_immersion`.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .charge_window import cheapest_period
from .tariff import RatePeriod, TariffConfig
from .timeutil import elapsed_seconds, local_time_on


def open_cheapest_window(tariff: TariffConfig, now: datetime) -> str | None:
    """Name and hours of the cheapest period when it is cheaper than the base rate and open now."""
    if not tariff.rate_periods:
        return None
    period = cheapest_period(tariff)
    if period.rate >= tariff.base_rate or not period.is_active(now):
        return None
    return f"{period.name} {period.start:%H:%M} to {period.end:%H:%M}"


@dataclass(frozen=True)
class WindowOpening:
    """The cheapest window as one stretch of time: the one open now, else the next to open."""

    name: str
    start: datetime
    end: datetime
    is_open: bool


def _opening_start(period: RatePeriod, now: datetime) -> datetime:
    """When the window that is open now opened: today's start, or yesterday's after midnight."""
    start = local_time_on(now, period.start)
    if elapsed_seconds(now, start) > 0:
        return local_time_on(now - timedelta(days=1), period.start)
    return start


def _next_start(period: RatePeriod, now: datetime) -> datetime:
    """When the closed window opens next: today's start if still ahead, else tomorrow's."""
    start = local_time_on(now, period.start)
    if elapsed_seconds(now, start) <= 0:
        return local_time_on(now + timedelta(days=1), period.start)
    return start


def next_window_opening(tariff: TariffConfig, now: datetime) -> WindowOpening | None:
    """The cheapest window open now or next to open, None when the tariff has none.

    The window is the same one `open_cheapest_window` reads: the cheapest timed period, and only
    when it is cheaper than the base rate.
    """
    if not tariff.rate_periods:
        return None
    period = cheapest_period(tariff)
    if period.rate >= tariff.base_rate:
        return None
    is_open = period.is_active(now)
    start = _opening_start(period, now) if is_open else _next_start(period, now)
    end = local_time_on(start, period.end)
    if elapsed_seconds(start, end) <= 0:
        end = local_time_on(start + timedelta(days=1), period.end)
    return WindowOpening(period.name, start, end, is_open)
