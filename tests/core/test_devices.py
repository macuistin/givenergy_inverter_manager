"""Which optional devices an install has: the EV charger, the immersion switch and sensor."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
)
from custom_components.givenergy_inverter_manager.core.devices import Device, installed_devices

SWITCH = {CONF_IMMERSION_SWITCH: "switch.heater"}
SENSOR = {CONF_IMMERSION_TEMP_SENSOR: "sensor.cylinder"}


def test_an_install_with_nothing_has_no_device():
    assert installed_devices({}, ev_charger_found=False) == frozenset()


def test_a_discovered_charger_is_the_ev_device():
    assert installed_devices({}, ev_charger_found=True) == {Device.EV_CHARGER}


def test_a_switch_alone_is_only_the_switch():
    assert installed_devices(SWITCH, ev_charger_found=False) == {Device.IMMERSION_SWITCH}


def test_a_sensor_alone_is_only_the_sensor():
    assert installed_devices(SENSOR, ev_charger_found=False) == {Device.IMMERSION_SENSOR}


def test_the_thermostat_needs_the_switch_and_the_sensor():
    both = installed_devices({**SWITCH, **SENSOR}, ev_charger_found=False)
    assert both == {Device.IMMERSION_SWITCH, Device.IMMERSION_SENSOR, Device.IMMERSION_THERMOSTAT}


@pytest.mark.parametrize("empty", [None, "", []])
def test_an_unset_entity_is_not_a_device(empty):
    config = {CONF_IMMERSION_SWITCH: empty, CONF_IMMERSION_TEMP_SENSOR: empty}
    assert installed_devices(config, ev_charger_found=False) == frozenset()


def test_the_devices_do_not_depend_on_each_other_apart_from_the_thermostat():
    everything = installed_devices({**SWITCH, **SENSOR}, ev_charger_found=True)
    assert everything == frozenset(Device)
