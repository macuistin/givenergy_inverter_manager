"""A switch that rejects the manager's commands raises one repair, and it clears itself."""

from __future__ import annotations

import pytest
from conftest import IMMERSION_SWITCH, MIDDAY, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.repairs import (
    ISSUE_IMMERSION_SWITCH_NOT_RESPONDING,
)

REASON = "The Tuya cloud rejected the command"


@pytest.fixture
def scenario():
    return MIDDAY


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_IMMERSION_SWITCH_NOT_RESPONDING)


async def _set_up(hass) -> MockConfigEntry:
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
    return entry


def _plug_that(hass, *, accepts: bool) -> None:
    """Replace the switch service, as the plug's own integration would answer it."""

    async def handle(call: ServiceCall) -> None:
        if not accepts:
            raise HomeAssistantError(REASON)
        hass.states.async_set(call.data["entity_id"], "on")

    hass.services.async_register("switch", "turn_on", handle)


async def test_two_rejected_commands_raise_the_repair_and_a_good_one_clears_it(
    hass_in_scenario,
):
    hass = hass_in_scenario
    entry = await _set_up(hass)
    coordinator = entry.runtime_data
    _plug_that(hass, accepts=False)

    for _ in range(2):
        with pytest.raises(HomeAssistantError, match="rejected"):
            await coordinator._send_immersion_command("turn_on", IMMERSION_SWITCH)

    issue = _issue(hass)
    assert issue is not None
    assert issue.translation_placeholders == {"switch": IMMERSION_SWITCH, "reason": REASON}
    assert issue.is_fixable is False

    _plug_that(hass, accepts=True)
    await coordinator._send_immersion_command("turn_on", IMMERSION_SWITCH)
    assert _issue(hass) is None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_the_repair_is_gone_when_the_integration_unloads(hass_in_scenario):
    hass = hass_in_scenario
    entry = await _set_up(hass)
    _plug_that(hass, accepts=False)
    for _ in range(2):
        with pytest.raises(HomeAssistantError):
            await entry.runtime_data._send_immersion_command("turn_on", IMMERSION_SWITCH)
    assert _issue(hass) is not None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert _issue(hass) is None
