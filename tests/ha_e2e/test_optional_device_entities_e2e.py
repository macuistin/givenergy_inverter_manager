"""
The EV charger, the immersion switch and the immersion temperature sensor are optional.

An entity that needs one exists only while the device does. A device added later brings its
entities with it, with no restart and no manual step. A device taken away takes them with it.
"""

from __future__ import annotations

import pytest
from conftest import (
    IMMERSION_SWITCH,
    IMMERSION_TEMP,
    MIDDAY,
    ZAPPI_STATES,
    discover_the_charger,
    full_config_data,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_MIN_TEMP,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TARGET_TEMP,
    CONF_IMMERSION_TEMP_SENSOR,
    DOMAIN,
)
from custom_components.givenergy_inverter_manager.core.devices import Device
from custom_components.givenergy_inverter_manager.optional_devices import _device_entities

SERIAL = "ab1234g567"


@pytest.fixture
def scenario():
    return MIDDAY


def _keys_needing(*devices: Device) -> set[str]:
    return {key for _, key, device in _device_entities() if device in devices}


EV_KEYS = _keys_needing(Device.EV_CHARGER)
SWITCH_KEYS = _keys_needing(Device.IMMERSION_SWITCH)
SENSOR_KEYS = _keys_needing(Device.IMMERSION_SENSOR)
THERMOSTAT_KEYS = _keys_needing(Device.IMMERSION_THERMOSTAT)


def _config(*, switch: bool, sensor: bool) -> dict:
    data = full_config_data()
    for key in (CONF_IMMERSION_SWITCH, CONF_IMMERSION_TEMP_SENSOR):
        data.pop(key)
    if switch:
        data[CONF_IMMERSION_SWITCH] = IMMERSION_SWITCH
    if sensor:
        data[CONF_IMMERSION_TEMP_SENSOR] = IMMERSION_TEMP
    return data


async def _setup(hass, *, switch=False, sensor=False, charger=False) -> MockConfigEntry:
    if charger:
        for entity_id, state in ZAPPI_STATES.items():
            hass.states.async_set(entity_id, state)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=_config(switch=switch, sensor=sensor),
        unique_id=SERIAL,
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    if charger:
        await discover_the_charger(hass, entry)
    return entry


def _registered(hass, entry) -> set[str]:
    """The unique ID suffixes of the entities in the registry for this entry."""
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    return {
        e.unique_id.removeprefix(prefix)
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }


def _states_exist(hass, entry, keys: set[str]) -> bool:
    """True when every one of these is registered, and has a state unless it is disabled."""
    registry = er.async_get(hass)
    for key in keys:
        entity_id = next(
            (
                found
                for domain in ("sensor", "switch", "number")
                if (found := registry.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}"))
            ),
            None,
        )
        if entity_id is None:
            return False
        if registry.async_get(entity_id).disabled_by is None and hass.states.get(entity_id) is None:
            return False
    return True


async def _unload(hass, entry) -> None:
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


# ── every combination of devices at setup ────────────────────────────────────

COMBINATIONS = {
    "none": {"switch": False, "sensor": False, "charger": False},
    "charger only": {"switch": False, "sensor": False, "charger": True},
    "switch only": {"switch": True, "sensor": False, "charger": False},
    "sensor only": {"switch": False, "sensor": True, "charger": False},
    "switch and sensor": {"switch": True, "sensor": True, "charger": False},
    "everything": {"switch": True, "sensor": True, "charger": True},
}


def _expected(switch: bool, sensor: bool, charger: bool) -> set[str]:
    keys: set[str] = set()
    if charger:
        keys |= EV_KEYS
    if switch:
        keys |= SWITCH_KEYS
    if sensor:
        keys |= SENSOR_KEYS
    if switch and sensor:
        keys |= THERMOSTAT_KEYS
    return keys


@pytest.mark.parametrize("combination", COMBINATIONS)
async def test_only_the_entities_of_the_devices_present_exist(hass, hass_in_scenario, service_calls, combination):
    devices = COMBINATIONS[combination]
    entry = await _setup(hass, **devices)

    device_keys = EV_KEYS | SWITCH_KEYS | SENSOR_KEYS | THERMOSTAT_KEYS
    assert _registered(hass, entry) & device_keys == _expected(**devices)
    assert _states_exist(hass, entry, _expected(**devices))
    await _unload(hass, entry)


async def test_an_install_with_no_device_has_no_entity_that_reads_unavailable(
    hass, hass_in_scenario, service_calls
):
    """Before this, an install with no EV charger had six sensors that were never available."""
    entry = await _setup(hass)
    registry = er.async_get(hass)
    unavailable = [
        registered.entity_id
        for registered in er.async_entries_for_config_entry(registry, entry.entry_id)
        if registered.disabled_by is None
        and hass.states.get(registered.entity_id).state == "unavailable"
    ]
    assert unavailable == []
    await _unload(hass, entry)


# ── a device that appears later ──────────────────────────────────────────────


async def test_a_charger_found_after_setup_brings_its_entities(hass, hass_in_scenario, service_calls):
    entry = await _setup(hass)
    assert _registered(hass, entry).isdisjoint(EV_KEYS)

    for entity_id, state in ZAPPI_STATES.items():
        hass.states.async_set(entity_id, state)
    await discover_the_charger(hass, entry)

    assert _states_exist(hass, entry, EV_KEYS)
    assert entry.state is ConfigEntryState.LOADED  # no reload, no restart
    await _unload(hass, entry)


async def test_a_charger_is_not_added_twice(hass, hass_in_scenario, service_calls):
    entry = await _setup(hass, charger=True)
    before = _registered(hass, entry)
    await discover_the_charger(hass, entry)
    await discover_the_charger(hass, entry)
    assert _registered(hass, entry) == before
    await _unload(hass, entry)


async def test_the_immersion_entities_arrive_when_the_options_name_the_devices(
    hass, hass_in_scenario, service_calls
):
    """The options change reloads the entry, and the reload creates what is now needed."""
    entry = await _setup(hass)
    assert _registered(hass, entry).isdisjoint(SWITCH_KEYS | SENSOR_KEYS | THERMOSTAT_KEYS)

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_IMMERSION_SWITCH: IMMERSION_SWITCH,
            CONF_IMMERSION_TEMP_SENSOR: IMMERSION_TEMP,
        },
    )
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert _states_exist(hass, entry, SWITCH_KEYS | SENSOR_KEYS | THERMOSTAT_KEYS)
    await _unload(hass, entry)


async def test_adding_only_the_switch_later_adds_its_entities_but_not_the_thermostat(
    hass, hass_in_scenario, service_calls
):
    entry = await _setup(hass, sensor=True)
    hass.config_entries.async_update_entry(
        entry, options={CONF_IMMERSION_SWITCH: IMMERSION_SWITCH}
    )
    await hass.async_block_till_done()

    registered = _registered(hass, entry)
    assert SWITCH_KEYS | SENSOR_KEYS | THERMOSTAT_KEYS <= registered
    await _unload(hass, entry)


# ── a device that goes ───────────────────────────────────────────────────────


async def test_removing_the_switch_removes_its_entities_from_the_registry(
    hass, hass_in_scenario, service_calls
):
    entry = await _setup(hass, switch=True, sensor=True)
    assert SWITCH_KEYS <= _registered(hass, entry)

    hass.config_entries.async_update_entry(entry, options={CONF_IMMERSION_SWITCH: ""})
    await hass.async_block_till_done()

    registered = _registered(hass, entry)
    assert registered.isdisjoint(SWITCH_KEYS | THERMOSTAT_KEYS)
    assert SENSOR_KEYS <= registered  # the sensor is still there
    await _unload(hass, entry)


async def test_removing_the_sensor_removes_the_temperature_entities(
    hass, hass_in_scenario, service_calls
):
    entry = await _setup(hass, switch=True, sensor=True)

    hass.config_entries.async_update_entry(entry, options={CONF_IMMERSION_TEMP_SENSOR: ""})
    await hass.async_block_till_done()

    registered = _registered(hass, entry)
    assert registered.isdisjoint(SENSOR_KEYS | THERMOSTAT_KEYS)
    assert SWITCH_KEYS <= registered
    await _unload(hass, entry)


async def test_a_charger_that_is_gone_loses_its_entities_at_the_next_reload(
    hass, hass_in_scenario, service_calls
):
    entry = await _setup(hass, charger=True)
    assert EV_KEYS <= _registered(hass, entry)

    for entity_id in ZAPPI_STATES:
        hass.states.async_remove(entity_id)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert _registered(hass, entry).isdisjoint(EV_KEYS)
    await _unload(hass, entry)


async def test_a_reload_keeps_the_charger_entities_and_their_ids(
    hass, hass_in_scenario, service_calls
):
    """A charger discovery has not counted yet must not lose its entities across a reload."""
    entry = await _setup(hass, charger=True)
    registry = er.async_get(hass)
    unique_id = f"{entry.entry_id}_ev_power"
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    registry.async_update_entity(entity_id, new_entity_id="sensor.my_car_charger_power")

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get_entity_id("sensor", DOMAIN, unique_id) == "sensor.my_car_charger_power"
    await _unload(hass, entry)


async def test_changing_a_temperature_slider_keeps_the_entities(hass, hass_in_scenario, service_calls):
    """The sliders write the entry data without a reload. Nothing is created or removed."""
    entry = await _setup(hass, switch=True, sensor=True)
    before = _registered(hass, entry)
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_IMMERSION_TARGET_TEMP: 60, CONF_IMMERSION_MIN_TEMP: 45},
    )
    await hass.async_block_till_done()
    assert _registered(hass, entry) == before
    await _unload(hass, entry)
