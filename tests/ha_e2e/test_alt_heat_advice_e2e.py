"""The alternative water heating advice in real Home Assistant, through the real options flow.

With alternative heating off, or with no cost, nothing is created or evaluated. Turning it on
with a cost in the options (with an immersion switch to compare with) creates the sensor after
the reload. Clearing the cost removes the sensor. A cost sensor overrides the saved number.
"""

from __future__ import annotations

import pytest
from conftest import MIDDAY, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from wizard_support import Only, options_wizard

from custom_components.givenergy_inverter_manager.const import (
    CONF_ALT_HEAT_COST,
    CONF_ALT_HEAT_COST_ENTITY,
    CONF_ALT_HEAT_ENABLED,
    CONF_IMMERSION_SWITCH,
    DOMAIN,
)
from custom_components.givenergy_inverter_manager.strategy import async_dashboard_for_websocket
from tests.dashboard_support import all_cards
from tests.dashboard_visibility import seen

KEY = "water_heating_cheapest_source"
TRIGGER_KEY = "water_heating_trigger"
PRICE_SENSOR = "sensor.heat_cost"
CHEAP_OIL = 0.05  # per litre: oil is far cheaper than any grid rate
DEAR_OIL = 4.5  # per litre: oil is dearer than any grid rate


@pytest.fixture
def scenario():
    return MIDDAY


def _entry(data: dict, options: dict | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=data,
        options=options or {},
        unique_id=SERIAL,
        version=1,
    )


async def save_alt_options(hass, entry, section: dict) -> None:
    """Run the options wizard's hot water page with this alternative heating section.

    {} is the section with every field left empty.
    """
    result = await options_wizard(hass, entry, {"hot_water": {"alt_heat": Only(section)}})
    # An unchanged run ends at the menu, which offers no save: nothing is written.
    assert result["type"] in (FlowResultType.CREATE_ENTRY, FlowResultType.MENU), result
    assert entry.state is ConfigEntryState.LOADED


def sensor_id(hass, entry, key: str = KEY) -> str | None:
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")


async def refresh(hass, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def set_up(hass, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


class TestNoAlternativeHeating:
    @pytest.fixture
    def config_entry(self):
        return _entry(full_config_data())

    async def test_nothing_is_created_or_evaluated(self, hass_in_scenario, config_entry):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        assert sensor_id(hass, config_entry) is None
        assert config_entry.runtime_data.data.water_heating_advice is None

    async def test_saving_the_options_untouched_keeps_it_that_way(
        self, hass_in_scenario, config_entry
    ):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        await save_alt_options(hass, config_entry, {})
        assert sensor_id(hass, config_entry) is None
        assert CONF_ALT_HEAT_COST not in config_entry.options


class TestAddedLater:
    @pytest.fixture
    def config_entry(self):
        return _entry(full_config_data())

    async def test_a_cost_in_the_options_creates_the_sensor(
        self, hass_in_scenario, config_entry
    ):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        await save_alt_options(hass, config_entry, {CONF_ALT_HEAT_ENABLED: True, CONF_ALT_HEAT_COST: CHEAP_OIL})
        entity_id = sensor_id(hass, config_entry)
        assert entity_id is not None
        await refresh(hass, config_entry)
        state = hass.states.get(entity_id)
        assert state.state == "alternative"
        # This install has a water temperature of 48.2, under the minimum of 50 plus the restart
        # gap of 5, so the suggestion is the keep-warm run, not the plain sentence.
        assert "run the oil water heating for about" in state.attributes["suggestion"]
        assert state.attributes["alt_keep_warm"] == state.attributes["suggestion"]
        assert state.attributes["alt_saving_per_kwh"] > 0

    async def test_a_dear_cost_says_electricity(self, hass_in_scenario, config_entry):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        await save_alt_options(hass, config_entry, {CONF_ALT_HEAT_ENABLED: True, CONF_ALT_HEAT_COST: DEAR_OIL})
        await refresh(hass, config_entry)
        state = hass.states.get(sensor_id(hass, config_entry))
        assert state.state == "electricity"
        assert state.attributes["best_hours_for_alt"] == []

    async def test_clearing_the_cost_removes_the_sensor(self, hass_in_scenario, config_entry):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        await save_alt_options(hass, config_entry, {CONF_ALT_HEAT_ENABLED: True, CONF_ALT_HEAT_COST: CHEAP_OIL})
        assert sensor_id(hass, config_entry) is not None
        await save_alt_options(hass, config_entry, {})
        assert sensor_id(hass, config_entry) is None
        # Cleared is saved as an empty value, because setup keeps the cost in the entry data.
        assert not config_entry.options.get(CONF_ALT_HEAT_COST)

    async def test_another_page_keeps_the_saved_cost(self, hass_in_scenario, config_entry):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        await save_alt_options(hass, config_entry, {CONF_ALT_HEAT_ENABLED: True, CONF_ALT_HEAT_COST: CHEAP_OIL})
        result = await options_wizard(hass, config_entry, {"charge_planning": {"battery_min_soc_pct": 12}})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert config_entry.options[CONF_ALT_HEAT_COST] == pytest.approx(CHEAP_OIL)
        assert sensor_id(hass, config_entry) is not None


class TestImmersionSwitchAddedAfterTheCost:
    @pytest.fixture
    def config_entry(self):
        data = full_config_data()
        data.pop(CONF_IMMERSION_SWITCH)
        return _entry(data, {CONF_ALT_HEAT_ENABLED: True, CONF_ALT_HEAT_COST: CHEAP_OIL})

    async def test_there_is_nothing_to_compare_with_until_a_switch_is_set(
        self, hass_in_scenario, config_entry
    ):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        assert sensor_id(hass, config_entry) is None
        assert config_entry.runtime_data.data.water_heating_advice is None

        hass.config_entries.async_update_entry(
            config_entry,
            options={**config_entry.options, CONF_IMMERSION_SWITCH: "switch.immersion_heater"},
        )
        await hass.async_block_till_done()
        assert sensor_id(hass, config_entry) is not None


class TestCostSensor:
    @pytest.fixture
    def config_entry(self):
        return _entry(
            full_config_data(),
            {
                CONF_ALT_HEAT_ENABLED: True,
                CONF_ALT_HEAT_COST: DEAR_OIL,
                CONF_ALT_HEAT_COST_ENTITY: PRICE_SENSOR,
            },
        )

    async def test_the_sensor_overrides_the_saved_number_and_follows_it(
        self, hass_in_scenario, config_entry
    ):
        hass = hass_in_scenario
        hass.states.async_set(PRICE_SENSOR, str(CHEAP_OIL))
        await set_up(hass, config_entry)
        entity_id = sensor_id(hass, config_entry)
        await refresh(hass, config_entry)
        assert hass.states.get(entity_id).state == "alternative"

        hass.states.async_set(PRICE_SENSOR, str(DEAR_OIL))
        await refresh(hass, config_entry)
        assert hass.states.get(entity_id).state == "electricity"

    async def test_an_unavailable_sensor_falls_back_to_the_saved_number(
        self, hass_in_scenario, config_entry
    ):
        hass = hass_in_scenario
        hass.states.async_set(PRICE_SENSOR, "unavailable")
        await set_up(hass, config_entry)
        await refresh(hass, config_entry)
        assert hass.states.get(sensor_id(hass, config_entry)).state == "electricity"

    async def test_with_no_number_and_no_reading_the_sensor_is_unavailable(
        self, hass_in_scenario
    ):
        hass = hass_in_scenario
        entry = _entry(
            full_config_data(), {CONF_ALT_HEAT_ENABLED: True, CONF_ALT_HEAT_COST_ENTITY: PRICE_SENSOR}
        )
        hass.states.async_set(PRICE_SENSOR, "unknown")
        await set_up(hass, entry)
        await refresh(hass, entry)
        assert hass.states.get(sensor_id(hass, entry)).state == "unavailable"


class TestDashboardTile:
    @pytest.fixture
    def config_entry(self):
        return _entry(full_config_data())

    async def shown_suggestions(self, hass, stored: dict) -> list[str]:
        """The cards shown now that print the cheapest source sensor's suggestion."""
        states = {state.entity_id: state.state for state in hass.states.async_all()}
        cards = all_cards(seen(stored, states)["views"])
        return [
            c["content"]
            for c in cards
            if c["type"] == "markdown" and "water_heating_cheapest_source', 'suggestion'" in c["content"]
        ]

    async def test_a_stored_file_shows_the_suggestion_once_alternative_heating_is_set(
        self, hass_in_scenario, config_entry
    ):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        stored = await async_dashboard_for_websocket(hass, is_admin=True)
        assert await self.shown_suggestions(hass, stored) == []

        await save_alt_options(hass, config_entry, {CONF_ALT_HEAT_ENABLED: True, CONF_ALT_HEAT_COST: CHEAP_OIL})
        await refresh(hass, config_entry)
        assert len(await self.shown_suggestions(hass, stored)) == 1

        await save_alt_options(hass, config_entry, {})
        assert await self.shown_suggestions(hass, stored) == []


class TestTheTrigger:
    """The trigger sensor sits beside the advice and follows the same cost."""

    @pytest.fixture
    def config_entry(self):
        return _entry(full_config_data())

    async def test_it_is_not_created_without_alternative_heating(
        self, hass_in_scenario, config_entry
    ):
        await set_up(hass_in_scenario, config_entry)

        assert sensor_id(hass_in_scenario, config_entry, TRIGGER_KEY) is None

    async def test_cooling_water_with_a_cheaper_alternative_is_keep_warm(
        self, hass_in_scenario, config_entry
    ):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        await save_alt_options(
            hass, config_entry, {CONF_ALT_HEAT_ENABLED: True, CONF_ALT_HEAT_COST: CHEAP_OIL}
        )
        await refresh(hass, config_entry)

        state = hass.states.get(sensor_id(hass, config_entry, TRIGGER_KEY))

        # This install has water at 48.2, under the lower boundary, with oil far cheaper.
        assert state.state == "keep_warm"
        assert state.attributes["run_minutes"] % 5 == 0
        assert state.attributes["saving_per_kwh"] > 0
        assert "start_by" not in state.attributes
        assert state.attributes["alt_label"] == "Oil"

    async def test_a_dearer_alternative_is_idle(self, hass_in_scenario, config_entry):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        await save_alt_options(
            hass, config_entry, {CONF_ALT_HEAT_ENABLED: True, CONF_ALT_HEAT_COST: DEAR_OIL}
        )
        await refresh(hass, config_entry)

        state = hass.states.get(sensor_id(hass, config_entry, TRIGGER_KEY))

        assert state.state == "idle"
        assert "run_minutes" not in state.attributes

    async def test_clearing_the_cost_removes_the_trigger_with_the_advice(
        self, hass_in_scenario, config_entry
    ):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        await save_alt_options(
            hass, config_entry, {CONF_ALT_HEAT_ENABLED: True, CONF_ALT_HEAT_COST: CHEAP_OIL}
        )
        assert sensor_id(hass, config_entry, TRIGGER_KEY) is not None

        await save_alt_options(hass, config_entry, {})

        assert sensor_id(hass, config_entry, TRIGGER_KEY) is None
