"""The immersion switch and temperature sensor are optional and can be added or removed later.

Real Home Assistant, real options flow. Nothing restarts: the update listener reloads the entry
and the managed switch entity and the Immersion dashboard view follow the configuration.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import IMMERSION_SWITCH, IMMERSION_TEMP, MIDDAY, SERIAL, full_config_data
from homeassistant.components.switch import DATA_COMPONENT
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    DOMAIN,
)
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


def _form_values(fields: list[dict]) -> dict:
    """What the frontend submits untouched: defaults and suggested values, section by section."""
    values: dict = {}
    for field in fields:
        if field.get("type") == "expandable":
            values[field["name"]] = _form_values(field["schema"])
        elif "default" in field:
            values[field["name"]] = field["default"]
        elif "suggested_value" in field.get("description", {}):
            values[field["name"]] = field["description"]["suggested_value"]
    return values


async def save_options(hass, entry, immersion: dict | None = None, unsent: bool = False) -> None:
    """Open the options form and save it as the frontend would.

    *immersion* replaces the entity choices of the immersion section ({} clears both). With
    *unsent*, the section is left out of the submission altogether.
    """
    result = await hass.config_entries.options.async_init(entry.entry_id)
    fields = cv.to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    payload = _form_values(fields)
    if unsent:
        del payload["immersion_settings"]
    elif immersion is not None:
        wattage = payload["immersion_settings"]["immersion_wattage_w"]
        payload["immersion_settings"] = {"immersion_wattage_w": wattage, **immersion}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=payload
    )
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
    async_mock_service(hass, "persistent_notification", "create")
    await hass.services.async_call(DOMAIN, "get_dashboard_yaml", blocking=True)
    await hass.async_block_till_done()
    text = (Path(hass.config.config_dir) / "givenergy_dashboard.yaml").read_text(encoding="utf-8")
    states = {state.entity_id: state.state for state in hass.states.async_all()}
    shown = seen(yaml.safe_load(text), states)
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


class TestUnsentSection:
    @pytest.fixture
    def config_entry(self):
        return _entry(full_config_data())

    async def test_a_submission_without_the_section_keeps_the_devices(self, hass, loaded_entry):
        await save_options(hass, loaded_entry, unsent=True)

        assert CONF_IMMERSION_SWITCH not in loaded_entry.options
        assert managed_switch_id(hass, loaded_entry) is not None
        assert "immersion" in await dashboard_paths(hass)

    async def test_an_untouched_form_keeps_the_devices(self, hass, loaded_entry):
        await save_options(hass, loaded_entry)

        assert managed_switch_id(hass, loaded_entry) is not None
        assert loaded_entry.runtime_data.immersion._ports.switch_entity() == IMMERSION_SWITCH
