"""Reconfigure against a real flow manager: it must take effect and reload once."""

from __future__ import annotations

import pytest
from conftest import MIDDAY
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv

import custom_components.givenergy_inverter_manager as integration
from custom_components.givenergy_inverter_manager.const import (
    CONF_BILL_START_DAY,
    CONF_EXPORT_RATE,
    CONF_RATE_PERIODS,
    CONF_VAT_RATE,
)


@pytest.fixture
def scenario():
    return MIDDAY


def _defaults(result) -> dict:
    fields = cv.to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    return {f["name"]: f["default"] for f in fields if "default" in f}


def _payload(result, **overrides) -> dict:
    fields = cv.to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    data: dict = {}
    for field in fields:
        if field.get("type") == "expandable":
            data[field["name"]] = {
                sub["name"]: sub["default"] for sub in field["schema"] if "default" in sub
            }
        elif "default" in field:
            data[field["name"]] = field["default"]
    data.update(overrides)
    return data


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


async def test_reconfigure_form_shows_the_values_in_force(hass, loaded_entry):
    hass.config_entries.async_update_entry(
        loaded_entry, options={CONF_EXPORT_RATE: 0.21, CONF_VAT_RATE: 13.5}
    )
    await hass.async_block_till_done()

    result = await loaded_entry.start_reconfigure_flow(hass)
    defaults = _defaults(result)

    assert defaults[CONF_EXPORT_RATE] == pytest.approx(0.21)
    assert defaults[CONF_VAT_RATE] == pytest.approx(13.5)
    assert defaults[CONF_BILL_START_DAY] == 16
    hass.config_entries.flow.async_abort(result["flow_id"])


async def test_reconfigure_wins_over_saved_options(hass, loaded_entry):
    hass.config_entries.async_update_entry(loaded_entry, options={CONF_EXPORT_RATE: 0.21})
    await hass.async_block_till_done()
    assert loaded_entry.runtime_data.export_rate == pytest.approx(0.21)

    result = await loaded_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=_payload(result, **{CONF_EXPORT_RATE: 0.3})
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert loaded_entry.state is ConfigEntryState.LOADED
    assert loaded_entry.runtime_data.export_rate == pytest.approx(0.3)
    assert CONF_EXPORT_RATE not in loaded_entry.options
    assert loaded_entry.data[CONF_EXPORT_RATE] == pytest.approx(0.3)


async def test_reconfigure_replaces_saved_rate_periods(hass, loaded_entry):
    saved = [{"name": "Weekend", "rate": 0.1, "start": "00:00", "end": "06:00"}]
    hass.config_entries.async_update_entry(loaded_entry, options={CONF_RATE_PERIODS: saved})
    await hass.async_block_till_done()

    result = await loaded_entry.start_reconfigure_flow(hass)
    payload = _payload(result)
    assert payload["rate_period_1"]["name"] == "Weekend"
    payload["rate_period_1"]["name"] = "Night"
    payload["rate_period_1"]["rate"] = 0.15
    await hass.config_entries.flow.async_configure(result["flow_id"], user_input=payload)
    await hass.async_block_till_done()

    assert CONF_RATE_PERIODS not in loaded_entry.options
    assert [p["name"] for p in loaded_entry.data[CONF_RATE_PERIODS]] == ["Night"]


async def test_reconfigure_reloads_once(hass, loaded_entry, setups):
    result = await loaded_entry.start_reconfigure_flow(hass)
    await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=_payload(result, **{CONF_EXPORT_RATE: 0.25})
    )
    await hass.async_block_till_done()

    assert len(setups) == 1
    assert loaded_entry.state is ConfigEntryState.LOADED


async def test_reconfigure_without_changes_does_not_reload(hass, loaded_entry, setups):
    result = await loaded_entry.start_reconfigure_flow(hass)
    await hass.config_entries.flow.async_configure(result["flow_id"], user_input=_payload(result))
    await hass.async_block_till_done()

    assert setups == []
    assert loaded_entry.state is ConfigEntryState.LOADED
