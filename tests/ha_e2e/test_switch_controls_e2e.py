"""The hand switches that act on the coordinator: skip the charge, auto immersion, and what the
managed immersion switch shows before there is data or after the immersion switch is cleared."""

from __future__ import annotations

import pytest
from conftest import MIDDAY
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    DOMAIN,
)

SKIP = "switch.givenergy_inverter_manager_force_skip_overnight_charge"
AUTO = "switch.immersion_auto_divert"
MANAGED = "switch.immersion_heater_managed"


@pytest.fixture
def scenario():
    return MIDDAY


async def _call(hass, service: str, entity_id: str) -> None:
    await hass.services.async_call("switch", service, {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()


async def test_the_skip_charge_switch_sets_and_clears_the_coordinator_override(
    hass, loaded_entry, service_calls
):
    coordinator = loaded_entry.runtime_data

    await _call(hass, "turn_on", SKIP)
    assert coordinator.override_skip_charge is True
    assert hass.states.get(SKIP).state == "on"

    await _call(hass, "turn_off", SKIP)
    assert coordinator.override_skip_charge is False
    assert hass.states.get(SKIP).state == "off"


async def test_the_auto_immersion_switch_hands_control_back_and_forth(
    hass, loaded_entry, service_calls
):
    coordinator = loaded_entry.runtime_data

    await _call(hass, "turn_off", AUTO)
    assert coordinator.override_immersion is False
    assert hass.states.get(AUTO).state == "off"

    await _call(hass, "turn_on", AUTO)
    assert coordinator.override_immersion is None
    assert hass.states.get(AUTO).state == "on"


async def test_the_managed_immersion_switch_reads_off_until_there_is_data(
    hass, loaded_entry, service_calls
):
    coordinator = loaded_entry.runtime_data
    coordinator.data = None

    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    assert hass.states.get(MANAGED).state == "off"


async def test_clearing_the_immersion_switch_removes_the_managed_switch(
    hass, loaded_entry, service_calls
):
    registry = er.async_get(hass)
    assert registry.async_get(MANAGED) is not None

    data = {
        k: v
        for k, v in loaded_entry.data.items()
        if k not in (CONF_IMMERSION_SWITCH, CONF_IMMERSION_TEMP_SENSOR)
    }
    hass.config_entries.async_update_entry(loaded_entry, data=data)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(MANAGED) is None
    assert DOMAIN in {e.domain for e in hass.config_entries.async_entries()}
