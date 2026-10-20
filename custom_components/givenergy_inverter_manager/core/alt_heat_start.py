"""
alt_heat_start.py: when to start the alternative heating so it does the work, not the immersion.

Two pieces of advice, both from the water temperature, the immersion's own heating rate and the
margin the ready-by plan uses:

  * A start time for a ready time. The start is just in time: the ready time less the run the
    water needs to reach the target, so the water is ready when it is wanted and the colder it is
    the earlier the run starts. The immersion plan (immersion_ready.py) is the backstop. It
    places its grid hours as late as possible, so if the alternative was not switched on, the
    immersion still gets the water ready. The alternative is only suggested when a kWh of heat
    from it costs less than the immersion plan pays per kWh (the hours-weighted grid rate of the
    bands it uses, or the export rate when solar surplus is cheaper still).
  * A keep-warm run. When the water has cooled to the lower of the minimum temperature plus the
    restart gap and the target less the restart gap, and the alternative is cheaper than the grid
    now, a short run lifts it to the target, so the water does not fall to where the immersion
    tops it up at the rate in force.

The alternative's heating rate is taken to be the immersion's. That is a conservative assumption:
a boiler coil usually heats faster, so the run is shorter than suggested and the start is early.

Advice only. The integration never switches the alternative system. Pure Python, no Home
Assistant imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..lib.heating import MINUTES_PER_HOUR, RUN_ROUND_MINUTES, WaterReading
from ..lib.heating.ready import place_hours
from .tariff import TariffConfig
from .timeutil import elapsed_seconds, shift_real

# Takes a float rounding error off a whole number of minutes before it is rounded up.
_ROUNDING_SLACK = 1e-6


@dataclass(frozen=True)
class StartQuery:
    """What the start needs. solar_cost is the export rate while surplus is being diverted."""

    tariff: TariffConfig
    now: datetime
    water: WaterReading
    alt_cost_per_kwh: float
    solar_cost: float | None = None
    # When set, the water needs heating as soon as it is this many degrees below the target,
    # instead of at the restart threshold. The ready-by trigger sets it.
    lift_below_target_c: float | None = None
    # True while a trigger that has fired is held: any water below the target still needs the
    # run, however near, so the cost check carries on until the water is warm.
    holding: bool = False


@dataclass(frozen=True)
class AltHeatStart:
    """The run for one ready time. start_by is None when the alternative is not the cheaper heat.

    electric_cost_per_kwh is what the immersion plan costs per kWh of heat, or the export rate
    when by_solar. saving_per_kwh is that less the alternative cost. late is True when it cannot
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


def _start_needed(query: StartQuery) -> bool:
    """Whether the water needs a run for a ready time, by the restart threshold or the margin."""
    water = query.water
    if query.holding:
        return water.temp < water.target and water.hours_to_target > 0
    if query.lift_below_target_c is None:
        return water.needs_heating
    long_enough = water.hours_to_target * MINUTES_PER_HOUR >= RUN_ROUND_MINUTES
    return water.temp <= water.target - query.lift_below_target_c and long_enough


def _whole_minutes(hours: float) -> int:
    return math.ceil(hours * MINUTES_PER_HOUR - _ROUNDING_SLACK)


def _to_the_minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def suggest_alt_heat_start(query: StartQuery, ready_at: datetime) -> AltHeatStart | None:
    """The run for this ready time, None when the water needs no heating (see needs_heating)."""
    if not _start_needed(query):
        return None
    needed = query.water.hours_to_target
    placed = place_hours(query.tariff, query.now, ready_at, needed)
    grid = query.tariff.effective_import_rate(placed.average_rate)
    by_solar = query.solar_cost is not None and query.solar_cost < grid
    electric = query.solar_cost if by_solar else grid
    saving = electric - query.alt_cost_per_kwh
    run_minutes = _whole_minutes(needed)
    if saving <= 0:
        return AltHeatStart(ready_at, electric, by_solar, saving, run_minutes, None, False)
    latest = shift_real(ready_at, -timedelta(minutes=run_minutes))
    late = elapsed_seconds(query.now, latest) < 0
    start = _to_the_minute(query.now if late else latest)
    return AltHeatStart(ready_at, electric, by_solar, saving, run_minutes, start, late)


def round_up_run_minutes(hours: float) -> int:
    """A run of this many hours in minutes, rounded up to a multiple of five, five at least."""
    steps = math.ceil(hours * MINUTES_PER_HOUR / RUN_ROUND_MINUTES - _ROUNDING_SLACK)
    return max(steps, 1) * RUN_ROUND_MINUTES


def keep_warm_minutes(water: WaterReading, grid_cost_now: float, alt_cost: float) -> int | None:
    """Minutes of the alternative to lift cooling water to the target, None when not worth running.

    Rounded up to a multiple of five. The caller leaves solar surplus out: surplus that is
    already heating the water needs no other heat.
    """
    if water.temp > water.keep_warm_below or alt_cost >= grid_cost_now:
        return None
    needed = water.hours_to_target
    if needed <= 0:
        return None
    return round_up_run_minutes(needed)


def low_water_minutes(
    water: WaterReading, grid_cost_now: float, alt_cost: float, margin_c: float
) -> int | None:
    """Minutes of the alternative to lift water that is near the lower boundary, else None.

    Like keep_warm_minutes, but it applies from margin_c degrees above the boundary, so the run
    can start before the immersion would restart. None when the water is further above the
    boundary than that, or when the alternative is not cheaper than the grid now. The caller
    leaves solar surplus out.
    """
    if water.temp > water.keep_warm_below + margin_c or alt_cost >= grid_cost_now:
        return None
    needed = water.hours_to_target
    if needed <= 0:
        return None
    return round_up_run_minutes(needed)

