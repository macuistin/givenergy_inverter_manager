"""Re-export of lib/heating so existing imports keep working. Import from lib/ in new code."""

from ..lib.heating.window import (
    WindowOpening,
    next_window_opening,
    open_cheapest_window,
)

__all__ = [
    "WindowOpening",
    "next_window_opening",
    "open_cheapest_window",
]
