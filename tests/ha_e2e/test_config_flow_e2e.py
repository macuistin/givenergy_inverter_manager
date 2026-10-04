"""Config flow against a real flow manager, with and without discovered GivTCP inverters."""

from __future__ import annotations

from conftest import (
    BATTERY_POWER,
    GRID,
    LOAD,
    MIDDAY,
    SERIAL,
    SOC,
    SOLAR,
    set_givtcp_states,
)
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType

from custom_components.givenergy_inverter_manager.const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_INVERTER_SERIAL,
    CONF_SOLAR_POWER,
    DOMAIN,
)

MANUAL_INPUT = {
    "discovered_inverter": "__manual__",
    CONF_SOLAR_POWER: SOLAR,
    CONF_BATTERY_SOC: SOC,
    CONF_BATTERY_POWER: BATTERY_POWER,
    CONF_GRID_POWER: GRID,
    CONF_HOUSE_LOAD: LOAD,
    CONF_BATTERY_CAPACITY: 9.5,
}


async def test_manual_path_without_discovered_inverters_reaches_tariff(hass):
    """(e) No GivTCP entities in HA: the manual form is shown and submitting it opens tariff."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "inverter"
    assert result["description_placeholders"]["discovered_count"] == "0"
    # Manual form: the five entity selectors are required.
    required = {str(k) for k in result["data_schema"].schema if k.__class__.__name__ == "Required"}
    assert {CONF_SOLAR_POWER, CONF_BATTERY_SOC, CONF_GRID_POWER} <= required

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MANUAL_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "tariff"
    hass.config_entries.flow.async_abort(result["flow_id"])


async def test_manual_wizard_creates_a_loading_entry(hass, hass_in_scenario, service_calls):
    """Walk every wizard step with defaults and check the created entry sets up."""
    # Only the five power sensors exist, so nothing is auto-discovered.
    for entity_id in list(hass.states.async_entity_ids()):
        if entity_id not in {SOLAR, SOC, BATTERY_POWER, GRID, LOAD}:
            hass.states.async_remove(entity_id)

    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await flow.async_configure(result["flow_id"], user_input=MANUAL_INPUT)
    for step in ("tariff", "forecast", "immersion", "ev", "battery"):
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == step
        result = await flow.async_configure(result["flow_id"], user_input={})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    try:
        assert entry.unique_id
        assert entry.data[CONF_INVERTER_SERIAL] == entry.unique_id
        assert entry.state is ConfigEntryState.LOADED
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_discovered_inverter_is_offered_and_creates_entry(
    hass, hass_in_scenario, service_calls
):
    """With GivTCP entities present the confirm form is shown and the serial becomes the unique ID."""
    set_givtcp_states(hass, MIDDAY)
    flow = hass.config_entries.flow

    result = await flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["step_id"] == "inverter"
    assert result["description_placeholders"]["discovered_count"] == "1"

    result = await flow.async_configure(
        result["flow_id"], user_input={"discovered_inverter": SERIAL, CONF_BATTERY_CAPACITY: 9.5}
    )
    assert result["step_id"] == "tariff"
    for _ in ("tariff", "forecast", "immersion", "ev", "battery"):
        result = await flow.async_configure(result["flow_id"], user_input={})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    try:
        assert entry.unique_id == SERIAL
        assert entry.data[CONF_SOLAR_POWER] == SOLAR
        assert entry.state is ConfigEntryState.LOADED
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    # A second flow for the same inverter is refused.
    again = await flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    again = await flow.async_configure(
        again["flow_id"], user_input={"discovered_inverter": SERIAL, CONF_BATTERY_CAPACITY: 9.5}
    )
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "already_configured"
