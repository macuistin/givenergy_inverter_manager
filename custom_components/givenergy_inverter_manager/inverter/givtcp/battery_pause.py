"""Re-export of lib/givtcp so existing imports keep working. Import from lib/ in new code."""

from ...lib.givtcp.pause_modes import (
    charge_pause_window,
    parse_clock,
    pause_window,
    pauses_charge,
    pauses_discharge,
)

__all__ = [
    "charge_pause_window",
    "parse_clock",
    "pause_window",
    "pauses_charge",
    "pauses_discharge",
]
