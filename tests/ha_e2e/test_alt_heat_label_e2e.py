"""The label of the alternative heating in real Home Assistant.

A new label changes the advice sentences without a reload. The form refuses an empty or a long
label. A label that reaches the entry some other way (a hand-edited file, a service call) is
cleaned before it reaches a sentence, and no state is over Home Assistant's 255 characters.
"""

from __future__ import annotations

import logging

import pytest
from conftest import MIDDAY, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import MAX_LENGTH_STATE_STATE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from wizard_support import Only, options_wizard

from custom_components.givenergy_inverter_manager.const import ALT_HEAT_LABEL_MAX_LENGTH, DOMAIN

KEY = "water_heating_cheapest_source"
BASE = {"alt_heat_enabled": True, "alt_heat_cost": 0.05}


@pytest.fixture
def scenario():
    return MIDDAY


def _entry(options: dict) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=full_config_data(),
        options=options,
        unique_id=SERIAL,
        version=1,
    )


async def submit(hass, entry, section: dict):
    """Run the options wizard's hot water page with *section* as the alternative heating section."""
    return await options_wizard(hass, entry, {"hot_water": {"alt_heat": Only(section)}})


async def set_up(hass, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def sensor(hass, entry):
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{KEY}")
    return hass.states.get(entity_id)


@pytest.fixture
def reloads(monkeypatch):
    import custom_components.givenergy_inverter_manager as integration

    calls = []
    real = integration.async_reload_entry

    async def _spy(hass, entry):
        calls.append(entry.entry_id)
        await real(hass, entry)

    monkeypatch.setattr(integration, "async_reload_entry", _spy)
    return calls


class TestAChangeOfLabel:
    async def test_the_sentences_change_without_a_reload(self, hass_in_scenario, reloads):
        hass = hass_in_scenario
        entry = _entry({**BASE, "alt_heat_label": "Oil"})
        await set_up(hass, entry)
        assert "run the oil water heating" in sensor(hass, entry).attributes["suggestion"]

        result = await submit(hass, entry, {**BASE, "alt_heat_label": "Heat pump"})

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert reloads == []
        attributes = sensor(hass, entry).attributes
        assert attributes["alt_label"] == "Heat pump"
        assert "Heat pump is cheaper than the grid now" in attributes["suggestion"]
        assert "run the heat pump water heating for about" in attributes["suggestion"]
        assert "oil" not in attributes["suggestion"].lower()

    async def test_a_new_unit_changes_the_cost_without_a_reload(self, hass_in_scenario, reloads):
        hass = hass_in_scenario
        entry = _entry({**BASE, "alt_heat_cost": 0.10, "alt_heat_label": "Gas"})
        await set_up(hass, entry)
        litre = sensor(hass, entry).attributes["alt_cost_per_kwh"]
        assert litre == pytest.approx(0.10 / (10.35 * 0.85), abs=1e-4)

        await submit(
            hass,
            entry,
            {**BASE, "alt_heat_cost": 0.10, "alt_heat_label": "Gas", "alt_heat_cost_unit": "kwh_heat"},
        )
        assert reloads == []
        assert sensor(hass, entry).attributes["alt_cost_per_kwh"] == 0.10

    async def test_the_label_is_saved_cleaned(self, hass_in_scenario, reloads):
        hass = hass_in_scenario
        entry = _entry({**BASE, "alt_heat_label": "Oil"})
        await set_up(hass, entry)
        await submit(hass, entry, {**BASE, "alt_heat_label": "  Wood   pellets  "})
        assert entry.options["alt_heat_label"] == "Wood pellets"


class TestTheFormRefusesABadLabel:
    @pytest.mark.parametrize(
        ("label", "error"),
        [
            ("", "alt_heat_label_empty"),
            ("   ", "alt_heat_label_empty"),
            ("x" * (ALT_HEAT_LABEL_MAX_LENGTH + 1), "alt_heat_label_too_long"),
            ("y" * 300, "alt_heat_label_too_long"),
        ],
    )
    async def test_an_empty_or_long_label_shows_the_form_again(
        self, hass_in_scenario, reloads, label, error
    ):
        hass = hass_in_scenario
        entry = _entry({**BASE, "alt_heat_label": "Oil"})
        await set_up(hass, entry)

        result = await submit(hass, entry, {**BASE, "alt_heat_label": label})

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": error}
        assert entry.options["alt_heat_label"] == "Oil"
        assert reloads == []

    async def test_the_longest_label_is_accepted(self, hass_in_scenario, reloads):
        hass = hass_in_scenario
        entry = _entry({**BASE, "alt_heat_label": "Oil"})
        await set_up(hass, entry)
        label = "z" * ALT_HEAT_LABEL_MAX_LENGTH
        result = await submit(hass, entry, {**BASE, "alt_heat_label": label})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options["alt_heat_label"] == label

    async def test_a_label_is_not_checked_while_the_setting_is_off(self, hass_in_scenario):
        hass = hass_in_scenario
        entry = _entry({**BASE, "alt_heat_label": "Oil"})
        await set_up(hass, entry)
        result = await submit(
            hass, entry, {"alt_heat_enabled": False, "alt_heat_label": "", "alt_heat_cost": 0.05}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options["alt_heat_label"] == "Oil"


class TestALabelThatSkipsTheForm:
    """A hand-edited entry can hold anything. The state stays inside Home Assistant's limit."""

    @pytest.mark.parametrize(
        "label",
        [
            "q" * 2000,
            "",
            "   ",
            None,
            "Gás “boiler” \n {x}",
            "<script>alert(1)</script>" * 20,
        ],
        ids=["very-long", "empty", "blank", "none", "odd-characters", "markup"],
    )
    async def test_every_state_and_the_sentence_stay_within_the_limits(
        self, hass_in_scenario, caplog, label
    ):
        hass = hass_in_scenario
        entry = _entry({**BASE, "alt_heat_label": label})
        with caplog.at_level(logging.ERROR):
            await set_up(hass, entry)

        state = sensor(hass, entry)
        assert state.state == "alternative"
        for ours in hass.states.async_all("sensor"):
            if ours.entity_id.startswith("sensor.givenergy_inverter_manager"):
                assert len(ours.state) <= MAX_LENGTH_STATE_STATE, ours.entity_id
        assert len(state.attributes["alt_label"]) <= ALT_HEAT_LABEL_MAX_LENGTH
        assert state.attributes["alt_label"].strip() != ""
        assert len(state.attributes["suggestion"]) < 500
        assert "\n" not in state.attributes["suggestion"]
        assert "is longer than 255" not in caplog.text
        assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []

    async def test_an_empty_label_says_oil(self, hass_in_scenario):
        hass = hass_in_scenario
        entry = _entry({**BASE, "alt_heat_label": ""})
        await set_up(hass, entry)
        assert sensor(hass, entry).attributes["alt_label"] == "Oil"
        assert "run the oil water heating" in sensor(hass, entry).attributes["suggestion"]
