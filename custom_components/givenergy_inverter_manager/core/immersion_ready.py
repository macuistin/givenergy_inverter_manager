"""Re-export of lib/heating so existing imports keep working. Import from lib/ in new code."""

from ..lib.heating.ready import (
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

__all__ = [
    "HeatingSpan",
    "Placement",
    "RateSegment",
    "ReadyInputs",
    "ReadyPlan",
    "hours_to_heat",
    "next_ready_at",
    "parse_ready_times",
    "place_hours",
    "plan_ready",
    "rate_segments",
]
