"""The repair fix flows when the entry is not loaded, and the outcomes that are not a success."""

from __future__ import annotations

import pytest
from conftest import MIDDAY, SERIAL, full_config_data
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager import repairs
from custom_components.givenergy_inverter_manager.const import CONF_TARIFF_REVIEWED_ON, DOMAIN


@pytest.fixture
def scenario():
    return MIDDAY


async def _confirm(hass, issue_id: str, user_input: dict | None = None) -> dict:
    assert await async_setup_component(hass, "repairs", {})
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=issue_id,
    )
    manager = repairs_flow_manager(hass)
    result = await manager.async_init(DOMAIN, data={"issue_id": issue_id})
    if result["type"] is FlowResultType.ABORT:
        return result
    assert result["type"] is FlowResultType.FORM
    return await manager.async_configure(result["flow_id"], user_input or {})


async def _loaded(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=full_config_data(), unique_id=SERIAL, version=1)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.parametrize(
    "issue_id",
    [
        repairs.ISSUE_OTHER_CHARGE_SLOTS_ACTIVE,
        repairs.ISSUE_TARIFF_REVIEW_DUE,
        repairs.ISSUE_SYSTEM_LOOKS_DIFFERENT,
        repairs.ISSUE_DASHBOARD_OUT_OF_DATE,
        repairs.ISSUE_BATTERY_COST_NOT_SET,
    ],
)
async def test_a_fix_aborts_when_the_integration_is_not_loaded(
    hass, hass_in_scenario, service_calls, issue_id
):
    entry = await _loaded(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)

    result = await _confirm(hass, issue_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"


async def test_the_tariff_review_fix_records_today(hass, hass_in_scenario, service_calls):
    entry = await _loaded(hass)

    result = await _confirm(hass, repairs.ISSUE_TARIFF_REVIEW_DUE)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_TARIFF_REVIEWED_ON]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_accepting_a_system_change_takes_the_system_as_it_now_is(
    hass, hass_in_scenario, service_calls
):
    entry = await _loaded(hass)

    result = await _confirm(hass, repairs.ISSUE_SYSTEM_LOOKS_DIFFERENT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_dashboard_fix_aborts_with_the_reason_when_there_is_no_dashboard_to_write(
    hass, hass_in_scenario, service_calls
):
    entry = await _loaded(hass)

    result = await _confirm(hass, repairs.ISSUE_DASHBOARD_OUT_OF_DATE)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_clearing_the_slots_aborts_with_the_outcome_when_it_did_not_succeed(
    hass, hass_in_scenario, service_calls, monkeypatch
):
    entry = await _loaded(hass)

    async def failed():
        return repairs.ClearOutcome.FAILED

    monkeypatch.setattr(entry.runtime_data, "async_clear_other_charge_slots", failed)

    result = await _confirm(hass, repairs.ISSUE_OTHER_CHARGE_SLOTS_ACTIVE)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "write_failed"
    await hass.config_entries.async_unload(entry.entry_id)
