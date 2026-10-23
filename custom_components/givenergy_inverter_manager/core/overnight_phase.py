"""
overnight_phase.py: when the overnight plan is worth showing.

The overnight charge is planned all day, but the plan is only useful in the evening and while
it runs. In the morning it has been carried out, and through the day the battery will still
change a lot before the cheap rate starts, so a "tonight" figure then is a guess from the
state of charge now. The plan is shown from an hour before solar is expected to end until the
charge window has closed. Outside that time the plan sensor says in words where things stand.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ..const import OVERNIGHT_PLAN_LEAD_MINUTES, SOLAR_SUNRISE_HOUR

if TYPE_CHECKING:
    from .charge_window import ChargeWindow

_MINUTES_PER_DAY = 24 * 60
_NOON_MINUTE = 12 * 60

# The words the plan sensor starts with outside the evening and night. The dashboard reads them
# to choose its line, as it does for PLAN_SKIP_WORDS and PLAN_CHARGE_WORDS.
PLAN_WAITING_WORDS = "Tonight's plan will be ready"
PLAN_DONE_WORDS = "Overnight charge complete"


class OvernightPhase(StrEnum):
    """Where the day is in the overnight plan."""

    WAITING = "waiting"  # daylight, the plan is not ready to be read yet
    ACTIVE = "active"  # the evening and the night until the charge window has closed
    DONE = "done"  # the window has closed and it is not yet daylight


@dataclass(frozen=True)
class OvernightTimes:
    """The minutes of the day the phase is read from.

    solar_end_minute is when solar is expected to stop today. window_end_minute is the end of
    the published charge window, None without one. solar_stopped is True once solar has
    settled at nothing, which shows the plan at once when it stops before it was expected to.
    """

    solar_end_minute: float
    window_end_minute: float | None
    solar_stopped: bool = False


def plan_ready_minute(solar_end_minute: float) -> int:
    """The minute of the day the plan starts to show: an hour before solar is expected to end."""
    return max(0, round(solar_end_minute) - OVERNIGHT_PLAN_LEAD_MINUTES)


def window_end_minute(window: ChargeWindow | None) -> float | None:
    """The minute of the day the published charge window ends, None without a window."""
    return None if window is None else window.end.hour * 60 + window.end.minute


def overnight_phase(minute: float, times: OvernightTimes) -> OvernightPhase:
    """The phase at *minute* of the day.

    The plan shows from plan_ready_minute through midnight and on until the window ends. After
    that it is done until the hour solar usually starts, then waiting until the evening. A
    window with no end, or one that runs past that hour, leaves no done time. Solar that has
    stopped in the afternoon shows the plan before its ready time.
    """
    if minute >= plan_ready_minute(times.solar_end_minute):
        return OvernightPhase.ACTIVE
    if times.solar_stopped and minute >= _NOON_MINUTE:
        return OvernightPhase.ACTIVE
    handover = SOLAR_SUNRISE_HOUR * 60
    ends = handover if times.window_end_minute is None else min(times.window_end_minute, handover)
    if minute < ends:
        return OvernightPhase.ACTIVE
    return OvernightPhase.DONE if minute < handover else OvernightPhase.WAITING


def clock_text(minute: float) -> str:
    """A minute of the day as HH:MM, for example 1020 gives "17:00"."""
    whole = round(minute) % _MINUTES_PER_DAY
    return f"{whole // 60:02d}:{whole % 60:02d}"
