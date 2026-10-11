"""Reconfigure is the inverter connection: remap the GivTCP entities, with one reload.

The tariff is edited in the options wizard (tests/ha_e2e/test_options_flow_e2e.py and
test_dated_tariff_e2e.py).
"""

from __future__ import annotations

import logging

import pytest
from conftest import BATTERY_POWER, GRID, LOAD, MIDDAY, SERIAL, SOC, SOLAR
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from wizard_support import field_names, serialised, submit

import custom_components.givenergy_inverter_manager as integration
from custom_components.givenergy_inverter_manager.const import (
    CONF_BASE_RATE,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_CHARGE_END_TIME_ENTITY,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_INVERTER_TEMP_ENTITY,
    CONF_SOLAR_POWER,
    CONF_TARGET_SOC_ENTITY,
)

OTHER_SOLAR = "sensor.rewired_solar"
OTHER_GRID = "sensor.rewired_grid"


@pytest.fixture
def scenario():
    return MIDDAY


@pytest.fixture
def setups(monkeypatch) -> list[str]:
    """Record every time the integration is set up."""
    calls: list[str] = []
    real = integration.async_setup_entry

    async def counting(hass, entry):
        calls.append(entry.entry_id)
        return await real(hass, entry)

    monkeypatch.setattr(integration, "async_setup_entry", counting)
    return calls


def flow(hass):
    return hass.config_entries.flow


def five(**changes) -> dict:
    mapping = {
        CONF_SOLAR_POWER: SOLAR,
        CONF_BATTERY_SOC: SOC,
        CONF_BATTERY_POWER: BATTERY_POWER,
        CONF_GRID_POWER: GRID,
        CONF_HOUSE_LOAD: LOAD,
    }
    return {**mapping, **changes}


async def manual_form(hass, entry):
    result = await entry.start_reconfigure_flow(hass)
    return await submit(flow(hass), result, source="manual")


def publish_rewired_sensors(hass) -> None:
    hass.states.async_set(OTHER_SOLAR, 1200, {"unit_of_measurement": "W"})
    hass.states.async_set(OTHER_GRID, -300, {"unit_of_measurement": "W"})


async def test_the_form_shows_the_mapping_in_force_next_to_what_discovery_finds(
    hass, loaded_entry
):
    result = await loaded_entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    placeholders = result["description_placeholders"]
    assert f"solar_power_entity: {SOLAR}" in placeholders["current"]
    assert f"solar_power_entity: {SOLAR}" in placeholders["found"]
    fields = serialised(result)
    assert [f["name"] for f in fields] == ["source"]
    assert fields[0]["default"] == "found"
    assert fields[0]["selector"]["select"]["options"] == ["found", "manual"]
    flow(hass).async_abort(result["flow_id"])


async def test_without_a_discovered_inverter_only_the_manual_choice_is_offered(hass, loaded_entry):
    for entity_id in list(hass.states.async_entity_ids()):
        if "givtcp" in entity_id and entity_id not in {SOLAR, SOC, BATTERY_POWER, GRID, LOAD}:
            hass.states.async_remove(entity_id)
    result = await loaded_entry.start_reconfigure_flow(hass)

    assert "Nothing was found" in result["description_placeholders"]["found"]
    (field,) = serialised(result)
    assert field["selector"]["select"]["options"] == ["manual"]
    assert field["default"] == "manual"
    flow(hass).async_abort(result["flow_id"])


async def test_using_what_was_found_changes_nothing_when_it_matches(hass, loaded_entry, setups):
    before = dict(loaded_entry.data)
    result = await loaded_entry.start_reconfigure_flow(hass)

    result = await submit(flow(hass), result)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert dict(loaded_entry.data) == before
    assert setups == []
    assert loaded_entry.state is ConfigEntryState.LOADED


async def test_using_what_was_found_remaps_a_wiring_that_has_drifted_and_reloads_once(
    hass, loaded_entry, setups
):
    hass.config_entries.async_update_entry(
        loaded_entry, data={**loaded_entry.data, CONF_SOLAR_POWER: OTHER_SOLAR}
    )
    await hass.async_block_till_done()
    setups.clear()
    result = await loaded_entry.start_reconfigure_flow(hass)

    result = await submit(flow(hass), result)
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert loaded_entry.data[CONF_SOLAR_POWER] == SOLAR
    assert len(setups) == 1
    assert loaded_entry.state is ConfigEntryState.LOADED


async def test_a_manual_remap_is_saved_and_reloads_once(hass, loaded_entry, setups, caplog):
    publish_rewired_sensors(hass)
    result = await manual_form(hass, loaded_entry)
    assert result["step_id"] == "reconfigure_manual"
    defaults = {
        f["name"]: (f.get("description") or {}).get("suggested_value") for f in serialised(result)
    }
    assert defaults[CONF_SOLAR_POWER] == SOLAR

    with caplog.at_level(logging.WARNING):
        result = await submit(
            flow(hass), result, **five(**{CONF_SOLAR_POWER: OTHER_SOLAR, CONF_GRID_POWER: OTHER_GRID})
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert loaded_entry.data[CONF_SOLAR_POWER] == OTHER_SOLAR
    assert loaded_entry.data[CONF_GRID_POWER] == OTHER_GRID
    assert len(setups) == 1
    assert loaded_entry.state is ConfigEntryState.LOADED
    assert loaded_entry.runtime_data.last_update_success
    assert "update listener" not in caplog.text


async def test_reconfigure_leaves_the_tariff_the_options_and_the_serial_alone(hass, loaded_entry):
    hass.config_entries.async_update_entry(
        loaded_entry, options={CONF_BASE_RATE: 0.41, "dry_run": True}
    )
    await hass.async_block_till_done()
    publish_rewired_sensors(hass)
    data_before = {k: v for k, v in loaded_entry.data.items() if k != CONF_SOLAR_POWER}
    result = await manual_form(hass, loaded_entry)

    await submit(flow(hass), result, **five(**{CONF_SOLAR_POWER: OTHER_SOLAR}))
    await hass.async_block_till_done()

    assert {k: v for k, v in loaded_entry.data.items() if k != CONF_SOLAR_POWER} == data_before
    assert loaded_entry.options[CONF_BASE_RATE] == 0.41
    assert loaded_entry.options["dry_run"] is True
    assert loaded_entry.unique_id == SERIAL


async def test_an_optional_entity_that_is_emptied_is_removed_from_the_entry(hass, loaded_entry):
    result = await manual_form(hass, loaded_entry)

    emptied = {CONF_INVERTER_TEMP_ENTITY: None, CONF_TARGET_SOC_ENTITY: None}
    await submit(flow(hass), result, **emptied)
    await hass.async_block_till_done()

    assert CONF_INVERTER_TEMP_ENTITY not in loaded_entry.data
    assert CONF_TARGET_SOC_ENTITY not in loaded_entry.data
    assert CONF_CHARGE_END_TIME_ENTITY in loaded_entry.data
    assert loaded_entry.state is ConfigEntryState.LOADED


async def test_the_five_power_entities_are_required_and_the_other_six_are_optional(
    hass, loaded_entry
):
    result = await manual_form(hass, loaded_entry)

    required = {f["name"] for f in serialised(result) if f["required"]}
    assert required == set(five())
    assert len(field_names(result)) == 11
    flow(hass).async_abort(result["flow_id"])


async def test_an_entity_that_does_not_exist_is_refused_and_nothing_is_saved(
    hass, loaded_entry, setups
):
    before = dict(loaded_entry.data)
    result = await manual_form(hass, loaded_entry)

    result = await submit(flow(hass), result, **five(**{CONF_SOLAR_POWER: "sensor.not_there"}))

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure_manual"
    assert result["errors"] == {"base": "missing_entities"}
    assert dict(loaded_entry.data) == before
    assert setups == []
    flow(hass).async_abort(result["flow_id"])


async def test_an_entity_that_reads_unavailable_is_refused(hass, loaded_entry):
    publish_rewired_sensors(hass)
    hass.states.async_set(OTHER_GRID, "unavailable")
    result = await manual_form(hass, loaded_entry)

    result = await submit(flow(hass), result, **five(**{CONF_GRID_POWER: OTHER_GRID}))

    assert result["errors"] == {"base": "missing_entities"}
    flow(hass).async_abort(result["flow_id"])


async def test_entities_of_another_inverter_abort_the_flow_and_save_nothing(
    hass, loaded_entry, setups
):
    before = dict(loaded_entry.data)
    other = "givtcp_cd5678h901"
    for suffix in ("pv_power", "soc", "battery_power", "grid_power", "load_power"):
        hass.states.async_set(f"sensor.{other}_{suffix}", 1)
    result = await manual_form(hass, loaded_entry)
    mapping = {
        CONF_SOLAR_POWER: f"sensor.{other}_pv_power",
        CONF_BATTERY_SOC: f"sensor.{other}_soc",
        CONF_BATTERY_POWER: f"sensor.{other}_battery_power",
        CONF_GRID_POWER: f"sensor.{other}_grid_power",
        CONF_HOUSE_LOAD: f"sensor.{other}_load_power",
    }

    result = await submit(flow(hass), result, **mapping)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_inverter"
    assert dict(loaded_entry.data) == before
    assert setups == []


async def test_hand_picked_sensors_with_no_serial_in_their_name_are_accepted(hass, loaded_entry):
    publish_rewired_sensors(hass)
    result = await manual_form(hass, loaded_entry)

    result = await submit(
        flow(hass),
        result,
        **five(
            **{
                CONF_SOLAR_POWER: OTHER_SOLAR,
                CONF_BATTERY_SOC: "sensor.rewired_solar",
                CONF_BATTERY_POWER: "sensor.rewired_grid",
                CONF_GRID_POWER: OTHER_GRID,
                CONF_HOUSE_LOAD: OTHER_SOLAR,
            }
        ),
    )

    assert result["reason"] == "reconfigure_successful"


async def test_the_serial_check_is_case_insensitive(hass, loaded_entry):
    """GivTCP serials are upper case in the sensor and lower case in entity ids."""
    hass.config_entries.async_update_entry(loaded_entry, unique_id=SERIAL.upper())
    result = await manual_form(hass, loaded_entry)

    result = await submit(flow(hass), result)

    assert result["reason"] == "reconfigure_successful"


async def test_an_entry_set_up_by_hand_has_no_serial_to_check(hass, loaded_entry):
    hass.config_entries.async_update_entry(loaded_entry, unique_id="manual")
    publish_rewired_sensors(hass)
    result = await manual_form(hass, loaded_entry)

    result = await submit(flow(hass), result, **five(**{CONF_SOLAR_POWER: OTHER_SOLAR}))

    assert result["reason"] == "reconfigure_successful"
    assert loaded_entry.data[CONF_SOLAR_POWER] == OTHER_SOLAR


async def test_one_entity_of_another_inverter_among_the_right_ones_aborts_the_flow(
    hass, loaded_entry, setups
):
    before = dict(loaded_entry.data)
    hass.states.async_set("sensor.givtcp_cd5678h901_pv_power", 1)
    result = await manual_form(hass, loaded_entry)

    result = await submit(
        flow(hass), result, **five(**{CONF_SOLAR_POWER: "sensor.givtcp_cd5678h901_pv_power"})
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_inverter"
    assert dict(loaded_entry.data) == before
    assert setups == []
