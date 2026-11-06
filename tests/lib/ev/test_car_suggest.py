"""suggest_car_entities finds one car's entities from registry facts, or nothing."""

from custom_components.givenergy_inverter_manager.lib.ev import (
    CAR_KEY_BATTERY_ENTITY,
    CAR_KEY_PLUG_ENTITY,
    CAR_KEY_TRACKER_ENTITY,
    EntityFacts,
    suggest_car_entities,
)


def _car(device: str, name: str) -> list[EntityFacts]:
    return [
        EntityFacts(f"sensor.{name}_soc", device, "battery", "%"),
        EntityFacts(f"binary_sensor.{name}_gun", device, "plug"),
        EntityFacts(f"device_tracker.{name}_gps", device, None),
        EntityFacts(f"sensor.{name}_range", device, "distance", "km"),
    ]


def _phone(device: str) -> list[EntityFacts]:
    return [
        EntityFacts("sensor.phone_battery", device, "battery", "%"),
        EntityFacts("binary_sensor.phone_charging", device, "battery_charging"),
        EntityFacts("device_tracker.phone", device, None),
    ]


def test_a_device_with_tracker_battery_and_plug_is_suggested():
    found = suggest_car_entities(_car("d1", "mg"))
    assert found == {
        CAR_KEY_BATTERY_ENTITY: "sensor.mg_soc",
        CAR_KEY_PLUG_ENTITY: "binary_sensor.mg_gun",
        CAR_KEY_TRACKER_ENTITY: "device_tracker.mg_gps",
    }


def test_a_phone_is_not_a_car_because_it_has_no_plug_sensor():
    assert suggest_car_entities(_phone("p1") + _car("d1", "mg")) == {
        CAR_KEY_BATTERY_ENTITY: "sensor.mg_soc",
        CAR_KEY_PLUG_ENTITY: "binary_sensor.mg_gun",
        CAR_KEY_TRACKER_ENTITY: "device_tracker.mg_gps",
    }
    assert suggest_car_entities(_phone("p1")) == {}


def test_two_cars_give_no_suggestion():
    assert suggest_car_entities(_car("d1", "mg") + _car("d2", "tesla")) == {}


def test_entities_without_a_device_are_ignored():
    assert suggest_car_entities([EntityFacts("sensor.x", None, "battery", "%")]) == {}


def test_a_battery_not_in_percent_does_not_count():
    entities = [
        EntityFacts("sensor.b", "d", "battery", "V"),
        EntityFacts("binary_sensor.p", "d", "plug"),
        EntityFacts("device_tracker.t", "d", None),
    ]
    assert suggest_car_entities(entities) == {}
