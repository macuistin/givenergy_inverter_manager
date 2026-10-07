"""Devices that are optional, or that arrive after the integration: end to end in real Home Assistant.

* An EV charger whose integration publishes its entities in stages is completed by the
  five-minute rediscovery, with no reload.
* A manual immersion run with no temperature sensor ends by itself, instead of heating for ever.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import IMMERSION_SWITCH, MIDDAY, SERIAL, full_config_data
from homeassistant.components.switch import DATA_COMPONENT
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_TEMP_SENSOR,
    DOMAIN,
    SENSOR_OUTAGE_HOLD_LIMIT_S,
)

CYCLE = timedelta(seconds=30)
CYCLES_PER_REDISCOVERY = 10  # the coordinator rescans every tenth cycle

ZAPPI_PLUG = "sensor.myenergi_zappi_plug_status"
ZAPPI_POWER = "sensor.myenergi_zappi_internal_load_ct1"
ZAPPI_SESSION = "sensor.myenergi_zappi_charge_added_session"
ZAPPI_MODE = "select.myenergi_zappi_charge_mode"


@pytest.fixture
def scenario():
    return MIDDAY


async def set_up(hass, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def cycles(hass, entry, freezer, count: int) -> None:
    for _ in range(count):
        freezer.tick(CYCLE)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


def make_entry(data: dict) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=data,
        unique_id=SERIAL,
        version=1,
    )


class TestEvChargerPublishedInStages:
    @pytest.fixture
    async def entry(self, hass_in_scenario, service_calls):
        """Set up while the charger has a status and a power entity but nothing else."""
        hass = hass_in_scenario
        hass.states.async_set(ZAPPI_PLUG, "EV Connected")
        hass.states.async_set(ZAPPI_POWER, "0")
        entry = make_entry(full_config_data())
        await set_up(hass, entry)
        return entry

    async def test_the_charge_mode_and_session_entities_are_found_when_they_appear(
        self, hass_in_scenario, entry, freezer
    ):
        hass = hass_in_scenario
        await cycles(hass, entry, freezer, 3)
        charger = entry.runtime_data._ev_charger
        assert charger is not None
        assert charger.power_entity == ZAPPI_POWER
        assert charger.charge_mode_entity is None
        assert charger.session_energy_entity is None

        hass.states.async_set(ZAPPI_SESSION, "1.5")
        hass.states.async_set(ZAPPI_MODE, "Fast")
        await cycles(hass, entry, freezer, CYCLES_PER_REDISCOVERY)

        assert charger.charge_mode_entity == ZAPPI_MODE
        assert charger.session_energy_entity == ZAPPI_SESSION
        assert charger.session_kwh == pytest.approx(1.5)
        assert charger.charge_mode == "Fast"
        assert entry.runtime_data._ev_charger is charger

    async def test_the_integration_is_not_reloaded_to_find_them(
        self, hass_in_scenario, entry, freezer
    ):
        hass = hass_in_scenario
        coordinator = entry.runtime_data
        hass.states.async_set(ZAPPI_MODE, "Fast")
        await cycles(hass, entry, freezer, CYCLES_PER_REDISCOVERY)
        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data is coordinator


class TestImmersionWithoutATemperatureSensor:
    @pytest.fixture
    async def entry(self, hass_in_scenario, service_calls):
        hass = hass_in_scenario
        data = full_config_data()
        data.pop(CONF_IMMERSION_TEMP_SENSOR)
        entry = make_entry(data)
        await set_up(hass, entry)
        return entry

    @pytest.fixture
    def switch_calls(self, hass_in_scenario, entry) -> list[str]:
        """The real immersion switch: records each call and follows it."""
        hass = hass_in_scenario
        calls: list[str] = []

        def handler(service: str, state: str):
            async def handle(call) -> None:
                if call.data["entity_id"] == IMMERSION_SWITCH:
                    calls.append(service)
                    hass.states.async_set(IMMERSION_SWITCH, state)

            return handle

        for service, state in (("turn_on", "on"), ("turn_off", "off")):
            hass.services.async_register("switch", service, handler(service, state))
        return calls

    async def press_managed_switch_on(self, hass, entry) -> None:
        entity_id = er.async_get(hass).async_get_entity_id(
            "switch", DOMAIN, f"{entry.entry_id}_immersion_managed"
        )
        await hass.data[DATA_COMPONENT].get_entity(entity_id).async_turn_on()
        await hass.async_block_till_done()

    async def test_a_manual_run_ends_after_the_outage_hold_limit(
        self, hass_in_scenario, entry, switch_calls, freezer
    ):
        hass = hass_in_scenario
        immersion = entry.runtime_data.immersion
        await self.press_managed_switch_on(hass, entry)
        assert switch_calls == ["turn_on"]

        held_for = timedelta(seconds=SENSOR_OUTAGE_HOLD_LIMIT_S)
        await cycles(hass, entry, freezer, int(held_for / CYCLE) - 2)
        assert immersion.override is True
        assert switch_calls == ["turn_on"]

        await cycles(hass, entry, freezer, 4)
        assert immersion.override is None
        assert switch_calls == ["turn_on", "turn_off"]
        assert hass.states.get(IMMERSION_SWITCH).state == "off"

    async def test_an_external_turn_on_ends_after_the_outage_hold_limit(
        self, hass_in_scenario, entry, switch_calls, freezer
    ):
        hass = hass_in_scenario
        immersion = entry.runtime_data.immersion
        await cycles(hass, entry, freezer, 2)
        immersion.last_commanded_on = False
        hass.states.async_set(IMMERSION_SWITCH, "on")  # a wall button or another automation
        await cycles(hass, entry, freezer, 2)
        assert immersion.override is True

        await cycles(hass, entry, freezer, int(timedelta(seconds=SENSOR_OUTAGE_HOLD_LIMIT_S) / CYCLE) + 2)
        assert immersion.override is None
        assert switch_calls == ["turn_off"]
