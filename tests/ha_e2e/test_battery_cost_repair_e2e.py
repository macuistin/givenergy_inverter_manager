"""A battery cost of 0 raises a repair that asks for it, and the fix saves it without losing options."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import CHEAP_NIGHT, SERIAL, full_config_data
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager import repairs
from custom_components.givenergy_inverter_manager.const import (
    BATTERY_LIFE_ESTIMATE_MIN_DAYS,
    CONF_BASE_RATE,
    CONF_BATTERY_COST,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    CONF_RATE_PERIODS,
    DOMAIN,
)

ISSUE = repairs.ISSUE_BATTERY_COST_NOT_SET


@pytest.fixture
def scenario():
    return CHEAP_NIGHT


def _without_optional_devices(data: dict) -> dict:
    return {k: v for k, v in data.items() if k not in (CONF_IMMERSION_SWITCH, CONF_IMMERSION_TEMP_SENSOR)}


@pytest.fixture(params=["all devices", "no optional devices"])
def config_data(request) -> dict:
    data = full_config_data()
    return data if request.param == "all devices" else _without_optional_devices(data)


async def _load(hass, data: dict, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data=data, options=options or {}, unique_id=SERIAL, version=1
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE)


async def _tracked_for(hass, entry, days: int) -> None:
    """Run one cycle as if the integration had tracked the battery for *days* days."""
    coordinator = entry.runtime_data
    coordinator._battery_stats.tracking_start_date = coordinator._now().date() - timedelta(
        days=days
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()


async def _open_fix_flow(hass) -> dict:
    assert await async_setup_component(hass, "repairs", {})
    return await repairs_flow_manager(hass).async_init(DOMAIN, data={"issue_id": ISSUE})


async def test_a_new_install_is_not_asked(hass, hass_in_scenario, config_data):
    entry = await _load(hass, config_data)

    await _tracked_for(hass, entry, BATTERY_LIFE_ESTIMATE_MIN_DAYS - 1)

    assert _issue(hass) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_week_of_tracking_with_no_cost_raises_a_fixable_warning(
    hass, hass_in_scenario, config_data
):
    entry = await _load(hass, config_data)

    await _tracked_for(hass, entry, BATTERY_LIFE_ESTIMATE_MIN_DAYS)

    issue = _issue(hass)
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.learn_more_url == repairs.LEARN_MORE_URLS[ISSUE]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_setting_the_cost_in_the_options_clears_the_issue(
    hass, hass_in_scenario, config_data
):
    entry = await _load(hass, config_data)
    await _tracked_for(hass, entry, BATTERY_LIFE_ESTIMATE_MIN_DAYS)
    assert _issue(hass) is not None

    hass.config_entries.async_update_entry(entry, options={CONF_BATTERY_COST: 6500.0})
    await hass.async_block_till_done()
    await _tracked_for(hass, entry, BATTERY_LIFE_ESTIMATE_MIN_DAYS)

    assert _issue(hass) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_fix_flow_asks_for_the_cost_and_saves_it_keeping_other_options(
    hass, hass_in_scenario, config_data
):
    saved_periods = [{"name": "Night", "rate": 0.12, "start": "23:00", "end": "07:00"}]
    entry = await _load(
        hass, config_data, {CONF_BASE_RATE: 0.41, CONF_RATE_PERIODS: saved_periods}
    )
    await _tracked_for(hass, entry, BATTERY_LIFE_ESTIMATE_MIN_DAYS)

    form = await _open_fix_flow(hass)
    assert form["type"] is FlowResultType.FORM
    assert form["step_id"] == "confirm"
    assert list(form["data_schema"].schema) == [CONF_BATTERY_COST]

    done = await repairs_flow_manager(hass).async_configure(
        form["flow_id"], {CONF_BATTERY_COST: 6500}
    )
    await hass.async_block_till_done()

    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_BASE_RATE: 0.41,
        CONF_RATE_PERIODS: saved_periods,
        CONF_BATTERY_COST: 6500.0,
    }
    assert entry.state is ConfigEntryState.LOADED
    await _tracked_for(hass, entry, BATTERY_LIFE_ESTIMATE_MIN_DAYS)
    assert _issue(hass) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_fix_flow_rejects_zero_and_changes_nothing(hass, hass_in_scenario, config_data):
    entry = await _load(hass, config_data)
    await _tracked_for(hass, entry, BATTERY_LIFE_ESTIMATE_MIN_DAYS)
    form = await _open_fix_flow(hass)

    again = await repairs_flow_manager(hass).async_configure(
        form["flow_id"], {CONF_BATTERY_COST: 0}
    )

    assert again["type"] is FlowResultType.FORM
    assert again["errors"] == {"base": "cost_required"}
    assert CONF_BATTERY_COST not in entry.options
    assert _issue(hass) is not None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_dismissed_issue_stays_dismissed_on_later_cycles(
    hass, hass_in_scenario, config_data
):
    entry = await _load(hass, config_data)
    await _tracked_for(hass, entry, BATTERY_LIFE_ESTIMATE_MIN_DAYS)
    ir.async_ignore_issue(hass, DOMAIN, ISSUE, True)

    await _tracked_for(hass, entry, BATTERY_LIFE_ESTIMATE_MIN_DAYS)
    await _tracked_for(hass, entry, BATTERY_LIFE_ESTIMATE_MIN_DAYS)

    assert _issue(hass).dismissed_version is not None
    await hass.config_entries.async_unload(entry.entry_id)
