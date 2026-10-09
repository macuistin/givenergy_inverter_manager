"""
solar_day.py — Settle whether the solar day has started.

The night window depends on whether solar is generating (see hours_until_solar): about 8 hours
while it is, the whole run to tomorrow's sunrise while it is not. At dawn and dusk the reading
wanders across SOLAR_NOISE_FLOOR_W every few cycles, and each crossing flipped the window and
with it the Night Survival Status, its reason and the Confidence sensor.

The day starts once the reading has stayed at or above the floor for SOLAR_DAY_DEBOUNCE_MINUTES,
and ends once it has stayed below it for as long. A reading that crosses back restarts the count.
Only the solar state is settled. The SoC, the load and the shortfall are read fresh every cycle,
so a real shortfall shows at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..const import SOLAR_DAY_DEBOUNCE_MINUTES, SOLAR_NOISE_FLOOR_W
from .sunrise_hold import STALE_AFTER_S
from .timeutil import elapsed_seconds


@dataclass
class HeldSolarDay:
    """Whether solar counts as generating, and since when the readings have disagreed."""

    generating: bool | None = None
    disagreed_since: datetime | None = None
    seen_at: datetime | None = None


@dataclass(frozen=True)
class SolarReading:
    """The raw solar power this cycle and when it was read."""

    power_w: float
    now: datetime


def _is_stale(held: HeldSolarDay, reading: SolarReading) -> bool:
    """True before the first reading, after a restart or gap, and when the clock stands still."""
    if held.generating is None or held.seen_at is None:
        return True
    elapsed_s = elapsed_seconds(held.seen_at, reading.now)
    return elapsed_s <= 0 or elapsed_s > STALE_AFTER_S


def _debounced(held: HeldSolarDay, reading: SolarReading) -> bool:
    raw_generating = reading.power_w >= SOLAR_NOISE_FLOOR_W
    if _is_stale(held, reading):
        held.generating, held.disagreed_since = raw_generating, None
    elif raw_generating == held.generating:
        held.disagreed_since = None
    elif held.disagreed_since is None:
        held.disagreed_since = reading.now
    elif elapsed_seconds(held.disagreed_since, reading.now) >= SOLAR_DAY_DEBOUNCE_MINUTES * 60:
        held.generating, held.disagreed_since = raw_generating, None
    held.seen_at = reading.now
    return bool(held.generating)


def settled_solar_w(held: HeldSolarDay, reading: SolarReading) -> float:
    """The solar power the night window should see. Mutates held.

    While the day counts as started that is the reading, never below the noise floor so a dip
    inside the debounce does not read as no solar. Otherwise it is zero.
    """
    if not _debounced(held, reading):
        return 0.0
    return max(reading.power_w, SOLAR_NOISE_FLOOR_W)
