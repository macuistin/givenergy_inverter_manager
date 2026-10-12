"""
replan.py: whether to correct tonight's charge target while the cheap window is open.

The target is written once, a minute before the cheapest rate starts. The forecast, the load or
a car plugged in can change after that, so the plan is worked out again inside the window and a
new target is written when it moved far enough. Three things start a check:

  1. The late check: once, at the later of 30 minutes after the first write and an hour before
     the window ends.
  2. The forecast: the figure the plan uses differs from the one used for the last write by at
     least 15% and at least 1 kWh.
  3. The car: it was plugged in or unplugged since the last write, which moves the target.

A check writes only when the new target differs from the last written one by 5 points or more,
at most 3 times a night, never outside the window and never with a manual override on. A
skipped night is not turned into a charge-free one while a charge is running: the charge itself
lifts the battery over the skip threshold.

Nothing here reads the clock or the inverter. Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..const import (
    REPLAN_FORECAST_CHANGE_MIN_KWH,
    REPLAN_FORECAST_CHANGE_PCT,
    REPLAN_LATE_CHECK_AFTER_MIN,
    REPLAN_LATE_CHECK_BEFORE_END_MIN,
    REPLAN_MAX_WRITES,
    REPLAN_MIN_CHANGE_PTS,
    REPLAN_MIN_REMAINING_MIN,
)
from .charge_retry import WriteWindow
from .tariff import RatePeriod
from .write_log import REPLAN_REASON

_ONE_MINUTE = timedelta(minutes=1)

TRIGGER_EV = "ev"
TRIGGER_FORECAST = "forecast"
TRIGGER_LATE = "late"


@dataclass(frozen=True)
class PlanBasis:
    """What a charge write was based on: the figures a later check compares against."""

    forecast_kwh: float | None
    ev_plugged: bool
    skipped: bool
    # The forecast for the day after the one charged for. Before sunrise the plan's own figure is
    # the one remembered at midnight, so this is the live reading that moves the target.
    next_day_kwh: float | None = None


@dataclass(frozen=True)
class PlannedWrite:
    """One charge write about to be sent: the target, the window period and what it rests on."""

    target: int
    period: RatePeriod
    basis: PlanBasis


@dataclass
class NightState:
    """Tonight's written plan. The coordinator keeps one from the first write until the next.

    *period* is the cheap period as it was written, so a re-plan sends the same window and
    never opens a new one.
    """

    window: WriteWindow
    period: RatePeriod
    target: int
    basis: PlanBasis
    replans: int = 0
    late_check_done: bool = False

    def wrote(self, target: int, basis: PlanBasis, *, replan: bool) -> None:
        """Note a write that took, so the next check compares against it."""
        self.target = target
        self.basis = basis
        if replan:
            self.replans += 1


@dataclass(frozen=True)
class ReplanInputs:
    """Everything one check needs. The coordinator gathers it, this module decides."""

    now: datetime
    window: WriteWindow
    last_target: int
    last_basis: PlanBasis
    new_target: int
    new_basis: PlanBasis
    replans_so_far: int
    override_active: bool
    late_check_done: bool


@dataclass(frozen=True)
class ReplanDecision:
    """Whether to write, which target, and why in a few words ('the forecast fell by 20%')."""

    write: bool
    target: int
    reason: str
    trigger: str | None = None
    # True when the late check came due on this call. It is a one-off, so the coordinator
    # records it as done whether or not a write followed.
    late_check_ran: bool = False


@dataclass(frozen=True)
class ReplanStep:
    """A check that decided to write: tonight's state, the decision, what it rests on, and when."""

    night: NightState
    result: ReplanDecision
    basis: PlanBasis
    at: datetime


def window_start(window: WriteWindow) -> datetime:
    """When the cheap window opens: the trigger fires a minute before it."""
    return window.trigger + _ONE_MINUTE


def late_check_at(window: WriteWindow) -> datetime:
    """The later of 30 minutes after the first write and an hour before the window ends."""
    after_write = window.trigger + timedelta(minutes=REPLAN_LATE_CHECK_AFTER_MIN)
    before_end = window.end - timedelta(minutes=REPLAN_LATE_CHECK_BEFORE_END_MIN)
    return max(after_write, before_end)


def decide_replan(inputs: ReplanInputs) -> ReplanDecision:
    """Decide whether to write a new target now."""
    blocked = _blocked(inputs)
    late_due = not inputs.late_check_done and inputs.now >= late_check_at(inputs.window)
    if blocked:
        return _hold(inputs, blocked)
    trigger, cause = _trigger(inputs, late_due)
    if trigger is None:
        return _hold(inputs, "nothing has changed")
    if inputs.new_basis.skipped and not inputs.last_basis.skipped:
        return _hold(inputs, "a skip is not taken while a charge is written", late_due)
    change = abs(inputs.new_target - inputs.last_target)
    if change < REPLAN_MIN_CHANGE_PTS:
        return _hold(inputs, f"the target moves by {change} points", late_due)
    return ReplanDecision(True, inputs.new_target, cause, trigger, late_due)


def _blocked(inputs: ReplanInputs) -> str:
    """Why no check may run now, or an empty string."""
    window = inputs.window
    if not window_start(window) <= inputs.now < window.end:
        return "the window is not open"
    if window.end - inputs.now < timedelta(minutes=REPLAN_MIN_REMAINING_MIN):
        return "too little of the window is left"
    if inputs.override_active:
        return "a manual override is on"
    if inputs.replans_so_far >= REPLAN_MAX_WRITES:
        return "the re-plans for tonight are used up"
    return ""


def _hold(inputs: ReplanInputs, why: str, late_ran: bool = False) -> ReplanDecision:  # noqa: FBT001, FBT002
    return ReplanDecision(False, inputs.last_target, why, None, late_ran)


def _trigger(inputs: ReplanInputs, late_due: bool) -> tuple[str | None, str]:  # noqa: FBT001
    """The first thing that asks for a check, with the cause in words."""
    before, now = inputs.last_basis, inputs.new_basis
    if before.ev_plugged != now.ev_plugged:
        return TRIGGER_EV, "the car was plugged in" if now.ev_plugged else "the car was unplugged"
    moved = _forecast_move(before.forecast_kwh, now.forecast_kwh, "the forecast")
    moved = moved or _forecast_move(
        before.next_day_kwh, now.next_day_kwh, "the forecast for the day after"
    )
    if moved:
        return TRIGGER_FORECAST, moved
    if late_due:
        return TRIGGER_LATE, "the late check found a different plan"
    return None, ""


def _forecast_move(last: float | None, new: float | None, what: str) -> str:
    """'the forecast fell by 20%' when it moved far enough to ask for a check, else ''."""
    if last is None or new is None:
        return ""
    gap = new - last
    if abs(gap) < REPLAN_FORECAST_CHANGE_MIN_KWH:
        return ""
    verb = "rose" if gap > 0 else "fell"
    if last <= 0:
        return f"{what} {verb} to {new:.1f} kWh"
    pct = abs(gap) / last * 100
    if pct < REPLAN_FORECAST_CHANGE_PCT:
        return ""
    return f"{what} {verb} by {round(pct)}%"


def replan_note(now: datetime, reason: str) -> str:
    """The sentence the Overnight Charge Reason sensor leads with after a re-plan."""
    return f"Re-planned at {now:%H:%M}: {reason}."


def count_replans(entries: Iterable[Mapping[str, Any]], entity_id: str, since: datetime) -> int:
    """How many re-plans the write log holds for *entity_id* at or after *since*."""
    return sum(
        1
        for entry in entries
        if entry.get("reason") == REPLAN_REASON
        and entry.get("entity_id") == entity_id
        and (at := _parse(entry.get("time"))) is not None
        and at >= since
    )


def _parse(stamp: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(stamp))
    except ValueError:
        return None

