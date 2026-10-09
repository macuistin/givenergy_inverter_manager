"""The suggested oil schedule in real Home Assistant, with the record in real storage.

The record of the immersion's grid heating is read from the stored data at setup, filled each
cycle only while an oil price is set, and shown as attributes of the cheapest source sensor,
apart from the live suggestion. The scenario is 13:00 local on 15 June 2026.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from conftest import MIDDAY, SERIAL, full_config_data
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.accumulation import (
    _STORAGE_KEY,
    AccumulationState,
    _serialize,
)
from custom_components.givenergy_inverter_manager.const import (
    CONF_OIL_PRICE_PER_LITRE,
    DOMAIN,
)

KEY = "water_heating_cheapest_source"
CHEAP_OIL = 0.05  # per litre: far cheaper than any grid rate
HEAT_KEY = "immersion_heat_history"


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


def _seed(hass_storage, days: range) -> None:
    """Storage with the immersion heating 1.5 kWh at 0.30 at 13:00 on each of these days."""
    state = AccumulationState()
    state.last_reset_iso = "2026-06-15T00:00:00+01:00"
    for day in days:
        state.immersion_heat_log.add(datetime(2026, 6, day, 13, 30), 1.5, 0.45)
    hass_storage[_STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": _STORAGE_KEY,
        "data": _serialize(state),
    }


async def _set_up(hass, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _cycle(hass, freezer, entry, count: int = 2) -> None:
    """Run cycles 30 seconds apart, so each has an interval to record."""
    for _ in range(count):
        freezer.tick(30)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


def _sensor(hass, entry):
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{KEY}")
    return None if entity_id is None else hass.states.get(entity_id)


class TestWithAnOilPrice:
    @pytest.fixture
    def config_entry(self):
        return _entry({CONF_OIL_PRICE_PER_LITRE: CHEAP_OIL})

    async def test_a_week_of_stored_heating_gives_the_schedule_attributes(
        self, hass, hass_in_scenario, freezer, config_entry, hass_storage
    ):
        _seed(hass_storage, range(7, 15))
        await _set_up(hass_in_scenario, config_entry)
        await _cycle(hass, freezer, config_entry)
        attributes = _sensor(hass, config_entry).attributes
        assert attributes["oil_schedule_days"] == 8
        assert attributes["oil_schedule"] == ["12:30 to 13:00"]
        assert attributes["oil_schedule_saving"] == pytest.approx(3.5, abs=0.1)
        assert "Running the oil from 12:30 to 13:00" in attributes["oil_schedule_suggestion"]

    async def test_the_live_suggestion_is_left_alone(
        self, hass, hass_in_scenario, freezer, config_entry, hass_storage
    ):
        _seed(hass_storage, range(7, 15))
        await _set_up(hass_in_scenario, config_entry)
        await _cycle(hass, freezer, config_entry)
        attributes = _sensor(hass, config_entry).attributes
        assert "Over the last" not in attributes["suggestion"]

    async def test_with_too_few_days_the_schedule_attributes_are_absent(
        self, hass, hass_in_scenario, freezer, config_entry, hass_storage
    ):
        _seed(hass_storage, range(9, 15))
        await _set_up(hass_in_scenario, config_entry)
        await _cycle(hass, freezer, config_entry)
        attributes = _sensor(hass, config_entry).attributes
        assert not {name for name in attributes if name.startswith("oil_schedule")}

    async def test_the_record_is_read_back_from_storage_and_saved_again(
        self, hass, hass_in_scenario, freezer, config_entry, hass_storage
    ):
        _seed(hass_storage, range(7, 15))
        await _set_up(hass_in_scenario, config_entry)
        log = config_entry.runtime_data._acc.immersion_heat_log
        assert [d.date for d in log.days][0] == "2026-06-07"
        assert log.days[0].kwh[13] == pytest.approx(1.5)

        await _cycle(hass, freezer, config_entry)
        await config_entry.runtime_data._acc.async_save()
        saved = hass_storage[_STORAGE_KEY]["data"][HEAT_KEY]
        assert [d["date"] for d in saved][-1] == "2026-06-15"
        assert len(saved) == 9

    async def test_each_cycle_notes_the_day(
        self, hass, hass_in_scenario, freezer, config_entry
    ):
        await _set_up(hass_in_scenario, config_entry)
        await _cycle(hass, freezer, config_entry)
        log = config_entry.runtime_data._acc.immersion_heat_log
        assert [d.date for d in log.days] == ["2026-06-15"]


class TestWithNoOilPrice:
    @pytest.fixture
    def config_entry(self):
        return _entry({})

    async def test_nothing_is_recorded_or_created_or_stored(
        self, hass, hass_in_scenario, freezer, config_entry
    ):
        await _set_up(hass_in_scenario, config_entry)
        await _cycle(hass, freezer, config_entry, count=3)
        acc = config_entry.runtime_data._acc
        assert _sensor(hass, config_entry) is None
        assert acc.immersion_heat_log.days == []
        assert HEAT_KEY not in _serialize(acc.state)

    async def test_a_stored_record_is_kept_but_not_used(
        self, hass, hass_in_scenario, freezer, config_entry, hass_storage
    ):
        _seed(hass_storage, range(7, 15))
        await _set_up(hass_in_scenario, config_entry)
        await _cycle(hass, freezer, config_entry)
        assert config_entry.runtime_data.data.oil_schedule is None
        assert len(config_entry.runtime_data._acc.immersion_heat_log.days) == 8
