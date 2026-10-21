"""An entry saved before the capacity and output sensors were offered picks them up at setup."""

from __future__ import annotations

import pytest
from conftest import CAPACITY, MIDDAY, PREFIX

from custom_components.givenergy_inverter_manager.const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_INVERTER_MAX_OUTPUT_ENTITY,
)

RATE = f"sensor.{PREFIX}_invertor_max_inv_rate"


@pytest.fixture
def scenario():
    return MIDDAY


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_an_older_entry_picks_the_givtcp_sensors_that_read_a_number(
    hass_in_scenario, service_calls, config_entry
):
    hass = hass_in_scenario
    hass.states.async_set(RATE, "5000", {"unit_of_measurement": "W"})

    await _setup(hass, config_entry)

    try:
        assert config_entry.options[CONF_BATTERY_CAPACITY_ENTITY] == CAPACITY
        assert config_entry.options[CONF_INVERTER_MAX_OUTPUT_ENTITY] == RATE
        assert config_entry.data[CONF_BATTERY_CAPACITY] == 9.5  # the typed value is kept
    finally:
        await hass.config_entries.async_unload(config_entry.entry_id)


async def test_a_sensor_the_user_cleared_stays_cleared(
    hass_in_scenario, service_calls, config_entry
):
    hass = hass_in_scenario
    hass.states.async_set(RATE, "5000", {"unit_of_measurement": "W"})
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_BATTERY_CAPACITY_ENTITY: ""}
    )

    await _setup_added(hass, config_entry)

    try:
        assert config_entry.options[CONF_BATTERY_CAPACITY_ENTITY] == ""
        assert config_entry.options[CONF_INVERTER_MAX_OUTPUT_ENTITY] == RATE
    finally:
        await hass.config_entries.async_unload(config_entry.entry_id)


async def test_a_sensor_that_reads_nothing_is_not_picked(
    hass_in_scenario, service_calls, config_entry
):
    hass = hass_in_scenario
    hass.states.async_set(CAPACITY, "unavailable")

    await _setup(hass, config_entry)

    try:
        assert CONF_BATTERY_CAPACITY_ENTITY not in config_entry.options
        assert CONF_INVERTER_MAX_OUTPUT_ENTITY not in config_entry.options
    finally:
        await hass.config_entries.async_unload(config_entry.entry_id)


async def _setup_added(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
