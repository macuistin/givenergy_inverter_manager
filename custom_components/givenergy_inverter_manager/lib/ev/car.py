"""car.py: is a car plugged in at home, from the charger and the car's own readings.

The charger is the authority on whether something is connected to it. The car adds which car
it is and where it is. A car reading older than the limit counts as missing, because many cars
report only every 10 to 30 minutes and some stop while asleep.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .defaults import CAR_READING_MAX_AGE_S


class PlugState(StrEnum):
    PLUGGED_IN = "plugged_in"
    NOT_PLUGGED_IN = "not_plugged_in"
    UNKNOWN = "unknown"


class PlugSource(StrEnum):
    CHARGER = "charger"
    CAR = "car"
    CHARGER_AND_CAR = "charger_and_car"
    NONE = "none"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class CarPlugInputs:
    """What the decision reads. None means not known, not configured or unavailable."""

    charger_plugged: bool | None
    car_plugged: bool | None
    car_home: bool | None
    car_age_s: float | None = None


@dataclass(frozen=True)
class CarPlugResult:
    state: PlugState
    source: PlugSource
    confidence: Confidence
    # The readings disagree, such as the car saying unplugged while the charger is connected.
    conflict: bool = False
    # False when the charger is connected but the car is somewhere else, so it is a visitor.
    car_matches: bool = True


_TRUE_STATES = frozenset({"on", "true", "plugged", "plugged in", "plugged_in", "connected"})
_FALSE_STATES = frozenset(
    {"off", "false", "unplugged", "not plugged", "not_plugged", "disconnected", "not connected"}
)
_UNREADABLE = frozenset({"unavailable", "unknown", "none", ""})


def car_plug_from_state(raw: str | None) -> bool | None:
    """A car's plug or cable entity state as a bool, None when it cannot be read."""
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in _UNREADABLE:
        return None
    if lowered in _TRUE_STATES:
        return True
    if lowered in _FALSE_STATES:
        return False
    return None


def car_home_from_state(raw: str | None) -> bool | None:
    """A device tracker state as at home, not at home, or None when it cannot be read.

    Only the state is read, never the coordinates.
    """
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in _UNREADABLE:
        return None
    return lowered == "home"


def decide_car_plug(
    inputs: CarPlugInputs, max_age_s: float = CAR_READING_MAX_AGE_S
) -> CarPlugResult:
    """Combine the charger and the car into one plug-in answer."""
    stale = inputs.car_age_s is not None and inputs.car_age_s > max_age_s
    car_plugged = None if stale else inputs.car_plugged
    car_home = None if stale else inputs.car_home

    if inputs.charger_plugged:
        return _charger_plugged(car_plugged=car_plugged, car_home=car_home)
    if inputs.charger_plugged is False:
        return _charger_not_plugged(car_plugged=car_plugged, car_home=car_home)
    return _no_charger(car_plugged=car_plugged, car_home=car_home)


def _charger_plugged(*, car_plugged: bool | None, car_home: bool | None) -> CarPlugResult:
    if car_home is False:
        return CarPlugResult(
            PlugState.PLUGGED_IN,
            PlugSource.CHARGER,
            Confidence.MEDIUM,
            conflict=True,
            car_matches=False,
        )
    if car_plugged is False:
        return CarPlugResult(
            PlugState.PLUGGED_IN, PlugSource.CHARGER, Confidence.MEDIUM, conflict=True
        )
    if car_plugged and car_home:
        return CarPlugResult(PlugState.PLUGGED_IN, PlugSource.CHARGER_AND_CAR, Confidence.HIGH)
    return CarPlugResult(PlugState.PLUGGED_IN, PlugSource.CHARGER, Confidence.HIGH)


def _charger_not_plugged(*, car_plugged: bool | None, car_home: bool | None) -> CarPlugResult:
    """A car plugged in at home on a cable the charger does not report still counts."""
    if car_plugged and car_home is not False:
        confidence = Confidence.MEDIUM if car_home else Confidence.LOW
        return CarPlugResult(PlugState.PLUGGED_IN, PlugSource.CAR, confidence, conflict=True)
    return CarPlugResult(PlugState.NOT_PLUGGED_IN, PlugSource.CHARGER, Confidence.HIGH)


def _no_charger(*, car_plugged: bool | None, car_home: bool | None) -> CarPlugResult:
    if car_plugged is None:
        return CarPlugResult(PlugState.UNKNOWN, PlugSource.NONE, Confidence.LOW)
    if car_plugged and car_home is not False:
        confidence = Confidence.MEDIUM if car_home else Confidence.LOW
        return CarPlugResult(PlugState.PLUGGED_IN, PlugSource.CAR, confidence)
    return CarPlugResult(PlugState.NOT_PLUGGED_IN, PlugSource.CAR, Confidence.MEDIUM)
