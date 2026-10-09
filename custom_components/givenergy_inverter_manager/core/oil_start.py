"""
oil_start.py: when to start the oil water heating so the oil does the work, not the immersion.

Two pieces of advice, both from the water temperature, the immersion's own heating rate and the
margin the ready-by plan uses:

  * An oil start time for a ready time. The immersion plan (immersion_ready.py) is the backstop:
    it places its grid hours as late as possible, so it starts when the water would otherwise
    miss the ready time. This module finds that start, and puts the oil run before it. If the
    oil has run, the water is at the target when the immersion would have started and the
    immersion does nothing. If the oil was not switched on, the immersion still gets the water
    ready. Oil is only suggested when a kWh of heat from oil costs less than the immersion plan
    pays per kWh (the hours-weighted grid rate of the bands it uses, or the export rate when
    solar surplus is cheaper still).
  * A keep-warm run. When the water has cooled to the minimum temperature plus the restart gap
    and oil is cheaper than the grid now, a short oil run lifts it to the target, so the water
    does not fall to where the immersion tops it up at the rate in force.

The oil's heating rate is taken to be the immersion's. That is a conservative assumption: an oil
coil usually heats faster, so the oil run is shorter than suggested and the start is early.

Advice only. The integration never switches the oil system. Pure Python, no Home Assistant
imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .immersion_ready import hours_to_heat, place_hours
from .tariff import TariffConfig
from .timeutil import elapsed_seconds, shift_real

_MINUTES_PER_HOUR = 60.0
_KEEP_WARM_ROUND_MINUTES = 5
# Takes a float rounding error off a whole number of minutes before it is rounded up.
_ROUNDING_SLACK = 1e-6


@dataclass(frozen=True)
class WaterReading:
    """The water and the heater the advice reads, in degrees and degrees an hour."""

    temp: float
    target: float
    rate_c_per_h: float
    min_temp: float
    restart_gap_c: float

    @property
    def at_target(self) -> bool:
        return self.temp >= self.target

    @property
    def hours_to_target(self) -> float:
        """Heating hours to the target, with the plan's margin. Zero when there is no heating."""
        return hours_to_heat(self.temp, self.target, self.rate_c_per_h)

    @property
    def keep_warm_below(self) -> float:
        return self.min_temp + self.restart_gap_c


@dataclass(frozen=True)
class StartQuery:
    """What the oil start needs. solar_cost is the export rate while surplus is being diverted."""

    tariff: TariffConfig
    now: datetime
    water: WaterReading
    oil_cost_per_kwh: float
    solar_cost: float | None = None


@dataclass(frozen=True)
class OilStart:
    """The oil run for one ready time. start_by is None when oil is not the cheaper heat.

    electric_cost_per_kwh is what the immersion plan costs per kWh of heat, or the export rate
    when by_solar. saving_per_kwh is that less the oil cost. late is True when the oil cannot
    finish before the immersion has to start, so the start is now and the immersion will share
    the heating.
    """

    ready_at: datetime
    electric_cost_per_kwh: float
    by_solar: bool
    saving_per_kwh: float
    run_minutes: int
    start_by: datetime | None
    late: bool


def _whole_minutes(hours: float) -> int:
    return math.ceil(hours * _MINUTES_PER_HOUR - _ROUNDING_SLACK)


def _to_the_minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def suggest_oil_start(query: StartQuery, ready_at: datetime) -> OilStart | None:
    """The oil run for this ready time, None when the water is already at the target."""
    needed = query.water.hours_to_target
    if needed <= 0:
        return None
    placed = place_hours(query.tariff, query.now, ready_at, needed)
    grid = query.tariff.effective_import_rate(placed.average_rate)
    by_solar = query.solar_cost is not None and query.solar_cost < grid
    electric = query.solar_cost if by_solar else grid
    saving = electric - query.oil_cost_per_kwh
    run_minutes = _whole_minutes(needed)
    if saving <= 0:
        return OilStart(ready_at, electric, by_solar, saving, run_minutes, None, False)
    latest = shift_real(placed.starts_at, -timedelta(minutes=run_minutes))
    late = elapsed_seconds(query.now, latest) < 0
    start = _to_the_minute(query.now if late else latest)
    return OilStart(ready_at, electric, by_solar, saving, run_minutes, start, late)


def keep_warm_minutes(water: WaterReading, grid_cost_now: float, oil_cost: float) -> int | None:
    """Minutes of oil to lift cooling water to the target, None when it is not worth running.

    Rounded up to a multiple of five. The caller leaves solar surplus out: surplus that is
    already heating the water needs no oil.
    """
    if water.temp > water.keep_warm_below or oil_cost >= grid_cost_now:
        return None
    needed = water.hours_to_target
    if needed <= 0:
        return None
    steps = math.ceil(needed * _MINUTES_PER_HOUR / _KEEP_WARM_ROUND_MINUTES - _ROUNDING_SLACK)
    return max(steps, 1) * _KEEP_WARM_ROUND_MINUTES
