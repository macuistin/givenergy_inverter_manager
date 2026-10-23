"""A decision text longer than 255 characters reaches the real state machine without an error.

Home Assistant logs "State ... is longer than 255, falling back to unknown" on every update of
a state that is too long, and the state reads unknown. The overnight charge reason did this on
2026-10-11. The sensor now publishes a cut of the text and keeps the whole in an attribute.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest
from conftest import CHEAP_NIGHT, EVENING
from homeassistant.const import MAX_LENGTH_STATE_STATE, STATE_UNKNOWN
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import (
    ATTR_FULL_TEXT,
    DOMAIN,
    STATE_MAX_LENGTH,
)
from custom_components.givenergy_inverter_manager.core import engine

# The reason of the 2026-10-11 log line, as the charge calculation builds it. The engine adds
# "(capped at configured max N%)" after it.
LONG_REASON = (
    "Forward simulation: 7.3kWh forecast (forecast integration, x0.87 recent accuracy "
    "(cautious forecast, 50% of the way from the typical to the low estimate)). Target 100%. "
    "Not skipping: Battery may run low. Estimated shortfall: 1.0kWh before solar starts. "
    "Per-slot load profile used."
)


@pytest.fixture(params=[EVENING, CHEAP_NIGHT], ids=lambda s: s.name)
def scenario(request):
    """The overnight sensors read unknown by day, so these run in the evening and at night."""
    return request.param


@pytest.fixture(autouse=True)
def _a_charge_reason_over_the_limit(monkeypatch):
    """Make the engine's charge calculation return the logged reason, ahead of the setup."""
    real = engine.calculate_overnight_charge_target

    def long_reason(*args, **kwargs):
        return replace(real(*args, **kwargs), reason=LONG_REASON)

    monkeypatch.setattr(engine, "calculate_overnight_charge_target", long_reason)


def _published_reason(entry) -> str:
    """The full reason the coordinator holds for the sensor to publish."""
    return entry.runtime_data.data.published_charge_decision.reason


def _entity_id(hass, entry, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None, key
    return entity_id


def test_the_limit_matches_the_one_home_assistant_enforces():
    assert STATE_MAX_LENGTH == MAX_LENGTH_STATE_STATE


async def test_a_long_charge_reason_is_published_without_an_error(hass, loaded_entry, caplog):
    with caplog.at_level(logging.ERROR):
        await loaded_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
    assert "is longer than 255" not in caplog.text


async def test_the_state_is_a_cut_of_the_reason_and_not_unknown(hass, loaded_entry):
    state = hass.states.get(_entity_id(hass, loaded_entry, "overnight_charge_reason"))

    assert state.state != STATE_UNKNOWN
    assert len(state.state) <= MAX_LENGTH_STATE_STATE
    assert state.state.endswith("…")
    assert _published_reason(loaded_entry).startswith(state.state.removesuffix("…"))


async def test_the_full_reason_is_the_full_text_attribute_of_the_same_sensor(hass, loaded_entry):
    state = hass.states.get(_entity_id(hass, loaded_entry, "overnight_charge_reason"))

    assert state.attributes[ATTR_FULL_TEXT] == _published_reason(loaded_entry)
    assert state.attributes[ATTR_FULL_TEXT].startswith(LONG_REASON)
    assert len(state.attributes[ATTR_FULL_TEXT]) > MAX_LENGTH_STATE_STATE


async def test_the_full_text_is_not_recorded(hass, loaded_entry):
    state = hass.states.get(_entity_id(hass, loaded_entry, "overnight_charge_reason"))

    assert ATTR_FULL_TEXT in state.state_info["unrecorded_attributes"]


async def test_the_charge_plan_report_holds_the_whole_reason(hass, loaded_entry):
    state = hass.states.get(_entity_id(hass, loaded_entry, "charge_plan"))

    assert _published_reason(loaded_entry) in state.attributes["html"]
    assert len(state.state) <= MAX_LENGTH_STATE_STATE


async def test_a_reason_that_fits_is_published_as_it_is(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    coordinator.data.published_charge_decision = replace(
        coordinator.data.published_charge_decision, reason="Skipping overnight charge."
    )

    coordinator.async_set_updated_data(coordinator.data)
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, loaded_entry, "overnight_charge_reason"))
    assert state.state == "Skipping overnight charge."
    assert ATTR_FULL_TEXT not in state.attributes
