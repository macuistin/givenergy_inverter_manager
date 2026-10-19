"""
immersion_rate.py: how fast the heater warms the water, learned from its own runs.

The ready-by planner needs degrees per hour. Nothing is configured for it, so the integration
measures it. A run is a stretch of cycles with the heater on and the temperature readable. When
it ends, the rise over its length is one sample. The last few samples are kept (the storage
holds them) and their median is the rate. Until a run has been measured, the rate is assumed
from the element power and a large cylinder, which heats slowly, so the first plans start early.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime

from ..timeutil import elapsed_seconds
from .defaults import (
    IMMERSION_ASSUMED_TANK_LITRES,
    IMMERSION_RATE_DAYS_KEPT,
    IMMERSION_RATE_RUN_MIN_MINUTES,
    IMMERSION_RATE_RUN_MIN_RISE_C,
    IMMERSION_RATE_RUNS_KEPT,
    SENSOR_OUTAGE_HOLD_LIMIT_S,
)

# Heating one litre of water by one degree takes 4.186 kJ, and one kWh is 3600 kJ.
_KWH_PER_LITRE_DEGREE = 4.186 / 3600
_SECONDS_PER_HOUR = 3600.0

SOURCE_LEARNED = "learned"
SOURCE_ASSUMED = "assumed"


def assumed_rate_c_per_h(power_w: float) -> float:
    """Degrees per hour of an element of this power in a cylinder of the assumed size."""
    if power_w <= 0:
        return 0.0
    return power_w / 1000 / (IMMERSION_ASSUMED_TANK_LITRES * _KWH_PER_LITRE_DEGREE)


def resolve_rate(
    learned: list[float], power_w: float, days: list[dict] | None = None
) -> tuple[float, str]:
    """The rate to plan with and where it came from.

    The average of the daily rates when there are any. An install from before the daily rates
    has the median of its last runs until the first dated run is recorded. Without either, the
    rate is assumed from the element.
    """
    daily = day_rates(days or [])
    if daily:
        return statistics.fmean(daily), SOURCE_LEARNED
    if learned:
        return statistics.median(learned), SOURCE_LEARNED
    return assumed_rate_c_per_h(power_w), SOURCE_ASSUMED


def day_rates(days: list[dict]) -> list[float]:
    """The rate of each stored day: the average of that day's runs, in degrees per hour."""
    return [d["total"] / d["runs"] for d in days if d.get("runs") and d.get("total", 0) > 0]


def keep_day_rate(days: list[dict], day: date, rate_c_per_h: float) -> list[dict]:
    """The days with one more run on *day*, the oldest dropped past IMMERSION_RATE_DAYS_KEPT.

    Each day holds the sum of its runs' rates and how many runs there were, so a day's rate is
    their average. Days are kept oldest first.
    """
    stamp = day.isoformat()
    kept = [dict(d) for d in days if d.get("date") != stamp]
    existing = next((d for d in days if d.get("date") == stamp), {"total": 0.0, "runs": 0})
    kept.append(
        {"date": stamp, "total": existing["total"] + rate_c_per_h, "runs": existing["runs"] + 1}
    )
    return sorted(kept, key=lambda d: d["date"])[-IMMERSION_RATE_DAYS_KEPT:]


def keep_run(learned: list[float], rate: float) -> list[float]:
    """The learned rates with one more, oldest dropped past IMMERSION_RATE_RUNS_KEPT."""
    return [*learned, rate][-IMMERSION_RATE_RUNS_KEPT:]


@dataclass
class RunTracker:
    """Follows heater-on stretches across cycles and reports the rate of each finished run."""

    started_at: datetime | None = None
    started_temp: float = 0.0
    last_at: datetime | None = None
    last_temp: float = 0.0

    def observe(self, now: datetime, temp_while_on: float | None) -> float | None:
        """Take one cycle. Pass the temperature when the heater is on and it can be read, else None.

        Returns the rate in degrees per hour when a run just ended.
        """
        if temp_while_on is not None:
            return self._continue_or_start(now, temp_while_on)
        return self._end()

    def _continue_or_start(self, now: datetime, temp: float) -> float | None:
        if self.last_at is not None and self._gap_too_long(now):
            finished = self._end()
            self._start(now, temp)
            return finished
        if self.started_at is None:
            self._start(now, temp)
        else:
            self.last_at, self.last_temp = now, temp
        return None

    def _gap_too_long(self, now: datetime) -> bool:
        return elapsed_seconds(self.last_at, now) > SENSOR_OUTAGE_HOLD_LIMIT_S

    def _start(self, now: datetime, temp: float) -> None:
        self.started_at = self.last_at = now
        self.started_temp = self.last_temp = temp

    def _end(self) -> float | None:
        if self.started_at is None or self.last_at is None:
            return None
        hours = elapsed_seconds(self.started_at, self.last_at) / _SECONDS_PER_HOUR
        rise = self.last_temp - self.started_temp
        self.started_at = self.last_at = None
        if hours * 60 < IMMERSION_RATE_RUN_MIN_MINUTES or rise < IMMERSION_RATE_RUN_MIN_RISE_C:
            return None
        return rise / hours
