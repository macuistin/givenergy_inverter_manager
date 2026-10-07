"""The shared entity base gives every platform the same device.

The sensor platform cannot be imported under the stubbed Home Assistant, so the real
Home Assistant suite (tests/ha_e2e) checks its device.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.givenergy_inverter_manager import button, number, switch
from custom_components.givenergy_inverter_manager.const import (
    DEVICE_MANUFACTURER,
    DOMAIN,
    INTEGRATION_VERSION,
    NAME,
    SERVICE_GET_DASHBOARD_YAML,
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
        button.GivEnergyRefreshDashboardButton(coord),
    ]


@pytest.mark.parametrize("entity", _entities(), ids=lambda e: type(e).__name__)
def test_every_entity_uses_the_shared_base_and_device(entity):
    assert isinstance(entity, GivEnergyEntity)
    assert entity._attr_has_entity_name is True
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
    assert ids["GivEnergyRefreshDashboardButton"] == f"{ENTRY_ID}_refresh_dashboard"


def test_refresh_button_stays_available_when_the_coordinator_fails():
    coord = _coordinator()
    coord.last_update_success = False

    assert button.GivEnergyRefreshDashboardButton(coord).available is True


async def test_pressing_the_refresh_button_calls_the_dashboard_service():
    coord = _coordinator()
    coord.hass.services.async_call = AsyncMock()

    await button.GivEnergyRefreshDashboardButton(coord).async_press()

    coord.hass.services.async_call.assert_awaited_once_with(
        DOMAIN, SERVICE_GET_DASHBOARD_YAML, blocking=True
    )
