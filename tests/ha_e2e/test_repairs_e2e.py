"""Repair issues land in the real issue registry with a learn-more link."""

from __future__ import annotations

from conftest import SERIAL, full_config_data
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager import repairs
from custom_components.givenergy_inverter_manager.const import CONF_BATTERY_MIN_SOC, DOMAIN


async def test_min_soc_issue_links_to_troubleshooting(hass, hass_in_scenario, service_calls):
    data = full_config_data()
    data[CONF_BATTERY_MIN_SOC] = 45
    entry = MockConfigEntry(domain=DOMAIN, data=data, unique_id=SERIAL, version=1)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, repairs.ISSUE_MIN_SOC_TOO_HIGH)
    assert issue is not None
    assert issue.learn_more_url == repairs.LEARN_MORE_URLS[repairs.ISSUE_MIN_SOC_TOO_HIGH]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_missing_entities_issue_links_to_troubleshooting(hass):
    repairs.async_create_givtcp_missing_issue(hass)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, repairs.ISSUE_GIVTCP_ENTITIES_MISSING)
    assert issue is not None
    assert issue.learn_more_url == repairs.LEARN_MORE_URLS[repairs.ISSUE_GIVTCP_ENTITIES_MISSING]
