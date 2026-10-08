"""
ev_base_rate.py: when a car charging from the grid at the base rate is worth an alert.

The base rate is the tariff's catch-all rate, in force when no timed band is active. When
the tariff has a cheaper band, a session that draws from the grid at the base rate costs
more than the same session moved into that band.

A reading is a base-rate grid draw when all of these hold:
  * the car draws at least EV_CHARGER_MIN_POWER_W, the existing "EV is charging" threshold
  * the grid supplies at least that much power, so the car is not running on solar
  * the rate in force is the base rate
  * the tariff has a cheaper band, so there is somewhere to move the session

watch_step() turns a reading into an action. It raises the alert once the draw has held for
EV_BASE_RATE_ALERT_DELAY_S, raises it once, and clears it when any condition stops holding.
A tariff with no cheaper band never alerts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ..const import EV_BASE_RATE_ALERT_DELAY_S, EV_CHARGER_MIN_POWER_W
from .timeutil import elapsed_seconds


class AlertAction(StrEnum):
    """What the caller does with the alert this cycle."""

    NONE = "none"
    RAISE = "raise"
    CLEAR = "clear"


@dataclass(frozen=True)
class BaseRateReading:
    """One cycle's inputs.

    grid_import_w is positive when the home imports. next_cheap_start is the HH:MM start of
    the next cheaper band, or None when the tariff has none or one is active now.
    """

    ev_power_w: float
    grid_import_w: float
    on_base_rate: bool
    next_cheap_start: str | None

    @property
    def is_base_rate_draw(self) -> bool:
        """True when the car is charging from the grid at the base rate with a cheaper band."""
        return (
            self.ev_power_w >= EV_CHARGER_MIN_POWER_W
            and self.grid_import_w >= EV_CHARGER_MIN_POWER_W
            and self.on_base_rate
            and self.next_cheap_start is not None
        )


@dataclass(frozen=True)
class WatchState:
    """When the current draw began, and whether its alert is raised."""

    draw_since: datetime | None = None
    raised: bool = False


@dataclass(frozen=True)
class WatchStep:
    """The state to keep and the action to take."""

    state: WatchState
    action: AlertAction


def watch_step(state: WatchState, reading: BaseRateReading, now: datetime) -> WatchStep:
    """Advance the watch by one cycle."""
    if not reading.is_base_rate_draw:
        action = AlertAction.CLEAR if state.raised else AlertAction.NONE
        return WatchStep(WatchState(), action)
    since = state.draw_since or now
    if state.raised:
        return WatchStep(WatchState(since, raised=True), AlertAction.NONE)
    if elapsed_seconds(since, now) >= EV_BASE_RATE_ALERT_DELAY_S:
        return WatchStep(WatchState(since, raised=True), AlertAction.RAISE)
    return WatchStep(WatchState(since), AlertAction.NONE)
