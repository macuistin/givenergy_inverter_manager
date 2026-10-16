"""When a battery pause that stops charging covers the planned charge, and the repair about it.

GivTCP's pause mode can stop the battery charging in a time of day window (PauseCharge and
PauseBoth). A charge window inside it is written and read back as set, but the inverter does not
charge in it, so the battery never reaches the target. The integration does not change the
pause. It reports the overlap in a repair, once it has held for a few cycles in a row.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass

from .battery_pause import PauseWindow
from .charge_window import ChargeWindow

# Cycles in a row the overlap must hold before a repair appears, so a pause entity that is
# unavailable for a moment raises and clears nothing.
BLOCKED_CYCLES = 3


def charge_is_blocked(
    pause: PauseWindow | None, window: ChargeWindow | None, *, skipped: bool
) -> bool:
    """True when tonight's charge is planned and the pause covers some of its window."""
    if pause is None or window is None or skipped:
        return False
    return pause.overlaps(window.start, window.end)


@dataclass(frozen=True)
class ChargePauseStep:
    blocked_cycles: int
    raise_issue: bool = False
    clear_issue: bool = False


def next_step(*, blocked: bool, blocked_cycles: int) -> ChargePauseStep:
    """The count of cycles blocked so far and what to do about it.

    A cycle with no overlap clears the repair at once. A blocked one counts toward it.
    """
    if not blocked:
        return ChargePauseStep(0, clear_issue=True)
    count = blocked_cycles + 1
    return ChargePauseStep(count, raise_issue=count >= BLOCKED_CYCLES)
