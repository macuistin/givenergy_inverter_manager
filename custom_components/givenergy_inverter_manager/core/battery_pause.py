"""Re-export of lib/givtcp so existing imports keep working. Import from lib/ in new code."""

from ..lib.givtcp.pause import (
    MINUTES_PER_DAY,
    SLOT_MINUTES,
    SLOTS_PER_DAY,
    PauseWindow,
    with_note,
)

__all__ = [
    "MINUTES_PER_DAY",
    "PauseWindow",
    "SLOTS_PER_DAY",
    "SLOT_MINUTES",
    "with_note",
]
