"""A hot water temperature sensor that stops reporting raises one repair, and it clears itself."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import IMMERSION_LOWER_TEMP, MIDDAY, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.core.temperature_feed import SILENT_CYCLES
from custom_components.givenergy_inverter_manager.repairs import (
    ISSUE_IMMERSION_TEMPERATURE_NOT_REPORTING,
)

CYCLE = timedelta(seconds=30)


@pytest.fixture
def scenario():
    return MIDDAY


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_IMMERSION_TEMPERATURE_NOT_REPORTING)


async def _cycles(hass, entry, freezer, count: int) -> None:
    for _ in range(count):
        freezer.tick(CYCLE)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


async def test_a_silent_thermometer_raises_the_repair_and_a_reading_clears_it(
    hass_in_scenario, freezer
):
    hass = hass_in_scenario
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=full_config_data(),
        unique_id=SERIAL,
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    hass.states.async_set(IMMERSION_LOWER_TEMP, "unavailable")
    await _cycles(hass, entry, freezer, SILENT_CYCLES)
    issue = _issue(hass)
    assert issue is not None
    assert issue.translation_placeholders == {"sensors": IMMERSION_LOWER_TEMP}
    assert issue.is_fixable is False

    hass.states.async_set(IMMERSION_LOWER_TEMP, "30.5", {"unit_of_measurement": "°C"})
    await _cycles(hass, entry, freezer, 1)
    assert _issue(hass) is None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
