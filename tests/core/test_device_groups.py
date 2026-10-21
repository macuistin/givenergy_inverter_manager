"""Which Home Assistant device each optional device's entities belong to."""

from custom_components.givenergy_inverter_manager.core.devices import Device, DeviceGroup, group_of


def test_no_requirement_is_main():
    assert group_of(None) is DeviceGroup.MAIN
    assert group_of(Device.ALTERNATIVE_HEAT) is DeviceGroup.MAIN


def test_ev_charger_has_its_own_group():
    assert group_of(Device.EV_CHARGER) is DeviceGroup.EV_CHARGER


def test_immersion_devices_share_one_group():
    for device in (Device.IMMERSION_SWITCH, Device.IMMERSION_SENSOR, Device.IMMERSION_THERMOSTAT):
        assert group_of(device) is DeviceGroup.IMMERSION
