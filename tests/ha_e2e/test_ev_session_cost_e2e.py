"""EV Session Cost end to end: plug in, charge, unplug, and the session survives a restart."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import CHEAP_NIGHT, discover_the_charger, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import DOMAIN

# House load 800 W plus the car at 7.2 kW, all imported from the grid in the cheap-rate window.
EV_NIGHT = replace(CHEAP_NIGHT, name="ev_cheap_night", grid_w=-8000.0, load_w=8000.0)

PLUG = "sensor.myenergi_zappi_plug_status"
STATUS = "sensor.myenergi_zappi_status"
POWER = "sensor.myenergi_zappi_internal_load_ct1"
UNPLUGGED = {
    PLUG: "EV Disconnected",
    STATUS: "Paused",
    POWER: "0",
    "sensor.myenergi_zappi_charge_added_session": "0",
    "sensor.myenergi_zappi_serial_number": "21637627",
    "select.myenergi_zappi_charge_mode": "Eco+",
}
CHARGING = {PLUG: "EV Connected", STATUS: "Boosting", POWER: "7200"}


def _publish(hass, states: dict) -> None:
    for entity_id, value in states.items():
        hass.states.async_set(entity_id, value)


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=full_config_data(),
        unique_id="ab1234g567",
        version=1,
    )


async def _set_up(hass, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def _cycles(hass, entry, freezer, count: int) -> None:
    for _ in range(count):
        freezer.tick(timedelta(seconds=60))
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


def _state(hass, entry):
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_ev_session_cost"
    )
    assert entity_id == "sensor.ev_charger_session_cost"
    return hass.states.get(entity_id)


@pytest.mark.parametrize("scenario", [EV_NIGHT], ids=lambda s: s.name)
async def test_a_charge_is_priced_listed_and_kept_across_a_restart(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    _publish(hass, UNPLUGGED)
    entry = _entry()
    entry.add_to_hass(hass)
    await _set_up(hass, entry)

    before = _state(hass, entry)
    assert before.state == "unknown"
    assert before.attributes["recent_table"] == "No finished charges yet."

    _publish(hass, CHARGING)
    await _cycles(hass, entry, freezer, 5)
    running = _state(hass, entry)
    today = entry.runtime_data.data.today
    assert float(running.state) == pytest.approx(today.zappi_cost, abs=1e-4)
    assert float(running.state) > 0
    assert running.attributes["unit_of_measurement"] == "€"
    assert running.attributes["device_class"] == "monetary"
    assert "state_class" not in running.attributes
    assert running.attributes["started"] is not None
    assert running.attributes["ended"] is None
    assert running.attributes["recent_sessions"] == []

    _publish(hass, {PLUG: "EV Disconnected", STATUS: "Paused", POWER: "0"})
    await _cycles(hass, entry, freezer, 1)
    finished = _state(hass, entry)
    assert finished.attributes["ended"] is not None
    [row] = finished.attributes["recent_sessions"]
    assert row["cost"] == pytest.approx(float(finished.state), abs=1e-4)
    assert row["energy_kwh"] == pytest.approx(today.zappi_kwh, abs=1e-3)
    assert row["per_kwh"] == pytest.approx(row["cost"] / row["energy_kwh"], rel=1e-3)
    assert row["solar_kwh"] is None
    assert finished.attributes["recent_table"].startswith("| Charge | Energy | Cost | Per kWh |")

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await _set_up(hass, entry)
    await _cycles(hass, entry, freezer, 1)
    restored = _state(hass, entry)
    assert restored.attributes["recent_sessions"] == finished.attributes["recent_sessions"]
    assert float(restored.state) == pytest.approx(float(finished.state))

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize("scenario", [EV_NIGHT], ids=lambda s: s.name)
async def test_a_running_session_survives_a_restart(hass_in_scenario, service_calls, freezer):
    hass = hass_in_scenario
    _publish(hass, {**UNPLUGGED, **CHARGING})
    entry = _entry()
    entry.add_to_hass(hass)
    await _set_up(hass, entry)
    await _cycles(hass, entry, freezer, 4)
    started = _state(hass, entry).attributes["started"]
    cost_before = float(_state(hass, entry).state)

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await _set_up(hass, entry)
    await _cycles(hass, entry, freezer, 3)
    after = _state(hass, entry)
    assert after.attributes["started"] == started
    assert float(after.state) > cost_before

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _registered(hass, entry) -> bool:
    unique_id = f"{entry.entry_id}_ev_session_cost"
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id) is not None


@pytest.mark.parametrize("scenario", [EV_NIGHT], ids=lambda s: s.name)
async def test_no_charger_no_sensor_and_a_charger_added_later_starts_counting(
    hass_in_scenario, service_calls, freezer
):
    hass = hass_in_scenario
    entry = _entry()
    entry.add_to_hass(hass)
    await _set_up(hass, entry)
    await _cycles(hass, entry, freezer, 2)
    assert not _registered(hass, entry)
    assert entry.runtime_data._acc.ev_sessions.is_empty

    _publish(hass, {**UNPLUGGED, **CHARGING})
    await discover_the_charger(hass, entry)
    await _cycles(hass, entry, freezer, 3)
    assert _registered(hass, entry)
    state = _state(hass, entry)
    assert state.attributes["started"] is not None
    assert float(state.state) > 0

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
