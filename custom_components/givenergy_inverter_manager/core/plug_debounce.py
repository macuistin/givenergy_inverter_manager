"""plug_debounce.py: a charger that reads unplugged for one moment is not an unplugged car.

A charger can drop its plug status for a minute while the car is still connected. The charge plan
reads the plug state to move tonight's target, so one dropped reading flipped the target and used
up the night's re-plans. Plugging in counts at once. Unplugging counts only after the charger has
read unplugged for the whole confirm time.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from datetime import datetime


class PlugDebounce:
    """Holds the plug state the charge plan sees."""

    def __init__(self, unplug_confirm_s: float) -> None:
        self._confirm_s = unplug_confirm_s
        self._plugged = False
        self._unplugged_since: datetime | None = None
        self._seen = False

    def update(self, raw_plugged: bool, now: datetime) -> bool:  # noqa: FBT001
        """The plug state to use now, given the charger's reading at *now*."""
        if raw_plugged or not self._seen:
            self._plugged = raw_plugged
            self._unplugged_since = None
            self._seen = True
            return self._plugged
        if not self._plugged:
            return False
        if self._unplugged_since is None:
            self._unplugged_since = now
        if (now - self._unplugged_since).total_seconds() >= self._confirm_s:
            self._plugged = False
            self._unplugged_since = None
        return self._plugged
