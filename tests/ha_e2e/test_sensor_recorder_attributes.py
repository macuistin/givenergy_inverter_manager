"""Report sensors keep their html attribute out of the recorder."""

from __future__ import annotations

from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import DOMAIN


async def test_html_attribute_is_flagged_unrecorded(hass, hass_in_scenario, service_calls, config_entry):
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{config_entry.entry_id}_today_summary",
        config_entry=config_entry,
        suggested_object_id="today_summary",
    )
    registry.async_update_entity(entity.entity_id, disabled_by=None)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(entity.entity_id)
    assert state is not None
    assert "html" in state.attributes
    assert "html" in state.state_info["unrecorded_attributes"]
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_the_charge_plan_is_enabled_on_a_new_install_and_keeps_html_unrecorded(
    hass, hass_in_scenario, service_calls, config_entry
):
    """Tonight's charge plan is on by default, and its large html stays out of the recorder."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{config_entry.entry_id}_charge_plan")
    assert registry.async_get(entity_id).disabled_by is None
    state = hass.states.get(entity_id)
    assert state is not None
    assert len(state.attributes["html"]) > 100
    assert "html" in state.state_info["unrecorded_attributes"]
    await hass.config_entries.async_unload(config_entry.entry_id)
