"""The immersion switch and temperature sensor are optional and can be added or removed later.

Real Home Assistant, real options flow. Nothing restarts: the update listener reloads the entry
and the managed switch entity and the Immersion dashboard view follow the configuration.
"""

from __future__ import annotations

import pytest
from conftest import IMMERSION_SWITCH, MIDDAY, SERIAL, full_config_data
from homeassistant.components.switch import DATA_COMPONENT
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    DOMAIN,
)

MANAGED = "immersion_managed"


@pytest.fixture
def scenario():
    return MIDDAY


def _config_without_immersion() -> dict:
    data = full_config_data()
    data.pop(CONF_IMMERSION_SWITCH)
    data.pop(CONF_IMMERSION_TEMP_SENSOR)
    return data


@pytest.fixture
def config_entry():
    """An entry set up with no immersion switch and no temperature sensor."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=_config_without_immersion(),
        unique_id=SERIAL,
        version=1,
    )


def managed_switch_id(hass, entry) -> str | None:
    """The entity ID of the managed immersion switch, or None when it is not registered."""
    return er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_{MANAGED}")


class TestSwitchSavedInOptions:
    async def test_managed_switch_is_absent_without_a_configured_switch(self, hass, loaded_entry):
        assert managed_switch_id(hass, loaded_entry) is None

    async def test_options_value_creates_the_managed_switch_and_drives_the_real_one(
        self, hass_in_scenario, config_entry
    ):
        """A switch that exists only in options (not in setup data) is the one controlled."""
        hass = hass_in_scenario
        config_entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(
            config_entry, options={CONF_IMMERSION_SWITCH: IMMERSION_SWITCH}
        )
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        managed = managed_switch_id(hass, config_entry)
        assert managed is not None
        # Registered after setup, because the switch platform registers its own services.
        turn_on_calls = async_mock_service(hass, "switch", "turn_on")
        await hass.data[DATA_COMPONENT].get_entity(managed).async_turn_on()
        await hass.async_block_till_done()

        assert [call.data["entity_id"] for call in turn_on_calls] == [IMMERSION_SWITCH]
        await hass.config_entries.async_unload(config_entry.entry_id)
        assert config_entry.state is ConfigEntryState.NOT_LOADED
