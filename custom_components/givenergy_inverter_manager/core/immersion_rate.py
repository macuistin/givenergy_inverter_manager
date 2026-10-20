"""Re-export of lib/heating so existing imports keep working. Import from lib/ in new code."""

from ..lib.heating.rate import (
    SOURCE_ASSUMED,
    SOURCE_LEARNED,
    RunTracker,
    assumed_rate_c_per_h,
    day_rates,
    keep_day_rate,
    keep_run,
    resolve_rate,
)

__all__ = [
    "RunTracker",
    "SOURCE_ASSUMED",
    "SOURCE_LEARNED",
    "assumed_rate_c_per_h",
    "day_rates",
    "keep_day_rate",
    "keep_run",
    "resolve_rate",
]
