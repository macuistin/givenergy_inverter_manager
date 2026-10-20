"""
window_settle.py: put slot 1 and the charge target back once a night's charge window has closed.

A night that needs a long charge writes a window past the cheapest period (02:00 to 07:15 instead
of 02:00 to 04:00) and a high target. Nothing else writes slot 1 until the next trigger, so the
extended end and the old target stay on the inverter all day while the plan has moved on. This
decides when to write the plan's own window and target back.

It acts once the written window has closed, and only while the inverter still holds what the
manager wrote that night: an extended end, or a target other than the one the plan now gives. A
manual charge or skip override leaves it alone, and it stops after SETTLE_MAX_TRIES tries.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .charge_retry import WriteWindow
from .tariff import RatePeriod

SETTLE_MAX_TRIES = 3
SETTLE_RETRY_GAP = timedelta(minutes=5)


@dataclass(frozen=True)
class SettleInputs:
    """What one check needs. written_* is tonight's write, planned_* what the plan gives now."""

    now: datetime
    window: WriteWindow
    written_period: RatePeriod
    written_target: int
    planned_period: RatePeriod
    planned_target: int
    override_active: bool
    tries: int
    last_try: datetime | None


def needs_settling(inputs: SettleInputs) -> bool:
    """True when the window has closed and the inverter still holds more than the plan asks."""
    if inputs.override_active or inputs.now < inputs.window.end:
        return False
    if inputs.tries >= SETTLE_MAX_TRIES:
        return False
    if inputs.last_try is not None and inputs.now - inputs.last_try < SETTLE_RETRY_GAP:
        return False
    extended = inputs.written_period.end != inputs.planned_period.end
    return extended or inputs.written_target != inputs.planned_target
