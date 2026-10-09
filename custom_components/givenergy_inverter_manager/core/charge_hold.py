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

The published charge window end holds the same way, in minutes: a step of
CHARGE_WINDOW_HOLD_STEP_MINUTES once the held end has stood for the same time, and a step of
CHARGE_WINDOW_HOLD_LARGE_STEP_MINUTES at once. It stays put while a charge runs, so it matches
what was written when the charge began.

The charge and the window written to the inverter always come from the fresh decision, never
from the held copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..const import (
    CHARGE_TARGET_HOLD_LARGE_STEP_PCT,
    CHARGE_TARGET_HOLD_MIN_MINUTES,
    CHARGE_TARGET_HOLD_STEP_PCT,
    CHARGE_WINDOW_HOLD_LARGE_STEP_MINUTES,
    CHARGE_WINDOW_HOLD_STEP_MINUTES,
)
from .charge_window import ChargeWindow
from .rules import ChargeDecision
from .timeutil import elapsed_seconds

_MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True)
class HoldReading:
    """What the hold needs to know about this cycle besides the fresh decision."""

    now: datetime
    charge_running: bool = False
    # The configured cap on the target. The sensors show the capped target, so a step above it
    # is not a step the reader sees.
    max_target_pct: int = 100


@dataclass
class HeldCharge:
    """The recommendation and window currently published, and when. Mutated by the engine."""

    decision: ChargeDecision | None = None
    published_at: datetime | None = None
    window: ChargeWindow | None = None
    window_published_at: datetime | None = None

    def settle(self, fresh: ChargeDecision, reading: HoldReading) -> None:
        """Publish the fresh decision or keep the held one, and note when it changed."""
        published = next_held_recommendation(self, fresh, reading)
        if published is not self.decision:
            self.published_at = reading.now
        self.decision = published

    def settle_window(self, fresh: ChargeWindow | None, reading: HoldReading) -> None:
        """Publish the planned window or keep the held one, and note when it changed."""
        published = next_held_window(self, fresh, reading)
        if published is not self.window:
            self.window_published_at = reading.now
        self.window = published

    def release(self) -> None:
        """Drop what is held, so the next cycle publishes the fresh decision and window."""
        self.decision = self.published_at = self.window = self.window_published_at = None


def _has_stood_long_enough(published_at: datetime | None, reading: HoldReading) -> bool:
    if published_at is None:
        return True
    elapsed_s = elapsed_seconds(published_at, reading.now)
    return elapsed_s < 0 or elapsed_s >= CHARGE_TARGET_HOLD_MIN_MINUTES * 60


def _shown_target(decision: ChargeDecision, reading: HoldReading) -> int:
    """The target as published: a charge is capped, a skip is not."""
    if decision.skip_charge:
        return decision.target_soc
    return min(decision.target_soc, reading.max_target_pct)


def _plan_change_pct(held: ChargeDecision, fresh: ChargeDecision, reading: HoldReading) -> int:
    """SoC points the fresh plan differs from the held one by, as the sensors would show it.

    A change between charging and skipping counts the charge that one plan adds over the
    other, measured from the SoC now. A charge target at or below the SoC adds nothing.
    """
    if held.skip_charge == fresh.skip_charge:
        return abs(_shown_target(fresh, reading) - _shown_target(held, reading))
    charging = held if fresh.skip_charge else fresh
    return max(0, _shown_target(charging, reading) - round(fresh.current_soc))


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
    step_pct = _plan_change_pct(held.decision, fresh, reading)
    if step_pct >= CHARGE_TARGET_HOLD_LARGE_STEP_PCT:
        return fresh
    if step_pct >= CHARGE_TARGET_HOLD_STEP_PCT and _has_stood_long_enough(
        held.published_at, reading
    ):
        return fresh
    return held.decision


def _end_minute(window: ChargeWindow) -> int:
    return window.end.hour * 60 + window.end.minute


def _end_distance_minutes(held: ChargeWindow, fresh: ChargeWindow) -> int:
    """Minutes between two window ends on the clock, the short way round midnight."""
    gap = abs(_end_minute(fresh) - _end_minute(held))
    return min(gap, _MINUTES_PER_DAY - gap)


def next_held_window(
    held: HeldCharge, fresh: ChargeWindow | None, reading: HoldReading
) -> ChargeWindow | None:
    """Keep the held window until the planned end is a clear step away."""
    if fresh is None:
        return None
    if held.window is None or held.window.start != fresh.start:
        return fresh
    if reading.charge_running:
        return held.window
    distance = _end_distance_minutes(held.window, fresh)
    if distance >= CHARGE_WINDOW_HOLD_LARGE_STEP_MINUTES:
        return fresh
    if distance >= CHARGE_WINDOW_HOLD_STEP_MINUTES and _has_stood_long_enough(
        held.window_published_at, reading
    ):
        return fresh
    return held.window
