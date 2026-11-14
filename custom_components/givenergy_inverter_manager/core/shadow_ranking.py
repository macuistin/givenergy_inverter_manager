"""
shadow_ranking.py - the live ranking of the plans in the store against the current tariff.

`lib/tariffranking` prices every plan over measured usage and ranks them. This module turns that
result into what a sensor and the dashboard show: where the current plan stands, the cheapest few,
and what the cheapest would have saved. It is a re-pricing of past usage, never a forecast, and it
never changes the active tariff.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ..lib.tariffranking import TOP, Ranked, SearchResult, Unit, Window, rank_sentence

CURRENT = "current"
YOUR_PLAN = "Your plan"
LISTED = 5  # plans named in the ranking, as well as the current one
WINDOW = Window(Unit.BILLS, 1)  # the last whole bill


@dataclass(frozen=True)
class RankedPlan:
    rank: int
    name: str
    bill: float
    yours: bool


@dataclass(frozen=True)
class PlanRanking:
    """What the ranking shows."""

    current_rank: int
    compared: int
    plans: tuple[RankedPlan, ...]  # the cheapest few, and the current plan wherever it stands
    cheapest: str  # the name of the cheapest plan, "" when the current plan is it
    saving: float  # the current bill less the cheapest plan's, never negative
    sentence: str
    first_day: date
    last_day: date
    days: int
    days_recorded: int
    left_out: int  # plans that could not be priced
    assumed_export: int  # priced with your own export rate because the plan lists none


def _plan(ranked: Ranked) -> RankedPlan:
    yours = ranked.key == CURRENT
    return RankedPlan(ranked.rank, YOUR_PLAN if yours else ranked.label, ranked.total, yours)


def _sentence(result: SearchResult, cheapest: Ranked, saving: float) -> str:
    """Where your plan stands, then which plan the last bill would have been cheapest on."""
    standing = rank_sentence(result)
    if cheapest.key == CURRENT:
        return standing
    best = f"The last bill would have been cheapest on {cheapest.label}, {saving:.2f} less."
    return f"{standing} {best}"


def summarise(result: SearchResult, left_out: int, assumed_export: int) -> PlanRanking:
    """The ranking as shown: the best `LISTED` plans and the current one, with its standing."""
    chosen = [r for r in result.ranked if r.rank <= LISTED or r.key == CURRENT]
    cheapest = result.ranked[0]
    yours = result.ranked[result.current_rank - 1]
    saving = round(max(yours.total - cheapest.total, 0.0), 2)
    return PlanRanking(
        current_rank=result.current_rank,
        compared=result.compared,
        plans=tuple(_plan(r) for r in chosen),
        cheapest="" if cheapest.key == CURRENT else cheapest.label,
        saving=saving,
        sentence=_sentence(result, cheapest, saving),
        first_day=result.first_day,
        last_day=result.last_day,
        days=result.days,
        days_recorded=result.days_recorded,
        left_out=left_out,
        assumed_export=assumed_export,
    )


def attributes(ranking: PlanRanking) -> dict[str, Any]:
    """The state attributes of the rank sensor."""
    return {
        "summary": ranking.sentence,
        "plans_compared": ranking.compared,
        "in_top": ranking.current_rank <= TOP,
        "cheapest_plan": ranking.cheapest or None,
        "saving_with_cheapest": ranking.saving,
        "window_start": ranking.first_day.isoformat(),
        "window_end": ranking.last_day.isoformat(),
        "days_priced": ranking.days,
        "days_with_data": ranking.days_recorded,
        "plans_left_out": ranking.left_out,
        "plans_using_your_export_rate": ranking.assumed_export,
        "ranking": [
            {"rank": p.rank, "name": p.name, "bill": round(p.bill, 2), "yours": p.yours}
            for p in ranking.plans
        ],
    }
