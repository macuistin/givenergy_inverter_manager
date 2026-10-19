"""
scheduled_run.py: the longest a scheduled run of the immersion lasts.

Scheduled heating is the grid-paid kind: heating in the cheapest rate window, and heating to have
the water ready by a ready-by time. It is paid for by the minute, so the user sets how long one
run may last. Solar surplus heating is free and is not limited.

The plan is stateless. It works from the water temperature each cycle and keeps the heater on
until the water reaches its target, so on its own it cannot stop a run. This module counts the
minutes the heater has been on while scheduled heating wanted it, and says when the limit is
reached. After that the scheduled decisions step aside and the heater goes off, unless solar
surplus wants it. The run does not start again for the same ready time or window: the count and
the stop are kept until scheduled heating stops wanting the heater, which is when the window
closes, the ready time passes or the water is warm enough.

The count is in memory only, so a restart of Home Assistant starts it again.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .timeutil import elapsed_seconds

# The state of the run limit warning: off without a limit or with the warning turned off, idle
# while no run has reached the limit, reached once one has.
STATES = ("off", "idle", "reached")

_SECONDS_PER_MINUTE = 60.0
# Cycles are 30 seconds apart. A longer gap means Home Assistant was not running, and heating it
# did not see is not counted.
_LARGEST_GAP_S = 120.0


@dataclass
class HeldScheduledRun:
    """The minutes counted for the run in hand, and whether it has reached its limit."""

    minutes: float = 0.0
    last_at: datetime | None = None
    capped: bool = False


@dataclass(frozen=True)
class RunStep:
    """One cycle: whether scheduled heating wants the heater, and whether it is on."""

    now: datetime
    wanted: bool
    heater_on: bool
    max_minutes: int


def advance(held: HeldScheduledRun, step: RunStep) -> None:
    """Count this cycle, and set capped once the limit is reached.

    A limit of 0 turns the feature off. Scheduled heating that no longer wants the heater ends
    the run, so the count and the stop clear.
    """
    if step.max_minutes <= 0 or not step.wanted:
        held.minutes, held.capped = 0.0, False
    else:
        held.minutes += _counted_minutes(held, step)
        held.capped = held.capped or held.minutes >= step.max_minutes
    held.last_at = step.now


def _counted_minutes(held: HeldScheduledRun, step: RunStep) -> float:
    """The minutes since the last cycle that count: only while the heater was on and not capped."""
    if held.last_at is None or not step.heater_on or held.capped:
        return 0.0
    gap = elapsed_seconds(held.last_at, step.now)
    return gap / _SECONDS_PER_MINUTE if 0 < gap <= _LARGEST_GAP_S else 0.0


def warning_state(held: HeldScheduledRun, max_minutes: int, *, enabled: bool) -> str:
    """The state of the run limit warning for this cycle."""
    if max_minutes <= 0 or not enabled:
        return "off"
    return "reached" if held.capped else "idle"
