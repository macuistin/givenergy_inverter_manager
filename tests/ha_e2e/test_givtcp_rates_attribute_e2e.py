"""GivTCP rates that differ from the tariff show as attributes of Current Rate, with no repair.

Setup also deletes the givtcp_rates_differ repair that v0.13.0 to v0.14.0 may have raised.
"""

from __future__ import annotations

import pytest
from conftest import CHEAP_NIGHT, PREFIX, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import (
    CONF_BASE_RATE,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    DOMAIN,
)

STALE_ISSUE = "givtcp_rates_differ"
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
    return ir.async_get(hass).async_get_issue(DOMAIN, STALE_ISSUE)


def _current_rate(hass, entry):
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_current_rate"
    )
    assert entity_id is not None
    return hass.states.get(entity_id)


def _attributes(hass, entry) -> dict:
    return dict(_current_rate(hass, entry).attributes)


async def test_rates_that_differ_are_listed_on_current_rate_and_raise_no_repair(
    hass, hass_in_scenario, config_data
):
    _publish(hass, {**MATCHING, DAY: "0.395", EXPORT: "0.2"})
    entry = await _load(hass, config_data)

    attributes = _attributes(hass, entry)
    assert attributes["givtcp_rates_differ"] is True
    assert attributes["givtcp_rate_differences"] == [
        "Day rate: 0.3334 here, 0.395 in GivTCP",
        "Export rate: 0.195 here, 0.2 in GivTCP",
    ]
    assert _issue(hass) is None
    assert ir.async_get(hass).issues == {}
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_state_of_current_rate_does_not_change(hass, hass_in_scenario, config_data):
    _publish(hass, MATCHING)
    entry = await _load(hass, config_data)
    state_when_matching = _current_rate(hass, entry).state

    _publish(hass, {**MATCHING, DAY: "0.395"})
    await entry.runtime_data.async_refresh()

    assert _current_rate(hass, entry).state == state_when_matching
    await hass.config_entries.async_unload(entry.entry_id)


async def test_matching_rates_report_false(hass, hass_in_scenario, config_data):
    _publish(hass, MATCHING)
    entry = await _load(hass, config_data)

    attributes = _attributes(hass, entry)
    assert attributes["givtcp_rates_differ"] is False
    assert attributes["givtcp_rate_differences"] == []
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_attribute_follows_a_correction_in_givtcp(hass, hass_in_scenario, config_data):
    _publish(hass, {**MATCHING, DAY: "0.395"})
    entry = await _load(hass, config_data)
    assert _attributes(hass, entry)["givtcp_rates_differ"] is True

    _publish(hass, MATCHING)
    await entry.runtime_data.async_refresh()

    assert _attributes(hass, entry)["givtcp_rates_differ"] is False
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_attribute_follows_a_correction_of_the_tariff_here(
    hass, hass_in_scenario, config_data
):
    _publish(hass, {**MATCHING, DAY: "0.395"})
    entry = await _load(hass, config_data)
    assert _attributes(hass, entry)["givtcp_rates_differ"] is True

    hass.config_entries.async_update_entry(entry, options={CONF_BASE_RATE: 0.395})
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()

    assert _attributes(hass, entry)["givtcp_rates_differ"] is False
    await hass.config_entries.async_unload(entry.entry_id)


async def test_no_rate_entities_means_no_such_attributes(hass, hass_in_scenario, config_data):
    entry = await _load(hass, config_data)

    attributes = _attributes(hass, entry)
    assert "givtcp_rates_differ" not in attributes
    assert "givtcp_rate_differences" not in attributes
    await hass.config_entries.async_unload(entry.entry_id)


async def test_unavailable_rates_remove_the_attributes_again(hass, hass_in_scenario, config_data):
    _publish(hass, {**MATCHING, DAY: "0.395"})
    entry = await _load(hass, config_data)

    _publish(hass, {DAY: "unavailable", NIGHT: "unavailable", EXPORT: "unavailable"})
    await entry.runtime_data.async_refresh()

    assert "givtcp_rates_differ" not in _attributes(hass, entry)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_deletes_the_stale_issue_a_previous_version_raised(
    hass, hass_in_scenario, config_data
):
    ir.async_create_issue(
        hass,
        DOMAIN,
        STALE_ISSUE,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=STALE_ISSUE,
        translation_placeholders={"rates": "- Day rate: 0.3334 here, 0.395 in GivTCP"},
    )
    assert _issue(hass) is not None
    _publish(hass, {**MATCHING, DAY: "0.395"})

    entry = await _load(hass, config_data)

    assert _issue(hass) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_deletes_a_dismissed_stale_issue_too(hass, hass_in_scenario, config_data):
    ir.async_create_issue(
        hass,
        DOMAIN,
        STALE_ISSUE,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=STALE_ISSUE,
        translation_placeholders={"rates": "x"},
    )
    ir.async_ignore_issue(hass, DOMAIN, STALE_ISSUE, True)

    entry = await _load(hass, config_data)

    assert _issue(hass) is None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_without_the_stale_issue_is_safe_and_leaves_other_issues(
    hass, hass_in_scenario, config_data
):
    ir.async_create_issue(
        hass,
        DOMAIN,
        "some_other_issue",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="some_other_issue",
    )

    entry = await _load(hass, config_data)

    assert _issue(hass) is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, "some_other_issue") is not None
    await hass.config_entries.async_unload(entry.entry_id)
