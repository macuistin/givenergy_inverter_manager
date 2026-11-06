"""Reading a configured car's entities, and that only states are read."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.givenergy_inverter_manager.lib.ev import read_car

NOW = datetime(2031, 6, 15, 12, 0, tzinfo=timezone.utc)
CAR = {
    "car_name": "Family car",
    "car_battery_level_entity": "sensor.car_battery",
    "car_plug_entity": "binary_sensor.car_plug",
    "car_tracker_entity": "device_tracker.car",
}


def _states(**by_entity):
    """A get_state over {entity_id: (state, seconds old)}."""

    def get_state(entity_id):
        if entity_id not in by_entity:
            return None
        value, age = by_entity[entity_id]
        return SimpleNamespace(state=value, last_reported=NOW - timedelta(seconds=age))

    return get_state


def test_reads_the_battery_the_plug_and_the_location():
    reading = read_car(
        _states(
            **{
                "sensor.car_battery": ("42.5", 60),
                "binary_sensor.car_plug": ("on", 120),
                "device_tracker.car": ("home", 30),
            }
        ),
        CAR,
        NOW,
    )

    assert (reading.name, reading.battery_pct, reading.plugged, reading.at_home) == (
        "Family car",
        42.5,
        True,
        True,
    )
    assert reading.age_s == 120


def test_a_missing_or_unavailable_entity_reads_as_unknown():
    reading = read_car(
        _states(**{"sensor.car_battery": ("unavailable", 10), "device_tracker.car": ("home", 10)}),
        CAR,
        NOW,
    )

    assert reading.battery_pct is None
    assert reading.plugged is None
    assert reading.at_home is True


def test_a_battery_outside_zero_to_a_hundred_is_not_trusted():
    for bad in ("120", "-3", "full"):
        reading = read_car(_states(**{"sensor.car_battery": (bad, 0)}), CAR, NOW)
        assert reading.battery_pct is None


def test_a_car_with_no_entities_has_no_age_and_a_default_name():
    reading = read_car(_states(), {}, NOW)

    assert reading.name == "Car"
    assert reading.age_s is None
    assert (reading.plugged, reading.at_home, reading.battery_pct) == (None, None, None)


def test_a_reading_from_the_future_has_age_zero():
    reading = read_car(_states(**{"binary_sensor.car_plug": ("on", -50)}), CAR, NOW)

    assert reading.age_s == 0.0
