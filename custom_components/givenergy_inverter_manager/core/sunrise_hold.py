"""
sunrise_hold.py — Keep the published estimate of the SoC at sunrise continuous.

The estimate is the current SoC less the load until solar starts. The load and the window
both change in steps a battery cannot follow: the day's energy total resets at midnight, the
window flips from this morning to tonight at sunrise and from tonight's pre-solar hours to the
whole evening when solar fades. Each step moved the sensor by 15 points or more in one cycle.

The battery cannot move faster than the inverter can charge or discharge it, so neither can an
honest estimate of its charge. The published value follows the calculated one at no more than
that rate, and a step becomes a ramp of about half an hour. The Night Survival Status and
Confidence sensors still read the calculated figure, so a real shortfall is reported at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .timeutil import elapsed_seconds

# A gap this long means a restart or an outage. The held value is stale, so start again.
_STALE_AFTER_S = 3600.0


@dataclass
class HeldSunrise:
    """The estimate currently published and when it was published. Mutated by the engine."""

    soc: float | None = None
    at: datetime | None = None


@dataclass(frozen=True)
class SunriseReading:
    """This cycle's calculated estimate, when it was made and how fast the battery can move."""

    soc: float
    now: datetime
    max_change_pct_per_hour: float


def max_battery_swing_pct_per_hour(inverter_max_w: float, capacity_kwh: float) -> float:
    """SoC points per hour at the inverter's full charge or discharge power, 0 if unknown."""
    if inverter_max_w <= 0 or capacity_kwh <= 0:
        return 0.0
    return inverter_max_w / 1000 / capacity_kwh * 100


def published_sunrise_soc(held: HeldSunrise, reading: SunriseReading) -> float:
    """The estimate to publish: the calculated one, moved no faster than the battery can.

    The first reading, a reading after a long gap and a reading with no known battery rate
    publish the calculated value as it is.
    """
    if held.soc is None or held.at is None or reading.max_change_pct_per_hour <= 0:
        return reading.soc
    elapsed_s = elapsed_seconds(held.at, reading.now)
    if elapsed_s <= 0 or elapsed_s > _STALE_AFTER_S:
        return reading.soc
    allowed_pct = reading.max_change_pct_per_hour * elapsed_s / 3600
    return held.soc + max(-allowed_pct, min(allowed_pct, reading.soc - held.soc))
