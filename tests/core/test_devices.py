"""Which optional devices an install has: the EV charger, the immersion switch and sensor."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_ALT_HEAT_COST,
    CONF_ALT_HEAT_COST_ENTITY,
    CONF_ALT_HEAT_ENABLED,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
)
from custom_components.givenergy_inverter_manager.core.devices import (
    Device,
    alt_heat_configured,
    alt_heat_warnings,
    installed_devices,
)

SWITCH = {CONF_IMMERSION_SWITCH: "switch.heater"}
SENSOR = {CONF_IMMERSION_TEMP_SENSOR: "sensor.cylinder"}
ON = {CONF_ALT_HEAT_ENABLED: True}
COST = {CONF_ALT_HEAT_COST: 0.95}
COST_SENSOR = {CONF_ALT_HEAT_COST_ENTITY: "sensor.heat_cost"}


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
    everything = installed_devices({**SWITCH, **SENSOR, **ON, **COST}, ev_charger_found=True)
    assert everything == frozenset(Device)


def test_a_cost_alone_is_no_device():
    """The advice compares the alternative with the immersion, so it needs a heater to compare with."""
    assert installed_devices({**ON, **COST}, ev_charger_found=False) == frozenset()


def test_a_switch_alone_has_no_alternative_heat_advice():
    assert Device.ALTERNATIVE_HEAT not in installed_devices(SWITCH, ev_charger_found=False)


@pytest.mark.parametrize("cost", [COST, COST_SENSOR, {**COST, **COST_SENSOR}])
def test_on_with_a_cost_and_a_switch_give_the_advice(cost):
    devices = installed_devices({**SWITCH, **ON, **cost}, ev_charger_found=False)
    assert devices == {Device.IMMERSION_SWITCH, Device.ALTERNATIVE_HEAT}


@pytest.mark.parametrize("cost", [COST, COST_SENSOR])
def test_a_cost_with_the_setting_off_gives_no_advice(cost):
    config = {**SWITCH, CONF_ALT_HEAT_ENABLED: False, **cost}
    assert Device.ALTERNATIVE_HEAT not in installed_devices(config, ev_charger_found=False)


def test_a_cost_with_the_setting_never_saved_gives_no_advice():
    assert Device.ALTERNATIVE_HEAT not in installed_devices(
        {**SWITCH, **COST}, ev_charger_found=False
    )


def test_on_with_a_switch_and_no_cost_gives_no_advice():
    assert Device.ALTERNATIVE_HEAT not in installed_devices(
        {**SWITCH, **ON}, ev_charger_found=False
    )


@pytest.mark.parametrize("empty", [None, "", 0, 0.0])
def test_an_unset_cost_is_no_advice(empty):
    config = {**SWITCH, **ON, CONF_ALT_HEAT_COST: empty, CONF_ALT_HEAT_COST_ENTITY: empty}
    assert Device.ALTERNATIVE_HEAT not in installed_devices(config, ev_charger_found=False)


class TestConfigured:
    def test_it_needs_the_setting_on_and_a_cost_or_a_sensor(self):
        assert alt_heat_configured({**ON, **COST})
        assert alt_heat_configured({**ON, **COST_SENSOR})
        assert not alt_heat_configured(COST)
        assert not alt_heat_configured(ON)
        assert not alt_heat_configured({})

    def test_it_does_not_need_the_switch(self):
        assert alt_heat_configured({**ON, **COST}) is True


class TestWarnings:
    def test_a_complete_setting_has_none(self):
        assert alt_heat_warnings({**SWITCH, **ON, **COST}) == []

    def test_off_has_none_whatever_is_missing(self):
        assert alt_heat_warnings({}) == []
        assert alt_heat_warnings({CONF_ALT_HEAT_ENABLED: False}) == []

    def test_on_without_a_switch_says_so(self):
        assert alt_heat_warnings({**ON, **COST}) == ["no advice until an immersion switch is set"]

    def test_on_without_a_cost_says_so(self):
        assert alt_heat_warnings({**SWITCH, **ON}) == ["no advice until a cost is set"]

    def test_on_with_neither_says_both(self):
        assert len(alt_heat_warnings(ON)) == 2

    def test_a_cost_sensor_counts_as_a_cost(self):
        assert alt_heat_warnings({**SWITCH, **ON, **COST_SENSOR}) == []
