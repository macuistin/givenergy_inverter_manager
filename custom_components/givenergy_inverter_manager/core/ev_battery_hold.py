"""
ev_battery_hold.py - when to hold the house battery back while the car charges.

A car on the grid at a dear rate or on a full charge-now draws up to 7 kW. The inverter treats it
like any other load, so the battery covers what the grid does not. With the hold on, the
integration pauses battery discharge for a short window while the car draws from the battery,
renews it while the car keeps charging, and ends it soon after the car stops.

The pause window repeats every day, so a hold changes a setting the install may already use,
such as a night pause. The caller saves the live pause before a hold and writes it back when the
hold ends. This module decides only the step. It never reads or writes the inverter.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum

from ..const import (
    EV_HOLD_MINUTES,
    EV_HOLD_RELEASE_MINUTES,
    EV_HOLD_RENEW_MINUTES,
    EV_HOLD_STEP_MINUTES,
)
from ..lib.givtcp.model import BatteryPause, PauseSetting
from .battery_pause import PauseWindow


class HoldStep(StrEnum):
    NOTHING = "nothing"
    START = "start"
    RENEW = "renew"
    RELEASE = "release"


@dataclass(frozen=True)
class HoldFacts:
    """What the decision needs from one cycle."""

    enabled: bool
    car_draining_battery: bool
    # None while the car is charging, else how long it has not been.
    minutes_since_car_charged: float | None
    now: datetime
    live: PauseSetting | None
    holding: bool = False
    hold_ends: datetime | None = None


@dataclass(frozen=True)
class HoldDecision:
    step: HoldStep
    # Why nothing is done when the hold would otherwise have started, else empty.
    note: str = ""


def hold_ends(now: datetime) -> datetime:
    """When a hold written at *now* ends: the hold length after now rounded down to the step."""
    start = now.replace(second=0, microsecond=0)
    start -= timedelta(minutes=start.minute % EV_HOLD_STEP_MINUTES)
    return start + timedelta(minutes=EV_HOLD_MINUTES)


def hold_window(now: datetime) -> tuple[time, time]:
    """The window a hold writes, from now rounded down to the step to the end of the hold."""
    ends = hold_ends(now)
    return (ends - timedelta(minutes=EV_HOLD_MINUTES)).time(), ends.time()


@dataclass(frozen=True)
class HoldRecord:
    """What a hold changed: the pause to write back and when the hold ends."""

    prior: PauseSetting
    ends: datetime

    def as_dict(self) -> dict[str, str | None]:
        window = self.prior.window
        return {
            "pause": self.prior.pause.value,
            "start": window[0].strftime("%H:%M") if window else None,
            "end": window[1].strftime("%H:%M") if window else None,
            "ends": self.ends.isoformat(),
        }

    @classmethod
    def from_dict(cls, raw: object) -> HoldRecord | None:
        """The record from its saved form, None for anything that is not a whole record."""
        if not isinstance(raw, dict):
            return None
        try:
            pause = BatteryPause(raw["pause"])
            ends = datetime.fromisoformat(raw["ends"])
            start, end = raw.get("start"), raw.get("end")
            window = (
                (time.fromisoformat(start), time.fromisoformat(end)) if start and end else None
            )
        except (KeyError, TypeError, ValueError):
            return None
        return cls(PauseSetting(pause, window), ends)


def _already_paused(live: PauseSetting, now: datetime) -> bool:
    if live.pause is not BatteryPause.DISCHARGE or live.window is None:
        return False
    minute = now.hour * 60 + now.minute
    return PauseWindow(*live.window).paused_minutes(minute, 1) > 0


def _holding_step(facts: HoldFacts) -> HoldDecision:
    if not facts.enabled:
        return HoldDecision(HoldStep.RELEASE)
    away = facts.minutes_since_car_charged
    if away is not None:
        gone = away >= EV_HOLD_RELEASE_MINUTES
        return HoldDecision(HoldStep.RELEASE if gone else HoldStep.NOTHING)
    left = (
        (facts.hold_ends - facts.now).total_seconds() / 60 if facts.hold_ends is not None else 0.0
    )
    return HoldDecision(HoldStep.RENEW if left <= EV_HOLD_RENEW_MINUTES else HoldStep.NOTHING)


def decide_hold(facts: HoldFacts) -> HoldDecision:
    """The step for this cycle."""
    if facts.holding:
        return _holding_step(facts)
    if not facts.enabled or not facts.car_draining_battery:
        return HoldDecision(HoldStep.NOTHING)
    live = facts.live
    if live is None:
        return HoldDecision(HoldStep.NOTHING, "the battery pause cannot be read")
    if live.pause in (BatteryPause.CHARGE, BatteryPause.BOTH):
        return HoldDecision(HoldStep.NOTHING, "a pause that stops charging is already set")
    if live.pause is not BatteryPause.OFF and live.window is None:
        return HoldDecision(HoldStep.NOTHING, "the battery pause window cannot be read")
    if _already_paused(live, facts.now):
        return HoldDecision(HoldStep.NOTHING, "the battery is already paused")
    return HoldDecision(HoldStep.START)
