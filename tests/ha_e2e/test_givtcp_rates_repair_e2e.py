"""GivTCP rates that differ from the tariff raise a repair with both values, and clear again."""

from __future__ import annotations

import pytest
from conftest import CHEAP_NIGHT, PREFIX, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager import repairs
from custom_components.givenergy_inverter_manager.const import (
    CONF_BASE_RATE,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    DOMAIN,
)

ISSUE = repairs.ISSUE_GIVTCP_RATES_DIFFER
DAY = f"sensor.{PREFIX}_day_rate"
NIGHT = f"sensor.{PREFIX}_night_rate"
EXPORT = f"sensor.{PREFIX}_export_rate"
# Full config tariff: base 0.3334, Night 0.1644, Nightboost 0.0965, export 0.195.
MATCHING = {DAY: "0.3334", NIGHT: "0.1644", EXPORT: "0.195"}


@pytest.fixture
def scenario():
    return CHEAP_NIGHT


@pytest.fixture(params=["all devices", "no optional devices"])
def config_data(request) -> dict:
    data = full_config_data()
    if request.param == "all devices":
        return data
    return {k: v for k, v in data.items() if k not in (CONF_IMMERSION_SWITCH, CONF_IMMERSION_TEMP_SENSOR)}


def _publish(hass, rates: dict[str, str]) -> None:
    for entity_id, value in rates.items():
        hass.states.async_set(entity_id, value)


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


async def test_rates_that_differ_raise_a_warning_naming_both_values(
    hass, hass_in_scenario, config_data
):
    _publish(hass, {**MATCHING, DAY: "0.395", EXPORT: "0.2"})
    entry = await _load(hass, config_data)

    issue = _issue(hass)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.learn_more_url == repairs.LEARN_MORE_URLS[ISSUE]
    assert issue.translation_placeholders == {
        "rates": "- Day rate: 0.3334 here, 0.395 in GivTCP\n- Export rate: 0.195 here, 0.2 in GivTCP"
    }
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_issue_clears_when_givtcp_is_corrected(hass, hass_in_scenario, config_data):
    _publish(hass, {**MATCHING, DAY: "0.395"})
    entry = await _load(hass, config_data)
    assert _issue(hass) is not None

    _publish(hass, MATCHING)
    await entry.runtime_data.async_refresh()

    assert _issue(hass) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_issue_clears_when_the_tariff_here_is_corrected(
    hass, hass_in_scenario, config_data
):
    _publish(hass, {**MATCHING, DAY: "0.395"})
    entry = await _load(hass, config_data)
    assert _issue(hass) is not None

    hass.config_entries.async_update_entry(entry, options={CONF_BASE_RATE: 0.395})
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()

    assert _issue(hass) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_matching_rates_raise_nothing(hass, hass_in_scenario, config_data):
    _publish(hass, MATCHING)
    entry = await _load(hass, config_data)

    assert _issue(hass) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_no_rate_entities_means_nothing_is_shown(hass, hass_in_scenario, config_data):
    entry = await _load(hass, config_data)

    assert _issue(hass) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_unavailable_rates_show_nothing_and_keep_a_raised_issue(
    hass, hass_in_scenario, config_data
):
    _publish(hass, {**MATCHING, DAY: "0.395"})
    entry = await _load(hass, config_data)

    _publish(hass, {DAY: "unavailable", NIGHT: "unavailable", EXPORT: "unavailable"})
    await entry.runtime_data.async_refresh()

    assert _issue(hass) is not None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_a_dismissed_issue_stays_dismissed_on_later_cycles(
    hass, hass_in_scenario, config_data
):
    _publish(hass, {**MATCHING, DAY: "0.395"})
    entry = await _load(hass, config_data)
    ir.async_ignore_issue(hass, DOMAIN, ISSUE, True)

    await entry.runtime_data.async_refresh()
    await entry.runtime_data.async_refresh()

    assert _issue(hass).dismissed_version is not None
    await hass.config_entries.async_unload(entry.entry_id)
