"""
immersion_solar.py: the part of the day the ready-by plan leaves to the sun.

Heating for a ready time normally goes to the cheapest rate band left. Grid power in a cheap band
is still dearer than free solar, so when enough solar is forecast for the rest of today the plan
treats the solar hours as free and waits for them. The immersion's own surplus rule then does the
heating. The plan is recomputed every cycle, so a day that fades shrinks the solar still to come
and the plan falls back to the cheapest grid band, with the Day rate as the last resort.

Solar still to come is today's forecast times the share of the solar day left, from
SOLAR_SUNRISE_HOUR to the time solar is expected to stop. It must cover the heater's energy
IMMERSION_SOLAR_COVER_FACTOR times, because the house and the battery use some of it first.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from ..const import IMMERSION_SOLAR_COVER_FACTOR, SOLAR_SUNRISE_HOUR
from .timeutil import elapsed_seconds, local_time_on

SOLAR_BAND = "expected solar"


@dataclass(frozen=True)
class SolarOutlook:
    """Today's solar forecast: its energy, and the minute of the day solar is expected to stop."""

    forecast_kwh: float
    end_minute: float
    heater_w: float


def _minute_time(minute: float) -> time:
    whole = int(minute)
    return time(whole // 60 % 24, whole % 60)


def solar_window(
    outlook: SolarOutlook | None, now: datetime, ready: datetime, hours_needed: float
) -> tuple[datetime, datetime] | None:
    """The stretch of today the sun is expected to heat the water in, or None.

    It runs from sunrise, or now if later, to the time solar stops or the ready time, whichever
    comes first. None when there is no forecast, the sun has set, or the solar still to come
    does not cover the heating.
    """
    if outlook is None or outlook.forecast_kwh <= 0 or hours_needed <= 0:
        return None
    sunrise = local_time_on(now, time(SOLAR_SUNRISE_HOUR))
    sunset = local_time_on(now, _minute_time(outlook.end_minute))
    start, end = max(now, sunrise), min(ready, sunset)
    if elapsed_seconds(start, end) <= 0:
        return None
    day_minutes = max(elapsed_seconds(sunrise, sunset) / 60, 1.0)
    left = elapsed_seconds(max(now, sunrise), sunset) / 60
    ahead_kwh = outlook.forecast_kwh * min(1.0, left / day_minutes)
    needed_kwh = hours_needed * outlook.heater_w / 1000
    if ahead_kwh < needed_kwh * IMMERSION_SOLAR_COVER_FACTOR:
        return None
    return start, end
