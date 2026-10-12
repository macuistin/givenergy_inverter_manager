"""Two outside changes to the charge target flip the sensor, and the banner follows it."""

from __future__ import annotations

import pytest
from conftest import MIDDAY, TARGET_SOC
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.dashboard import async_host_facts, build_dashboard

pytestmark = pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)


async def _sensor(hass, entry):
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_charge_target_conflict"
    )
    assert entity_id, "the sensor is registered"
    return hass.states.get(entity_id)


async def test_a_quiet_system_is_none(hass, loaded_entry):
    state = await _sensor(hass, loaded_entry)

    assert state.state == "none"
    assert state.attributes["changes"] == 0
    assert state.attributes["target_entity"] == TARGET_SOC


async def test_one_outside_change_is_still_none(hass, loaded_entry):
    hass.states.async_set(TARGET_SOC, "55")

    state = await _sensor(hass, loaded_entry)

    assert (state.state, state.attributes["changes"]) == ("none", 1)


async def test_two_outside_changes_with_no_user_make_it_suspected(hass, loaded_entry):
    hass.states.async_set(TARGET_SOC, "55")
    hass.states.async_set(TARGET_SOC, "70")

    state = await _sensor(hass, loaded_entry)

    assert state.state == "suspected"
    assert state.attributes["changes"] == 2
    assert state.attributes["last_seen"]


async def test_changes_made_by_a_user_never_make_it_suspected(hass, loaded_entry):
    hass.states.async_set(TARGET_SOC, "55", context=Context(user_id="user-1"))
    hass.states.async_set(TARGET_SOC, "70", context=Context(user_id="user-1"))

    state = await _sensor(hass, loaded_entry)

    assert (state.state, state.attributes["changes"]) == ("none", 0)


async def _banner(hass, entry) -> dict:
    facts = await async_host_facts(hass, is_admin=True)
    dashboard = build_dashboard(hass, entry, facts)
    sections = next(v for v in dashboard["views"] if v.get("path") == "power-flow")["sections"]
    return next(
        s for s in sections if "Something else is setting" in str(s["cards"][0].get("heading"))
    )


async def test_the_banner_shows_for_suspected_and_for_no_other_state(hass, loaded_entry):
    sensor = (await _sensor(hass, loaded_entry)).entity_id

    banner = await _banner(hass, loaded_entry)

    assert banner["visibility"] == [{"condition": "state", "entity": sensor, "state": "suspected"}]
    # Plain state conditions only, so the dashboard works on the 2026.5 floor.
    assert {c["condition"] for c in banner["visibility"]} == {"state"}
    assert "SmartTarget" in banner["cards"][1]["content"]
