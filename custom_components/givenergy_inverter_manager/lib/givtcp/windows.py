"""windows.py: which end of a time window to write first, so the inverter never holds a gap.

A window is two writes, and between them the inverter holds a mix of the old and new times. The
mix is harmless when it covers both windows, and wrong when it covers neither. Moving a window
later, write the end first: the inverter holds the old start to the new end. Moving it earlier,
write the start first: the new start to the old end. Either way the mix contains the old window
and the new one. The first write is a harmless widening, and the second one narrows to the new
window. A window that wraps midnight is compared round the clock.
"""

from __future__ import annotations

import re
from datetime import time

_CLOCK = re.compile(r"^\s*(\d{1,2}):(\d{2})")
_DAY_MINUTES = 24 * 60


def clock_minutes(text: str | None) -> int | None:
    """Minutes since midnight for 'HH:MM' or 'HH:MM:SS', None for anything else."""
    match = _CLOCK.match(text) if text else None
    return int(match[1]) * 60 + int(match[2]) if match else None


def end_first(current_start: str | None, new_start: time) -> bool:
    """True when the window moves later, so its end should be written before its start.

    False when the current start cannot be read, which keeps the order start then end.
    """
    before = clock_minutes(current_start)
    if before is None:
        return False
    shift = (new_start.hour * 60 + new_start.minute - before) % _DAY_MINUTES
    return 0 < shift <= _DAY_MINUTES // 2
