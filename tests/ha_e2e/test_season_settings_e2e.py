"""The winter and shoulder months are settings that start from the latitude and apply live."""

from __future__ import annotations

import pytest
from conftest import MIDDAY
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from wizard_support import open_options, options_wizard, serialised, submit

import custom_components.givenergy_inverter_manager as integration
from custom_components.givenergy_inverter_manager.const import (
    CONF_CHARGE_SHOULDER_MONTHS,
    CONF_CHARGE_WINTER_MONTHS,
    CONF_CHARGE_WINTER_USES_FORECAST,
)

pytestmark = pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)


def _field(result, name: str) -> dict:
    return next(f for f in serialised(result) if f["name"] == name)


@pytest.fixture
def lifecycle(monkeypatch):
    calls = {"setup": 0, "unload": 0}
    real_setup, real_unload = integration.async_setup_entry, integration.async_unload_entry

    async def counted_setup(hass, entry):
        calls["setup"] += 1
        return await real_setup(hass, entry)

    async def counted_unload(hass, entry):
        calls["unload"] += 1
        return await real_unload(hass, entry)

    monkeypatch.setattr(integration, "async_setup_entry", counted_setup)
    monkeypatch.setattr(integration, "async_unload_entry", counted_unload)
    return calls


async def test_the_lists_start_from_the_latitude_default_and_nothing_is_saved(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"charge_planning": {}})

    assert _field(result, CONF_CHARGE_WINTER_MONTHS)["default"] == ["1", "2", "12"]
    assert _field(result, CONF_CHARGE_SHOULDER_MONTHS)["default"] == ["3", "4", "10", "11"]
    assert _field(result, CONF_CHARGE_WINTER_USES_FORECAST)["default"] is False
    hass.config_entries.options.async_abort(result["flow_id"])
    assert CONF_CHARGE_WINTER_MONTHS not in loaded_entry.options


async def test_a_southern_latitude_starts_from_the_southern_months(hass, loaded_entry):
    hass.config.latitude = -33.9

    result = await open_options(hass, loaded_entry, {"charge_planning": {}})

    assert _field(result, CONF_CHARGE_WINTER_MONTHS)["default"] == ["6", "7", "8"]
    hass.config_entries.options.async_abort(result["flow_id"])


async def test_saving_the_page_unchanged_stores_no_season_setting(hass, lifecycle, loaded_entry):
    result = await options_wizard(hass, loaded_entry, {"charge_planning": {}})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    for key in (CONF_CHARGE_WINTER_MONTHS, CONF_CHARGE_SHOULDER_MONTHS, CONF_CHARGE_WINTER_USES_FORECAST):
        assert key not in loaded_entry.options


async def test_editing_the_months_saves_them_and_does_not_reload(hass, lifecycle, loaded_entry):
    coordinator = loaded_entry.runtime_data

    result = await options_wizard(
        hass,
        loaded_entry,
        {
            "charge_planning": {
                CONF_CHARGE_WINTER_MONTHS: ["11", "12", "1", "2"],
                CONF_CHARGE_SHOULDER_MONTHS: ["3", "4", "10"],
                CONF_CHARGE_WINTER_USES_FORECAST: True,
            }
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options[CONF_CHARGE_WINTER_MONTHS] == [1, 2, 11, 12]
    assert loaded_entry.options[CONF_CHARGE_WINTER_USES_FORECAST] is True
    assert loaded_entry.options[CONF_CHARGE_SHOULDER_MONTHS] == [3, 4, 10]
    assert loaded_entry.state is ConfigEntryState.LOADED
    assert loaded_entry.runtime_data is coordinator
    assert lifecycle == {"setup": 1, "unload": 0}


async def test_a_month_in_both_lists_is_refused(hass, loaded_entry):
    result = await open_options(hass, loaded_entry, {"charge_planning": {}})

    result = await submit(
        hass.config_entries.options,
        result,
        **{CONF_CHARGE_WINTER_MONTHS: ["12", "1"], CONF_CHARGE_SHOULDER_MONTHS: ["1", "2"]},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "season_months_overlap"}
    assert CONF_CHARGE_WINTER_MONTHS not in loaded_entry.options


async def test_an_empty_list_is_allowed_and_turns_the_rule_off(hass, loaded_entry):
    result = await options_wizard(hass, loaded_entry, {"charge_planning": {CONF_CHARGE_WINTER_MONTHS: []}})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options[CONF_CHARGE_WINTER_MONTHS] == []


async def test_the_coordinator_plans_with_the_months_that_were_saved(hass, loaded_entry):
    """MIDDAY is in June. Making June a winter month charges to the cap."""
    await options_wizard(hass, loaded_entry, {"charge_planning": {CONF_CHARGE_WINTER_MONTHS: ["6"]}})
    await hass.async_block_till_done()

    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    decision = loaded_entry.runtime_data.data.charge_decision
    assert "Winter month (6)" in decision.reason
    assert decision.target_soc == 80  # the configured cap, which also limits the winter target
