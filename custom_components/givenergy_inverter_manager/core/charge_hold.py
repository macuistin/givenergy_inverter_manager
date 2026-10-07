"""
charge_hold.py — Steady the published charge recommendation.

The overnight charge target is recalculated every cycle and, in the small hours, moves by
several points as the load estimate settles. The sensors publish a held copy that only
changes once the fresh target is a clear step away, so the history stays readable and the
reason text does not churn. The charge written to the inverter always comes from the fresh
decision, never from the held copy.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..const import CHARGE_TARGET_HOLD_STEP_PCT
from .rules import ChargeDecision


@dataclass
class HeldCharge:
    """The recommendation currently published. Mutated in place by the engine each cycle."""

    decision: ChargeDecision | None = None


def next_held_recommendation(
    held: ChargeDecision | None,
    fresh: ChargeDecision,
    step_pct: int = CHARGE_TARGET_HOLD_STEP_PCT,
) -> ChargeDecision:
    """Keep the held decision until the fresh one differs by a clear step or changes kind."""
    if held is None:
        return fresh
    if held.skip_charge != fresh.skip_charge:
        return fresh
    if abs(fresh.target_soc - held.target_soc) >= step_pct:
        return fresh
    return held
