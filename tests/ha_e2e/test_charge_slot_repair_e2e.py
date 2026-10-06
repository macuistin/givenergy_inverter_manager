"""A leftover charge slot raises a repair, and the fix flow clears it through real services."""

from __future__ import annotations

import pytest
from conftest import CHEAP_NIGHT, PREFIX, SERIAL, full_config_data
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager import repairs
from custom_components.givenergy_inverter_manager.const import CONF_DRY_RUN, DOMAIN

START_2 = f"select.{PREFIX}_charge_start_time_slot_2"
END_2 = f"select.{PREFIX}_charge_end_time_slot_2"
ISSUE = repairs.ISSUE_OTHER_CHARGE_SLOTS_ACTIVE


@pytest.fixture
def scenario():
    return CHEAP_NIGHT


@pytest.fixture
def slot_writes(hass) -> list:
    """Capture select writes and let them take effect, as GivTCP does."""
    calls: list = []

    async def take_effect(call) -> None:
        calls.append(call)
        hass.states.async_set(call.data["entity_id"], call.data["option"])

    hass.services.async_register("select", "select_option", take_effect)
    return calls


async def _load(hass, **extra) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**full_config_data(), **extra},
        unique_id=SERIAL,
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE)


async def _open_fix_flow(hass) -> dict:
    assert await async_setup_component(hass, "repairs", {})
    return await repairs_flow_manager(hass).async_init(DOMAIN, data={"issue_id": ISSUE})


async def test_active_slot_two_raises_a_fixable_issue(hass, hass_in_scenario, slot_writes):
    hass.states.async_set(START_2, "00:00:00")
    hass.states.async_set(END_2, "08:00:00")
    entry = await _load(hass)

    issue = _issue(hass)
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {"slots": "Slot 2 (00:00 to 08:00)"}
    assert issue.learn_more_url == repairs.LEARN_MORE_URLS[ISSUE]
    assert slot_writes == []
    await hass.config_entries.async_unload(entry.entry_id)


async def test_no_issue_when_slot_two_is_zero_to_zero(hass, hass_in_scenario, slot_writes):
    hass.states.async_set(START_2, "00:00:00")
    hass.states.async_set(END_2, "00:00:00")
    entry = await _load(hass)

    assert _issue(hass) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_no_issue_when_there_are_no_other_slot_entities(hass, hass_in_scenario, slot_writes):
    entry = await _load(hass)

    assert _issue(hass) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_fix_flow_confirms_then_clears_the_slot_and_the_issue(
    hass, hass_in_scenario, slot_writes
):
    hass.states.async_set(START_2, "01:00:00")
    hass.states.async_set(END_2, "08:00:00")
    entry = await _load(hass)

    form = await _open_fix_flow(hass)
    assert form["type"] is FlowResultType.FORM
    assert form["step_id"] == "confirm"
    assert form["description_placeholders"] == {"slots": "Slot 2 (01:00 to 08:00)"}
    assert slot_writes == []

    done = await repairs_flow_manager(hass).async_configure(form["flow_id"], {})
    await hass.async_block_till_done()

    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert [(c.data["entity_id"], c.data["option"]) for c in slot_writes] == [
        (START_2, "00:00:00"),
        (END_2, "00:00:00"),
    ]
    assert entry.runtime_data._writer.write_count == 2

    await entry.runtime_data.async_refresh()
    assert _issue(hass) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_issue_stays_gone_on_later_cycles_after_the_fix(
    hass, hass_in_scenario, slot_writes
):
    hass.states.async_set(START_2, "01:00:00")
    hass.states.async_set(END_2, "08:00:00")
    entry = await _load(hass)
    form = await _open_fix_flow(hass)
    await repairs_flow_manager(hass).async_configure(form["flow_id"], {})

    await entry.runtime_data.async_refresh()
    await entry.runtime_data.async_refresh()

    assert _issue(hass) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_fix_flow_in_dry_run_aborts_and_changes_nothing(hass, hass_in_scenario, slot_writes):
    hass.states.async_set(START_2, "01:00:00")
    hass.states.async_set(END_2, "08:00:00")
    entry = await _load(hass, **{CONF_DRY_RUN: True})

    form = await _open_fix_flow(hass)
    done = await repairs_flow_manager(hass).async_configure(form["flow_id"], {})

    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "dry_run"
    assert slot_writes == []
    assert hass.states.get(END_2).state == "08:00:00"
    assert _issue(hass) is not None
    await hass.config_entries.async_unload(entry.entry_id)
