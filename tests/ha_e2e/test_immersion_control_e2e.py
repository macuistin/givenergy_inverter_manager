"""The managed immersion switch: decision to real-switch actuation against real Home Assistant.

The real immersion switch is a stand-in service pair that records each call. By default it
also moves the switch state, like a real switch would. The engine's decision is steered with
the water temperature: below the minimum (50) it heats regardless of surplus, at or above the
target (55) it stops.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import IMMERSION_SWITCH, IMMERSION_TEMP, MIDDAY, SERIAL, SOLAR, full_config_data
from homeassistant.components.switch import DATA_COMPONENT
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import (
    CONF_DRY_RUN,
    DOMAIN,
    IMMERSION_SWITCH_COOLDOWN_MINUTES,
)

COLD = 48.2  # below the 50 minimum: the engine wants the heater on
WARM = 52.0  # between minimum and target, no surplus needed to be off
HOT = 56.0  # above the 55 target: the engine wants it off
PAST_COOLDOWN = timedelta(minutes=IMMERSION_SWITCH_COOLDOWN_MINUTES + 1)


@pytest.fixture
def scenario():
    return MIDDAY


class RealSwitch:
    """Records calls to the real immersion switch and optionally follows them."""

    def __init__(self, hass) -> None:
        self.hass = hass
        self.calls: list[str] = []
        self.follow = True
        for service, state in (("turn_on", "on"), ("turn_off", "off")):
            hass.services.async_register("switch", service, self._handler(service, state))

    def _handler(self, service: str, state: str):
        async def handle(call) -> None:
            entity_id = call.data["entity_id"]
            if entity_id != IMMERSION_SWITCH:
                return
            self.calls.append(service)
            if self.follow:
                self.hass.states.async_set(IMMERSION_SWITCH, state)

        return handle


@pytest.fixture
def real_switch(hass, loaded_entry) -> RealSwitch:
    """Registered after setup, because the switch platform registers its own services."""
    return RealSwitch(hass)


async def cycle(hass, entry) -> None:
    """Run one coordinator cycle now and let the actuation task finish."""
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def water(hass, temperature: float) -> None:
    hass.states.async_set(IMMERSION_TEMP, temperature)


def managed_switch(hass, entry):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_immersion_managed")
    assert entity_id is not None
    return hass.data[DATA_COMPONENT].get_entity(entity_id)


def auto_switch(hass, entry):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_auto_immersion")
    return hass.data[DATA_COMPONENT].get_entity(entity_id)


class TestIndependenceFromTheEntity:
    @pytest.fixture
    def managed_switch_disabled(self, hass, config_entry):
        """Register the managed switch as disabled before the entry loads."""
        config_entry.add_to_hass(hass)
        er.async_get(hass).async_get_or_create(
            "switch",
            DOMAIN,
            f"{config_entry.entry_id}_immersion_managed",
            config_entry=config_entry,
            disabled_by=er.RegistryEntryDisabler.USER,
        )

    async def test_diversion_works_with_the_managed_switch_disabled(
        self, hass, managed_switch_disabled, loaded_entry, real_switch
    ):
        assert managed_switch(hass, loaded_entry) is None
        water(hass, COLD)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]
        water(hass, HOT)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on", "turn_off"]

    async def test_the_setup_cycle_only_observes(self, hass, loaded_entry, service_calls):
        """The water starts cold, so the engine wants the heater on, but nothing is sent yet."""
        sent = [c for c in service_calls["switch.turn_on"] if c.data["entity_id"] == IMMERSION_SWITCH]
        assert loaded_entry.runtime_data.data.should_divert_immersion is True
        assert sent == []


class TestAutomaticActuation:
    async def test_decision_on_turns_the_real_switch_on(self, hass, loaded_entry, real_switch):
        water(hass, COLD)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]

    async def test_decision_off_turns_a_running_switch_off(self, hass, loaded_entry, real_switch):
        hass.states.async_set(IMMERSION_SWITCH, "on")
        water(hass, HOT)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_off"]

    async def test_no_call_when_the_switch_already_matches(self, hass, loaded_entry, real_switch):
        hass.states.async_set(IMMERSION_SWITCH, "on")
        water(hass, COLD)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == []

    async def test_managed_switch_reports_the_decision(self, hass, loaded_entry, real_switch):
        water(hass, COLD)
        await cycle(hass, loaded_entry)
        assert managed_switch(hass, loaded_entry).is_on is True
        water(hass, HOT)
        await cycle(hass, loaded_entry)
        assert managed_switch(hass, loaded_entry).is_on is False

    async def test_auto_divert_switched_off_stops_a_running_heater(
        self, hass, loaded_entry, real_switch
    ):
        hass.states.async_set(IMMERSION_SWITCH, "on")
        water(hass, COLD)
        await auto_switch(hass, loaded_entry).async_turn_off()
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_off"]


class TestCooldown:
    async def test_a_second_write_inside_the_cooldown_is_skipped(
        self, hass, loaded_entry, real_switch
    ):
        real_switch.follow = False
        water(hass, COLD)
        await cycle(hass, loaded_entry)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]

    async def test_a_switch_that_never_followed_is_read_as_turned_off_externally(
        self, hass, loaded_entry, real_switch, freezer
    ):
        real_switch.follow = False
        water(hass, COLD)
        await cycle(hass, loaded_entry)
        freezer.tick(PAST_COOLDOWN)
        await cycle(hass, loaded_entry)
        # The off state is respected: no retry, and the run-to-target override is not set.
        assert real_switch.calls == ["turn_on"]
        assert loaded_entry.runtime_data.override_immersion is None

    async def test_overheat_turns_off_even_inside_the_cooldown(
        self, hass, loaded_entry, real_switch
    ):
        water(hass, COLD)
        await cycle(hass, loaded_entry)
        water(hass, HOT)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on", "turn_off"]

    async def test_a_turn_off_below_target_waits_for_the_cooldown(
        self, hass, loaded_entry, real_switch, freezer
    ):
        water(hass, COLD)
        await cycle(hass, loaded_entry)
        hass.states.async_set(SOLAR, 0)
        water(hass, WARM)
        await auto_switch(hass, loaded_entry).async_turn_off()
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]
        freezer.tick(PAST_COOLDOWN)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on", "turn_off"]


class TestManualSwitch:
    async def test_turn_on_calls_the_real_switch_and_runs_to_target(
        self, hass, loaded_entry, real_switch
    ):
        water(hass, WARM)
        await managed_switch(hass, loaded_entry).async_turn_on()
        await hass.async_block_till_done()
        assert real_switch.calls == ["turn_on"]
        await cycle(hass, loaded_entry)
        data = loaded_entry.runtime_data.data
        assert data.should_divert_immersion is True
        assert data.divert_reason == "Manual — running to 55°C (52.0°C now)"

    async def test_manual_run_releases_at_target_and_switches_off(
        self, hass, loaded_entry, real_switch
    ):
        water(hass, WARM)
        await managed_switch(hass, loaded_entry).async_turn_on()
        await hass.async_block_till_done()
        water(hass, HOT)
        await cycle(hass, loaded_entry)
        assert loaded_entry.runtime_data.override_immersion is None
        assert real_switch.calls == ["turn_on", "turn_off"]

    async def test_turn_off_calls_the_real_switch(self, hass, loaded_entry, real_switch):
        hass.states.async_set(IMMERSION_SWITCH, "on")
        water(hass, WARM)
        await managed_switch(hass, loaded_entry).async_turn_off()
        await hass.async_block_till_done()
        assert real_switch.calls == ["turn_off"]

    async def test_turn_off_blocks_an_automatic_restart_until_the_cooldown_ends(
        self, hass, loaded_entry, real_switch, freezer
    ):
        hass.states.async_set(IMMERSION_SWITCH, "on")
        water(hass, COLD)
        await managed_switch(hass, loaded_entry).async_turn_off()
        await hass.async_block_till_done()
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_off"]
        freezer.tick(PAST_COOLDOWN)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_off", "turn_on"]

    async def test_turn_on_clears_a_running_cooldown(self, hass, loaded_entry, real_switch):
        hass.states.async_set(IMMERSION_SWITCH, "on")
        water(hass, WARM)
        await managed_switch(hass, loaded_entry).async_turn_off()
        await hass.async_block_till_done()
        await managed_switch(hass, loaded_entry).async_turn_on()
        await hass.async_block_till_done()
        assert real_switch.calls == ["turn_off", "turn_on"]
        # With the cooldown cleared, a toggle by something else is noticed straight away.
        hass.states.async_set(IMMERSION_SWITCH, "off")
        await cycle(hass, loaded_entry)
        assert loaded_entry.runtime_data.override_immersion is None


class TestExternalToggle:
    async def test_external_turn_on_runs_to_target(
        self, hass, loaded_entry, real_switch, freezer
    ):
        hass.states.async_set(IMMERSION_SWITCH, "on")
        water(hass, WARM)
        await managed_switch(hass, loaded_entry).async_turn_off()
        await hass.async_block_till_done()
        freezer.tick(PAST_COOLDOWN)
        hass.states.async_set(IMMERSION_SWITCH, "on")  # an automation or the wall button
        await cycle(hass, loaded_entry)  # this cycle notices the toggle
        assert loaded_entry.runtime_data.override_immersion is True
        await cycle(hass, loaded_entry)  # the next cycle decides with the override
        data = loaded_entry.runtime_data.data
        assert data.divert_reason == "Manual — running to 55°C (52.0°C now)"
        assert real_switch.calls == ["turn_off"]

    async def test_external_turn_off_is_respected_for_the_cooldown(
        self, hass, loaded_entry, real_switch, freezer
    ):
        water(hass, WARM)
        await managed_switch(hass, loaded_entry).async_turn_on()
        await hass.async_block_till_done()
        hass.states.async_set(IMMERSION_SWITCH, "off")  # turned off by something else
        await cycle(hass, loaded_entry)
        assert loaded_entry.runtime_data.override_immersion is None
        water(hass, COLD)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]  # the cooldown blocks the restart
        freezer.tick(PAST_COOLDOWN)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on", "turn_on"]

    async def test_a_toggle_inside_the_cooldown_is_not_read_as_external(
        self, hass, loaded_entry, real_switch
    ):
        water(hass, COLD)
        await cycle(hass, loaded_entry)  # automatic turn_on starts a cooldown
        hass.states.async_set(IMMERSION_SWITCH, "off")
        await cycle(hass, loaded_entry)
        assert loaded_entry.runtime_data.override_immersion is None
        assert real_switch.calls == ["turn_on"]


class TestDryRun:
    @pytest.fixture
    def config_entry(self):
        from pytest_homeassistant_custom_component.common import MockConfigEntry

        return MockConfigEntry(
            domain=DOMAIN,
            title="GivEnergy Inverter Manager",
            data={**full_config_data(), CONF_DRY_RUN: True},
            unique_id=SERIAL,
            version=1,
        )

    async def test_automatic_decision_is_recorded_not_sent(self, hass, loaded_entry, real_switch):
        water(hass, COLD)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == []
        assert "Would turn_on immersion heater" in loaded_entry.runtime_data.data.dry_run_last_skipped

    async def test_manual_turn_on_sends_nothing(self, hass, loaded_entry, real_switch):
        water(hass, WARM)
        await managed_switch(hass, loaded_entry).async_turn_on()
        await hass.async_block_till_done()
        assert real_switch.calls == []

    async def test_manual_turn_on_is_recorded_and_the_run_survives_the_next_cycle(
        self, hass, loaded_entry, real_switch, freezer
    ):
        water(hass, WARM)
        await managed_switch(hass, loaded_entry).async_turn_on()
        await hass.async_block_till_done()
        coordinator = loaded_entry.runtime_data
        assert "Would turn_on immersion heater" in coordinator.data.dry_run_last_skipped
        freezer.tick(PAST_COOLDOWN)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == []
        assert coordinator.immersion.manual_run_to_target is True
