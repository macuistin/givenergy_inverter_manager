"""Setup deletes the registry entry of the retired Refresh Dashboard button.

The button pressed the get_dashboard_yaml action, which wrote a YAML file. The dashboard is a
strategy that builds itself, so both are gone. An upgrade must not leave the button behind as an
entity that is no longer provided.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager import _RETIRED_BUTTON_KEYS
from custom_components.givenergy_inverter_manager.const import DOMAIN


def test_the_cleanup_list_holds_the_refresh_button():
    assert _RETIRED_BUTTON_KEYS == ("refresh_dashboard",)


async def test_a_fresh_install_never_creates_the_button(hass, loaded_entry):
    registry = er.async_get(hass)
    unique_id = f"{loaded_entry.entry_id}_refresh_dashboard"
    assert registry.async_get_entity_id("button", DOMAIN, unique_id) is None
    assert not hass.states.async_entity_ids("button")


async def test_setup_removes_the_button_an_older_version_registered(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    stale = registry.async_get_or_create(
        "button", DOMAIN, f"{config_entry.entry_id}_refresh_dashboard", config_entry=config_entry
    )
    assert registry.async_get(stale.entity_id)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert registry.async_get(stale.entity_id) is None


async def test_setup_leaves_a_button_of_another_integration_alone(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    other = registry.async_get_or_create("button", "someone_else", "refresh_dashboard")

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(other.entity_id) is not None
