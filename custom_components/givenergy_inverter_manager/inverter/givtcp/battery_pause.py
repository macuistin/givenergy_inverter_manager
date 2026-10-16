"""
battery_pause.py: read GivTCP's battery pause into a PauseWindow.

GivTCP can pause the battery for a time of day window. It publishes three entities per inverter:
a mode select and a start and an end time. The mode has four options, taken from GivTCP's own
option list:

  Disabled        no pause
  PauseCharge     the battery does not charge in the window. It still serves the house, so
                  night estimates are unchanged
  PauseDischarge  the battery does not discharge in the window. The grid serves the house
  PauseBoth       neither charges nor discharges. Modelled as a discharge pause, see below

PauseDischarge and PauseBoth pause discharge, so they give a window. PauseBoth also stops a charge
inside the window, which the plan does not model. Any other text gives no window, so an install
whose GivTCP changes the option names reads as it did before this was added.

The entity ids are in discovery.py (battery_pause_entities). This module turns the three state
texts the reader finds into a window.

No Home Assistant imports. The reader passes in the state texts.
"""

from __future__ import annotations

import re
from datetime import time

from ...core.battery_pause import PauseWindow

# The options of GivTCP's Battery_pause_mode, with whether each pauses discharge. Compared
# without case, spaces, underscores or hyphens.
_PAUSES_DISCHARGE = {
    "disabled": False,
    "pausecharge": False,
    "pausedischarge": True,
    "pauseboth": True,
}
_IGNORED = re.compile(r"[\s_\-]+")
_CLOCK = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::\d{2})?$")


def pauses_discharge(mode: str | None) -> bool | None:
    """Whether a mode option stops the battery discharging. None for text GivTCP does not use."""
    if mode is None:
        return None
    return _PAUSES_DISCHARGE.get(_IGNORED.sub("", mode).casefold())


def parse_clock(text: str | None) -> time | None:
    """A time published as HH:MM or HH:MM:SS, None for anything else."""
    match = _CLOCK.match(text.strip()) if text is not None else None
    if match is None:
        return None
    try:
        return time(int(match["hour"]), int(match["minute"]))
    except ValueError:
        return None


def pause_window(mode: str | None, start: str | None, end: str | None) -> PauseWindow | None:
    """The window in which discharge is paused, from the three state texts.

    None when the mode does not pause discharge, a time is missing or not a time, or the start
    equals the end (an empty window).
    """
    if not pauses_discharge(mode):
        return None
    begin, finish = parse_clock(start), parse_clock(end)
    if begin is None or finish is None or begin == finish:
        return None
    return PauseWindow(begin, finish)
