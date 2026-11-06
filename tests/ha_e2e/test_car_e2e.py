"""The car set up in the options: its device, its sensors and what they read, in real Home Assistant."""

from __future__ import annotations

import pytest
from conftest import CAR_BATTERY, CAR_PLUG, CAR_TRACKER, MIDDAY, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import CONF_CARS, DOMAIN

BATTERY, PLUG, TRACKER = CAR_BATTERY, CAR_PLUG, CAR_TRACKER
KEYS = ("car_plug_status", "car_battery_level", "car_charging_power", "car_at_home")


@pytest.fixture
def scenario():
    return MIDDAY


async def _set_up(hass, *, with_car: bool = True) -> MockConfigEntry:
    data = full_config_data()
    if not with_car:
        del data[CONF_CARS]
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=data,
        unique_id=SERIAL,
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _entity_id(hass, entry, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")


async def _unload(hass, entry) -> None:
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_a_car_gets_its_own_device_with_four_sensors(hass_in_scenario):
    hass = hass_in_scenario
    entry = await _set_up(hass)

    ids = {key: _entity_id(hass, entry, key) for key in KEYS}
    assert ids == {
        "car_plug_status": "sensor.car_plug_status",
        "car_battery_level": "sensor.car_battery_level",
        "car_charging_power": "sensor.car_charging_power",
        "car_at_home": "sensor.car_location",
    }
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert {d.name for d in devices} >= {"Car"}
    registry = er.async_get(hass)
    car_device = registry.async_get(ids["car_plug_status"]).device_id
    assert {registry.async_get(e).device_id for e in ids.values()} == {car_device}

    await _unload(hass, entry)


async def test_the_sensors_read_the_cars_entities(hass_in_scenario):
    hass = hass_in_scenario
    hass.states.async_set(BATTERY, "64", {"device_class": "battery", "unit_of_measurement": "%"})
    hass.states.async_set(PLUG, "on")
    hass.states.async_set(TRACKER, "home")
    entry = await _set_up(hass)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert float(hass.states.get("sensor.car_battery_level").state) == 64.0
    assert hass.states.get("sensor.car_location").state == "home"
    status = hass.states.get("sensor.car_plug_status")
    assert status.state == "plugged_in"
    assert status.attributes["source"] == "car"
    assert float(hass.states.get("sensor.car_charging_power").state) == 0.0

    await _unload(hass, entry)


async def test_a_car_away_is_not_plugged_in_at_home(hass_in_scenario):
    hass = hass_in_scenario
    hass.states.async_set(PLUG, "on")
    hass.states.async_set(TRACKER, "not_home")
    entry = await _set_up(hass)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.car_plug_status").state == "not_plugged_in"
    assert hass.states.get("sensor.car_location").state == "away"

    await _unload(hass, entry)


async def test_without_a_car_there_is_no_car_device_or_sensor(hass_in_scenario):
    hass = hass_in_scenario
    entry = await _set_up(hass, with_car=False)

    assert all(_entity_id(hass, entry, key) is None for key in KEYS)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert "Car" not in {d.name for d in devices}

    await _unload(hass, entry)
