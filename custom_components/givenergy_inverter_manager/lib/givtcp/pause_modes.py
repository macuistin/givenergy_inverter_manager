"""
pause_modes.py: read GivTCP's battery pause into a PauseWindow.

GivTCP can pause the battery for a time of day window. It publishes three entities per inverter:
a mode select and a start and an end time. The mode has four options, taken from GivTCP's own
option list:

  Disabled        no pause
  PauseCharge     the battery does not charge in the window. It still serves the house, so
                  night estimates are unchanged
  PauseDischarge  the battery does not discharge in the window. The grid serves the house
  PauseBoth       neither charges nor discharges

PauseDischarge and PauseBoth pause discharge, so they give a discharge window, which the night
estimates model. PauseCharge and PauseBoth pause charging, so they give a charge window. The plan
does not model a stopped charge. The coordinator reports a planned charge that falls inside one
in a repair. Any other text gives no window, so an install whose GivTCP changes the option names
reads as it did before this was added.

The entity ids are in discovery.py (battery_pause_entities). This module turns the three state
texts the reader finds into a window.

No Home Assistant imports. The reader passes in the state texts.
"""

from __future__ import annotations

import re
from datetime import time

from .pause import PauseWindow

# The options of GivTCP's Battery_pause_mode, with what each one pauses: (discharge, charge).
# Compared without case, spaces, underscores or hyphens.
_PAUSES: dict[str, tuple[bool, bool]] = {
    "disabled": (False, False),
    "notpaused": (False, False),
    "pausecharge": (False, True),
    "pausedischarge": (True, False),
    "pauseboth": (True, True),
}
_IGNORED = re.compile(r"[\s_\-]+")
_CLOCK = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::\d{2})?$")


def _pauses(mode: str | None) -> tuple[bool, bool] | None:
    return None if mode is None else _PAUSES.get(_IGNORED.sub("", mode).casefold())


def pauses_discharge(mode: str | None) -> bool | None:
    """Whether a mode option stops the battery discharging. None for text GivTCP does not use."""
    pauses = _pauses(mode)
    return None if pauses is None else pauses[0]


def pauses_charge(mode: str | None) -> bool | None:
    """Whether a mode option stops the battery charging. None for text GivTCP does not use."""
    pauses = _pauses(mode)
    return None if pauses is None else pauses[1]


def parse_clock(text: str | None) -> time | None:
    """A time published as HH:MM or HH:MM:SS, None for anything else."""
    match = _CLOCK.match(text.strip()) if text is not None else None
    if match is None:
        return None
    try:
        return time(int(match["hour"]), int(match["minute"]))
    except ValueError:
        return None


def _window(start: str | None, end: str | None) -> PauseWindow | None:
    """The window from two state texts, None when a time is unusable or the window is empty."""
    begin, finish = parse_clock(start), parse_clock(end)
    if begin is None or finish is None or begin == finish:
        return None
    return PauseWindow(begin, finish)


def pause_window(mode: str | None, start: str | None, end: str | None) -> PauseWindow | None:
    """The window in which discharge is paused, from the three state texts.

    None when the mode does not pause discharge, a time is missing or not a time, or the start
    equals the end (an empty window).
    """
    return _window(start, end) if pauses_discharge(mode) else None


def charge_pause_window(
    mode: str | None, start: str | None, end: str | None
) -> PauseWindow | None:
    """The window in which charging is paused (PauseCharge or PauseBoth), from the same texts."""
    return _window(start, end) if pauses_charge(mode) else None
