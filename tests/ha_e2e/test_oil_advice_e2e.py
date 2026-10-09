"""The oil water heating advice in real Home Assistant, through the real options flow.

With no oil price nothing is created or evaluated. Setting a price in the options (with an
immersion switch to compare with) creates the sensor after the reload. Clearing it removes the
sensor. A price sensor overrides the saved number.
"""

from __future__ import annotations

import pytest
from conftest import MIDDAY, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_SWITCH,
    CONF_OIL_PRICE_ENTITY,
    CONF_OIL_PRICE_PER_LITRE,
    DOMAIN,
)

KEY = "water_heating_cheapest_source"
PRICE_SENSOR = "sensor.oil_price"
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


def _form_values(fields: list[dict]) -> dict:
    values: dict = {}
    for field in fields:
        if field.get("type") == "expandable":
            values[field["name"]] = _form_values(field["schema"])
        elif "default" in field:
            values[field["name"]] = field["default"]
        elif "suggested_value" in field.get("description", {}):
            values[field["name"]] = field["description"]["suggested_value"]
    return values


async def save_oil_options(hass, entry, oil: dict | None, *, unsent: bool = False) -> None:
    """Open the options form and save it as the frontend would, with this oil section.

    {} is the section with both fields cleared. With *unsent* the section is left out.
    """
    result = await hass.config_entries.options.async_init(entry.entry_id)
    fields = cv.to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    payload = _form_values(fields)
    payload.pop("oil_settings", None)
    if not unsent:
        payload["oil_settings"] = oil or {}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=payload
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    assert entry.state is ConfigEntryState.LOADED


def sensor_id(hass, entry) -> str | None:
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{KEY}")


async def refresh(hass, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def set_up(hass, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


class TestNoOilPrice:
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
        await save_oil_options(hass, config_entry, {})
        assert sensor_id(hass, config_entry) is None
        assert CONF_OIL_PRICE_PER_LITRE not in config_entry.options


class TestAddedLater:
    @pytest.fixture
    def config_entry(self):
        return _entry(full_config_data())

    async def test_a_price_in_the_options_creates_the_sensor(
        self, hass_in_scenario, config_entry
    ):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        await save_oil_options(hass, config_entry, {CONF_OIL_PRICE_PER_LITRE: CHEAP_OIL})
        entity_id = sensor_id(hass, config_entry)
        assert entity_id is not None
        await refresh(hass, config_entry)
        state = hass.states.get(entity_id)
        assert state.state == "oil"
        assert "Heat the water with the oil system now" in state.attributes["suggestion"]
        assert state.attributes["oil_saving_per_kwh"] > 0

    async def test_a_dear_price_says_electricity(self, hass_in_scenario, config_entry):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        await save_oil_options(hass, config_entry, {CONF_OIL_PRICE_PER_LITRE: DEAR_OIL})
        await refresh(hass, config_entry)
        state = hass.states.get(sensor_id(hass, config_entry))
        assert state.state == "electricity"
        assert state.attributes["best_hours_for_oil"] == []

    async def test_clearing_the_price_removes_the_sensor(self, hass_in_scenario, config_entry):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        await save_oil_options(hass, config_entry, {CONF_OIL_PRICE_PER_LITRE: CHEAP_OIL})
        assert sensor_id(hass, config_entry) is not None
        await save_oil_options(hass, config_entry, {})
        assert sensor_id(hass, config_entry) is None
        assert CONF_OIL_PRICE_PER_LITRE not in config_entry.options

    async def test_an_unsent_section_keeps_the_saved_price(self, hass_in_scenario, config_entry):
        hass = hass_in_scenario
        await set_up(hass, config_entry)
        await save_oil_options(hass, config_entry, {CONF_OIL_PRICE_PER_LITRE: CHEAP_OIL})
        await save_oil_options(hass, config_entry, None, unsent=True)
        assert config_entry.options[CONF_OIL_PRICE_PER_LITRE] == pytest.approx(CHEAP_OIL)
        assert sensor_id(hass, config_entry) is not None


class TestImmersionSwitchAddedAfterThePrice:
    @pytest.fixture
    def config_entry(self):
        data = full_config_data()
        data.pop(CONF_IMMERSION_SWITCH)
        return _entry(data, {CONF_OIL_PRICE_PER_LITRE: CHEAP_OIL})

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


class TestPriceSensor:
    @pytest.fixture
    def config_entry(self):
        return _entry(
            full_config_data(),
            {CONF_OIL_PRICE_PER_LITRE: DEAR_OIL, CONF_OIL_PRICE_ENTITY: PRICE_SENSOR},
        )

    async def test_the_sensor_overrides_the_saved_number_and_follows_it(
        self, hass_in_scenario, config_entry
    ):
        hass = hass_in_scenario
        hass.states.async_set(PRICE_SENSOR, str(CHEAP_OIL))
        await set_up(hass, config_entry)
        entity_id = sensor_id(hass, config_entry)
        await refresh(hass, config_entry)
        assert hass.states.get(entity_id).state == "oil"

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
        entry = _entry(full_config_data(), {CONF_OIL_PRICE_ENTITY: PRICE_SENSOR})
        hass.states.async_set(PRICE_SENSOR, "unknown")
        await set_up(hass, entry)
        await refresh(hass, entry)
        assert hass.states.get(sensor_id(hass, entry)).state == "unavailable"
