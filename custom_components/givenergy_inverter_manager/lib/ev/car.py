"""car.py: is a car plugged in at home, from the charger and the car's own readings.

The charger is the authority on whether something is connected to it. The car adds which car
it is and where it is. A car reading older than the limit counts as missing, because many cars
report only every 10 to 30 minutes and some stop while asleep.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from ..timeutil import elapsed_seconds
from .defaults import CAR_READING_MAX_AGE_S

# The keys of one car in the saved config. A car is a dict with these keys.
CAR_KEY_NAME = "car_name"
CAR_KEY_BATTERY_ENTITY = "car_battery_level_entity"
CAR_KEY_PLUG_ENTITY = "car_plug_entity"
CAR_KEY_TRACKER_ENTITY = "car_tracker_entity"
CAR_KEY_BATTERY_KWH = "car_battery_capacity_kwh"


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


@dataclass(frozen=True)
class CarReading:
    """One car's entities read at one moment. None means missing, unavailable or unreadable."""

    name: str
    plugged: bool | None
    at_home: bool | None
    battery_pct: float | None
    # Seconds since the oldest of the plug, location and battery readings that were present.
    age_s: float | None


def _battery_pct(raw: str | None) -> float | None:
    if raw is None or raw.strip().lower() in _UNREADABLE:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if 0.0 <= value <= 100.0 else None


def read_car(
    get_state: Callable[[str], Any], car: Mapping[str, Any], now: datetime
) -> CarReading:
    """Read a configured car's battery level, plug state and location from entity states.

    Only reads. It never calls a service on the car, so it cannot wake it. The tracker's
    coordinates are not read.
    """
    ages: list[float] = []

    def read(key: str) -> str | None:
        entity_id = car.get(key)
        state = get_state(entity_id) if entity_id else None
        if state is None:
            return None
        ages.append(max(0.0, elapsed_seconds(state.last_reported, now)))
        return str(state.state)

    plug = car_plug_from_state(read(CAR_KEY_PLUG_ENTITY))
    home = car_home_from_state(read(CAR_KEY_TRACKER_ENTITY))
    level = _battery_pct(read(CAR_KEY_BATTERY_ENTITY))
    return CarReading(
        name=str(car.get(CAR_KEY_NAME) or "Car"),
        plugged=plug,
        at_home=home,
        battery_pct=level,
        age_s=max(ages) if ages else None,
    )


@dataclass(frozen=True)
class EntityFacts:
    """What the entity registry says about one entity, for finding a car's entities."""

    entity_id: str
    device_id: str | None
    device_class: str | None
    unit: str | None = None


def suggest_car_entities(entities: list[EntityFacts]) -> dict[str, str]:
    """The entities of the one device that looks like a car, or nothing when unsure.

    A device is a car when it has a device tracker, a battery level sensor in percent and a
    binary sensor of device class plug. A phone has the first two but no plug sensor. When more
    than one device qualifies nothing is suggested, because a wrong guess is worse than none.
    """
    by_device: dict[str, list[EntityFacts]] = {}
    for entity in entities:
        if entity.device_id:
            by_device.setdefault(entity.device_id, []).append(entity)
    found: list[dict[str, str]] = []
    for members in by_device.values():
        tracker = _first(members, "device_tracker", None)
        plug = _first(members, "binary_sensor", "plug")
        battery = next(
            (
                m.entity_id
                for m in members
                if m.entity_id.startswith("sensor.")
                and m.device_class == "battery"
                and m.unit == "%"
            ),
            None,
        )
        if tracker and plug and battery:
            found.append(
                {
                    CAR_KEY_TRACKER_ENTITY: tracker,
                    CAR_KEY_PLUG_ENTITY: plug,
                    CAR_KEY_BATTERY_ENTITY: battery,
                }
            )
    return found[0] if len(found) == 1 else {}


def _first(members: list[EntityFacts], domain: str, device_class: str | None) -> str | None:
    for member in members:
        if member.entity_id.startswith(f"{domain}.") and (
            device_class is None or member.device_class == device_class
        ):
            return member.entity_id
    return None
