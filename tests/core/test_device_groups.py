"""Which Home Assistant device each optional device's entities belong to."""

from custom_components.givenergy_inverter_manager.core.devices import (
    Device,
    DeviceGroup,
    group_of,
    group_present,
)


def test_no_requirement_is_main():
    assert group_of(None) is DeviceGroup.MAIN
    assert group_of(Device.ALTERNATIVE_HEAT) is DeviceGroup.MAIN


def test_ev_charger_has_its_own_group():
    assert group_of(Device.EV_CHARGER) is DeviceGroup.EV_CHARGER


def test_immersion_devices_share_one_group():
    for device in (Device.IMMERSION_SWITCH, Device.IMMERSION_SENSOR, Device.IMMERSION_THERMOSTAT):
        assert group_of(device) is DeviceGroup.IMMERSION


def test_the_main_device_is_always_there():
    assert group_present(DeviceGroup.MAIN, frozenset())


def test_a_group_is_there_while_any_of_its_hardware_is():
    assert not group_present(DeviceGroup.IMMERSION, frozenset({Device.EV_CHARGER}))
    assert group_present(DeviceGroup.IMMERSION, frozenset({Device.IMMERSION_SENSOR}))
    assert group_present(DeviceGroup.EV_CHARGER, frozenset({Device.EV_CHARGER}))
    assert not group_present(DeviceGroup.EV_CHARGER, frozenset())
