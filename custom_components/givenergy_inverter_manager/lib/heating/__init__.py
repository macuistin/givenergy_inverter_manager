"""Hot-water heating planner: the run a heater needs to be ready on time, and where to place it."""

from .defaults import (
    CHARGE_WINDOW_MARGIN,
    IMMERSION_ASSUMED_TANK_LITRES,
    IMMERSION_RATE_DAYS_KEPT,
    IMMERSION_RATE_RUN_MIN_MINUTES,
    IMMERSION_RATE_RUN_MIN_RISE_C,
    IMMERSION_RATE_RUNS_KEPT,
    IMMERSION_SWITCH_COOLDOWN_MINUTES,
    SENSOR_OUTAGE_HOLD_LIMIT_S,
)
from .planned import (
    PlanQuery,
    describe_planned_heating,
)
from .rate import (
    SOURCE_ASSUMED,
    SOURCE_LEARNED,
    RunTracker,
    assumed_rate_c_per_h,
    day_rates,
    keep_day_rate,
    keep_run,
    resolve_rate,
)
from .ready import (
    HeatingSpan,
    Placement,
    RateSegment,
    ReadyInputs,
    ReadyPlan,
    hours_to_heat,
    next_ready_at,
    parse_ready_times,
    place_hours,
    plan_ready,
    rate_segments,
)
from .water import (
    MINUTES_PER_HOUR,
    RUN_ROUND_MINUTES,
    WaterReading,
)
from .window import (
    WindowOpening,
    next_window_opening,
    open_cheapest_window,
)

__all__ = [
    "CHARGE_WINDOW_MARGIN",
    "HeatingSpan",
    "IMMERSION_ASSUMED_TANK_LITRES",
    "IMMERSION_RATE_DAYS_KEPT",
    "IMMERSION_RATE_RUNS_KEPT",
    "IMMERSION_RATE_RUN_MIN_MINUTES",
    "IMMERSION_RATE_RUN_MIN_RISE_C",
    "IMMERSION_SWITCH_COOLDOWN_MINUTES",
    "MINUTES_PER_HOUR",
    "Placement",
    "PlanQuery",
    "RUN_ROUND_MINUTES",
    "RateSegment",
    "ReadyInputs",
    "ReadyPlan",
    "RunTracker",
    "SENSOR_OUTAGE_HOLD_LIMIT_S",
    "SOURCE_ASSUMED",
    "SOURCE_LEARNED",
    "WaterReading",
    "WindowOpening",
    "assumed_rate_c_per_h",
    "day_rates",
    "describe_planned_heating",
    "hours_to_heat",
    "keep_day_rate",
    "keep_run",
    "next_ready_at",
    "next_window_opening",
    "open_cheapest_window",
    "parse_ready_times",
    "place_hours",
    "plan_ready",
    "rate_segments",
    "resolve_rate",
]
