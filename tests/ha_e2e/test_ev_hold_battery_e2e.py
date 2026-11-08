"""The Hold Battery While EV Charges switch against a real Home Assistant.

It is a saved setting of the EV charger, so it exists with a charger and not without, shows off
until it is turned on, saves its flag without reloading, and keeps the value across a reload.
"""

from __future__ import annotations

import pytest
from conftest import MIDDAY
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import CONF_EV_HOLD_BATTERY, DOMAIN

ENTITY = "switch.ev_charger_hold_battery_while_ev_charges"


@pytest.fixture
def scenario():
    return MIDDAY


async def test_an_install_without_a_charger_has_no_hold_switch(hass, loaded_entry):
    assert er.async_get(hass).async_get(ENTITY) is None


async def test_the_switch_is_on_until_it_is_turned_off(hass, loaded_entry_with_charger):
    entry = loaded_entry_with_charger

    assert hass.states.get(ENTITY).state == STATE_ON
    assert entry.options.get(CONF_EV_HOLD_BATTERY, True)

    await hass.services.async_call("switch", "turn_off", {"entity_id": ENTITY}, blocking=True)
    await hass.async_block_till_done()

    assert entry.options[CONF_EV_HOLD_BATTERY] is False
    assert hass.states.get(ENTITY).state == STATE_OFF


async def test_turning_it_off_does_not_reload_the_entry_and_the_value_survives_a_reload(
    hass, loaded_entry_with_charger
):
    entry = loaded_entry_with_charger
    coordinator = entry.runtime_data

    await hass.services.async_call("switch", "turn_off", {"entity_id": ENTITY}, blocking=True)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is coordinator

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY).state == STATE_OFF


async def test_the_switch_belongs_to_the_ev_charger_device(hass, loaded_entry_with_charger):
    registry = er.async_get(hass)
    hold = registry.async_get(ENTITY)
    pause = registry.async_get("switch.ev_charger_pause_charging")

    assert hold.platform == DOMAIN
    assert hold.device_id == pause.device_id
