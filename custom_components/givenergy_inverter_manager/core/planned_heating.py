"""Re-export of lib/heating so existing imports keep working. Import from lib/ in new code."""

from ..lib.heating.planned import (
    PlanQuery,
    describe_planned_heating,
)

__all__ = [
    "PlanQuery",
    "describe_planned_heating",
]
