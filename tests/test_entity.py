"""The shared entity base gives every platform the same device.

The sensor platform cannot be imported under the stubbed Home Assistant, so the real
Home Assistant suite (tests/ha_e2e) checks its device.
"""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager import number, switch
from custom_components.givenergy_inverter_manager.const import (
    DEVICE_MANUFACTURER,
    DOMAIN,
    INTEGRATION_VERSION,
    NAME,
)
from custom_components.givenergy_inverter_manager.entity import GivEnergyEntity
from tests.test_coordinator import FakeCoordinator, _cfg

ENTRY_ID = "entry-123"


def _coordinator():
    coord = FakeCoordinator(cfg=_cfg())
    coord.entry.entry_id = ENTRY_ID
    return coord


def _entities():
    coord = _coordinator()
    return [
        switch.GivEnergyAutoImmersionSwitch(coord),
        switch.GivEnergyImmersionControlSwitch(coord),
        switch.GivEnergySkipChargeOverrideSwitch(coord),
        switch.GivEnergyChargeTargetOverrideSwitch(coord),
        number.GivEnergyChargeTargetOverride(coord),
        number.ImmersionTargetTempNumber(coord),
        number.ImmersionMinTempNumber(coord),
        number.ImmersionHysteresisNumber(coord),
    ]


_IMMERSION_ENTITIES = {
    "GivEnergyAutoImmersionSwitch",
    "GivEnergyImmersionControlSwitch",
    "ImmersionTargetTempNumber",
    "ImmersionMinTempNumber",
    "ImmersionHysteresisNumber",
}


@pytest.mark.parametrize("entity", _entities(), ids=lambda e: type(e).__name__)
def test_every_entity_uses_the_shared_base_and_a_device(entity):
    assert isinstance(entity, GivEnergyEntity)
    assert entity._attr_has_entity_name is True
    if type(entity).__name__ in _IMMERSION_ENTITIES:
        assert entity._attr_device_info == {
            "identifiers": {(DOMAIN, f"{ENTRY_ID}_immersion")},
            "name": "Immersion",
            "manufacturer": DEVICE_MANUFACTURER,
            "model": "Immersion",
            "via_device": (DOMAIN, ENTRY_ID),
        }
    else:
        assert entity._attr_device_info == {
            "identifiers": {(DOMAIN, ENTRY_ID)},
            "name": NAME,
            "manufacturer": DEVICE_MANUFACTURER,
            "model": "Inverter Manager",
            "sw_version": INTEGRATION_VERSION,
        }


def test_device_name_is_unchanged():
    """Renaming NAME would rename the device in existing installs."""
    assert NAME == "GivEnergy Inverter Manager"


def test_unique_ids_are_unchanged():
    ids = {type(e).__name__: e._attr_unique_id for e in _entities()}
    assert ids["GivEnergyAutoImmersionSwitch"] == f"{ENTRY_ID}_auto_immersion"
    assert ids["GivEnergyImmersionControlSwitch"] == f"{ENTRY_ID}_immersion_managed"
    assert ids["GivEnergySkipChargeOverrideSwitch"] == f"{ENTRY_ID}_skip_charge_override"
    assert (
        ids["GivEnergyChargeTargetOverrideSwitch"]
        == f"{ENTRY_ID}_charge_target_override_enabled"
    )
    assert ids["GivEnergyChargeTargetOverride"] == f"{ENTRY_ID}_charge_target_override"
