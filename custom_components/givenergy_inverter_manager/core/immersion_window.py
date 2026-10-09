"""
immersion_window.py: the cheapest rate window the immersion heats in.

The window is the cheapest timed rate period, the one the battery charge also starts in. It
counts only when its rate is below the base rate, so a tariff whose only timed period is
dearer than the base rate has no window. Whether to heat in it, and until when, is decided
by `rules.should_divert_to_immersion`.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from datetime import datetime

from .charge_window import cheapest_period
from .tariff import TariffConfig


def open_cheapest_window(tariff: TariffConfig, now: datetime) -> str | None:
    """Name and hours of the cheapest period when it is cheaper than the base rate and open now."""
    if not tariff.rate_periods:
        return None
    period = cheapest_period(tariff)
    if period.rate >= tariff.base_rate or not period.is_active(now):
        return None
    return f"{period.name} {period.start:%H:%M} to {period.end:%H:%M}"
