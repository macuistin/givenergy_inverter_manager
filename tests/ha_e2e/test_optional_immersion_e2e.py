"""The immersion switch and temperature sensor are optional and can be added or removed later.

Real Home Assistant, real options flow. Nothing restarts: the update listener reloads the entry
and the managed switch entity and the Immersion dashboard view follow the configuration.
"""

from __future__ import annotations

import pytest
from conftest import (
    IMMERSION_SWITCH,
    IMMERSION_TEMP,
    MIDDAY,
    SERIAL,
    full_config_data,
)
from homeassistant.components.switch import DATA_COMPONENT
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service
from wizard_support import options_wizard

from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    DOMAIN,
)
from custom_components.givenergy_inverter_manager.strategy import async_dashboard_for_websocket
from tests.dashboard_visibility import seen

MANAGED = "immersion_managed"
OTHER_SWITCH = "switch.second_heater"


@pytest.fixture
def scenario():
    return MIDDAY


def _entry(data: dict) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=data,
        unique_id=SERIAL,
        version=1,
    )


def _config_without_immersion() -> dict:
    data = full_config_data()
    data.pop(CONF_IMMERSION_SWITCH)
    data.pop(CONF_IMMERSION_TEMP_SENSOR)
    return data


async def save_options(hass, entry, immersion: dict | None = None) -> None:
    """Run the options wizard's hot water page as the frontend would.

    *immersion* replaces the entity choices ({} clears both, as the frontend leaves out an
    emptied selector). Without it the page is submitted untouched.
    """
    values: dict = {}
    if immersion is not None:
        values = {CONF_IMMERSION_SWITCH: None, CONF_IMMERSION_TEMP_SENSOR: None, **immersion}
    result = await options_wizard(hass, entry, {"hot_water": values})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    assert entry.state is ConfigEntryState.LOADED


def managed_switch_id(hass, entry) -> str | None:
    """The entity ID of the managed immersion switch, or None when it is not registered."""
    return er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_{MANAGED}")


async def dashboard_paths(hass) -> set[str]:
    """Paths of the views the generated dashboard shows right now.

    A device's view is always in the file, with its sections hidden by visibility conditions
    until the device exists, so a view counts when something in it is shown.
    """
    dashboard = await async_dashboard_for_websocket(hass, is_admin=True)
    states = {state.entity_id: state.state for state in hass.states.async_all()}
    shown = seen(dashboard, states)
    return {view["path"] for view in shown["views"] if view["sections"]}


class TestSwitchSavedInOptions:
    @pytest.fixture
    def config_entry(self):
        return _entry(_config_without_immersion())

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


class TestAddingDevicesLater:
    @pytest.fixture
    def config_entry(self):
        return _entry(_config_without_immersion())

    async def test_nothing_immersion_related_exists_at_first(self, hass, loaded_entry):
        assert managed_switch_id(hass, loaded_entry) is None
        assert "immersion" not in await dashboard_paths(hass)

    async def test_adding_both_devices_creates_the_switch_and_the_view(self, hass, loaded_entry):
        await save_options(
            hass,
            loaded_entry,
            immersion={
                CONF_IMMERSION_SWITCH: IMMERSION_SWITCH,
                CONF_IMMERSION_TEMP_SENSOR: IMMERSION_TEMP,
            },
        )

        assert managed_switch_id(hass, loaded_entry) is not None
        assert "immersion" in await dashboard_paths(hass)
        assert loaded_entry.options[CONF_IMMERSION_SWITCH] == IMMERSION_SWITCH
        assert loaded_entry.options[CONF_IMMERSION_TEMP_SENSOR] == IMMERSION_TEMP

    async def test_added_switch_is_the_one_the_actuator_drives(self, hass, loaded_entry):
        await save_options(hass, loaded_entry, immersion={CONF_IMMERSION_SWITCH: IMMERSION_SWITCH})
        turn_on_calls = async_mock_service(hass, "switch", "turn_on")

        managed = managed_switch_id(hass, loaded_entry)
        await hass.data[DATA_COMPONENT].get_entity(managed).async_turn_on()
        await hass.async_block_till_done()

        assert [call.data["entity_id"] for call in turn_on_calls] == [IMMERSION_SWITCH]

    async def test_adding_only_the_sensor_gives_the_view_but_no_managed_switch(
        self, hass, loaded_entry
    ):
        await save_options(
            hass, loaded_entry, immersion={CONF_IMMERSION_TEMP_SENSOR: IMMERSION_TEMP}
        )

        assert managed_switch_id(hass, loaded_entry) is None
        assert "immersion" in await dashboard_paths(hass)


class TestRemovingDevices:
    @pytest.fixture
    def config_entry(self):
        return _entry(full_config_data())

    async def test_both_devices_are_there_to_start_with(self, hass, loaded_entry):
        assert managed_switch_id(hass, loaded_entry) is not None
        assert "immersion" in await dashboard_paths(hass)

    async def test_clearing_both_removes_the_switch_and_the_view(self, hass, loaded_entry):
        await save_options(hass, loaded_entry, immersion={})

        assert managed_switch_id(hass, loaded_entry) is None
        assert hass.states.get("switch.givenergy_inverter_manager_immersion_heater_managed") is None
        assert "immersion" not in await dashboard_paths(hass)
        assert not loaded_entry.runtime_data.immersion._ports.switch_entity()

    async def test_a_cleared_heater_is_no_longer_commanded(self, hass, loaded_entry):
        await save_options(hass, loaded_entry, immersion={})
        turn_on_calls = async_mock_service(hass, "switch", "turn_on")
        turn_off_calls = async_mock_service(hass, "switch", "turn_off")
        hass.states.async_set(IMMERSION_TEMP, 40.0)  # would force the heater on if it were set

        await loaded_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

        assert turn_on_calls == []
        assert turn_off_calls == []

    async def test_clearing_only_the_sensor_keeps_the_switch(self, hass, loaded_entry):
        await save_options(hass, loaded_entry, immersion={CONF_IMMERSION_SWITCH: IMMERSION_SWITCH})

        assert managed_switch_id(hass, loaded_entry) is not None
        assert "immersion" in await dashboard_paths(hass)

    async def test_the_removed_switch_comes_back_when_it_is_added_again(self, hass, loaded_entry):
        await save_options(hass, loaded_entry, immersion={})
        await save_options(hass, loaded_entry, immersion={CONF_IMMERSION_SWITCH: IMMERSION_SWITCH})

        assert managed_switch_id(hass, loaded_entry) is not None
        assert "immersion" in await dashboard_paths(hass)

    async def test_changing_the_switch_moves_control_to_the_new_one(self, hass, loaded_entry):
        await save_options(hass, loaded_entry, immersion={CONF_IMMERSION_SWITCH: OTHER_SWITCH})
        turn_on_calls = async_mock_service(hass, "switch", "turn_on")

        managed = managed_switch_id(hass, loaded_entry)
        await hass.data[DATA_COMPONENT].get_entity(managed).async_turn_on()
        await hass.async_block_till_done()

        assert [call.data["entity_id"] for call in turn_on_calls] == [OTHER_SWITCH]


class TestUnticked:
    @pytest.fixture
    def config_entry(self):
        return _entry(full_config_data())

    async def test_a_page_that_was_not_ticked_keeps_the_devices(self, hass, loaded_entry):
        result = await options_wizard(hass, loaded_entry, {"battery": {"battery_min_soc_pct": 12}})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert CONF_IMMERSION_SWITCH not in loaded_entry.options
        assert CONF_IMMERSION_TEMP_SENSOR not in loaded_entry.options
        assert managed_switch_id(hass, loaded_entry) is not None
        assert "immersion" in await dashboard_paths(hass)

    async def test_an_untouched_hot_water_page_keeps_the_devices(self, hass, loaded_entry):
        await save_options(hass, loaded_entry)

        assert managed_switch_id(hass, loaded_entry) is not None
        assert loaded_entry.runtime_data.immersion._ports.switch_entity() == IMMERSION_SWITCH
        assert CONF_IMMERSION_SWITCH not in loaded_entry.options
