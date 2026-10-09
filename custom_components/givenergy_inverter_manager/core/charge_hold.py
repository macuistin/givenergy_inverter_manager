"""
charge_hold.py — Steady the published charge recommendation.

The overnight charge target is recalculated every cycle and, in the small hours, moves by
several points as the load estimate settles. The sensors publish a held copy that only
changes once the fresh target is a clear step away, so the history stays readable and the
reason text does not churn. A step of CHARGE_TARGET_HOLD_STEP_PCT is published once the held
value has stood for CHARGE_TARGET_HOLD_MIN_MINUTES, and a step of
CHARGE_TARGET_HOLD_LARGE_STEP_PCT at once.

A change between charging and skipping is measured by the charge it adds or removes: skipping
and charging a few points are the same night. A skip is never published while a charge is
running, because the charge itself lifts the SoC over the skip threshold.

The charge written to the inverter always comes from the fresh decision, never from the held
copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..const import (
    CHARGE_TARGET_HOLD_LARGE_STEP_PCT,
    CHARGE_TARGET_HOLD_MIN_MINUTES,
    CHARGE_TARGET_HOLD_STEP_PCT,
)
from .rules import ChargeDecision
from .timeutil import elapsed_seconds


@dataclass(frozen=True)
class HoldReading:
    """What the hold needs to know about this cycle besides the fresh decision."""

    now: datetime
    charge_running: bool = False


@dataclass
class HeldCharge:
    """The recommendation currently published and when it was. Mutated by the engine."""

    decision: ChargeDecision | None = None
    published_at: datetime | None = None

    def settle(self, fresh: ChargeDecision, reading: HoldReading) -> None:
        """Publish the fresh decision or keep the held one, and note when it changed."""
        published = next_held_recommendation(self, fresh, reading)
        if published is not self.decision:
            self.published_at = reading.now
        self.decision = published


def _has_stood_long_enough(held: HeldCharge, reading: HoldReading) -> bool:
    if held.published_at is None:
        return True
    elapsed_s = elapsed_seconds(held.published_at, reading.now)
    return elapsed_s < 0 or elapsed_s >= CHARGE_TARGET_HOLD_MIN_MINUTES * 60


def _plan_change_pct(held: ChargeDecision, fresh: ChargeDecision) -> int:
    """SoC points the fresh plan differs from the held one by.

    A change between charging and skipping counts the charge that one plan adds over the
    other, measured from the SoC now. A charge target at or below the SoC adds nothing.
    """
    if held.skip_charge == fresh.skip_charge:
        return abs(fresh.target_soc - held.target_soc)
    charging = held if fresh.skip_charge else fresh
    return max(0, charging.target_soc - round(fresh.current_soc))


def _skip_during_charge(held: ChargeDecision, fresh: ChargeDecision, reading: HoldReading) -> bool:
    return reading.charge_running and fresh.skip_charge and not held.skip_charge


def next_held_recommendation(
    held: HeldCharge, fresh: ChargeDecision, reading: HoldReading
) -> ChargeDecision:
    """Keep the held decision until the fresh one differs by a clear step."""
    if held.decision is None:
        return fresh
    if _skip_during_charge(held.decision, fresh, reading):
        return held.decision
    step_pct = _plan_change_pct(held.decision, fresh)
    if step_pct >= CHARGE_TARGET_HOLD_LARGE_STEP_PCT:
        return fresh
    if step_pct >= CHARGE_TARGET_HOLD_STEP_PCT and _has_stood_long_enough(held, reading):
        return fresh
    return held.decision
