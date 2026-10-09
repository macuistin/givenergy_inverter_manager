"""Scheduled immersion heating against real Home Assistant: cheapest window and ready-by times.

The real immersion switch is a stand-in that records each call and follows it. The test
clock is frozen at a winter night in Dublin, where the default tariff has its cheapest period,
Nightboost, from 02:00 to 04:00 inside the Night band from 23:00 to 08:00. The minimum
temperature is 45, the target 55 and the restart gap 5, so a fresh start needs water below 50.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import (
    CHEAP_NIGHT,
    IMMERSION_SWITCH,
    IMMERSION_TEMP,
    SERIAL,
    SOLAR,
    full_config_data,
)
from homeassistant.components.switch import DATA_COMPONENT
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import (
    CONF_DRY_RUN,
    CONF_IMMERSION_MIN_TEMP,
    CONF_IMMERSION_READY_TIMES,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    DOMAIN,
)

COLD = 46.0  # below the restart threshold of 50, above the minimum of 45
TARGET_REACHED = 55.5


@pytest.fixture
def scenario():
    return CHEAP_NIGHT


def _entry(**changes) -> MockConfigEntry:
    data = {**full_config_data(), CONF_IMMERSION_MIN_TEMP: 45, **changes}
    return MockConfigEntry(
        domain=DOMAIN, title="GivEnergy Inverter Manager", data=data, unique_id=SERIAL, version=1
    )


@pytest.fixture
def config_entry():
    return _entry()


class RealSwitch:
    """Records calls to the real immersion switch and follows them, like a real switch."""

    def __init__(self, hass) -> None:
        self.hass = hass
        self.calls: list[str] = []
        for service, state in (("turn_on", "on"), ("turn_off", "off")):
            hass.services.async_register("switch", service, self._handler(service, state))

    def _handler(self, service: str, state: str):
        async def handle(call) -> None:
            if call.data["entity_id"] != IMMERSION_SWITCH:
                return
            self.calls.append(service)
            self.hass.states.async_set(IMMERSION_SWITCH, state)

        return handle


@pytest.fixture
def real_switch(hass, loaded_entry) -> RealSwitch:
    return RealSwitch(hass)


def water(hass, temperature: float) -> None:
    hass.states.async_set(IMMERSION_TEMP, temperature)


async def cycle(hass, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def at(freezer, utc: str) -> None:
    """Move the clock to a time of day on the night the scenario starts."""
    freezer.move_to(f"2026-12-15 {utc}+00:00")


async def save_options(
    hass, entry, immersion: dict | None = None, ready: list[str] | None = None, expect="entry"
):
    """Open the options form and save it as the frontend would, with these immersion values."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    payload = _form_values(
        cv.to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    )
    section_values = payload["immersion_settings"]
    if immersion is not None:
        section_values = {"immersion_wattage_w": section_values["immersion_wattage_w"], **immersion}
    if ready is not None:
        section_values = {**section_values, CONF_IMMERSION_READY_TIMES: ready}
    payload["immersion_settings"] = section_values
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=payload
    )
    await hass.async_block_till_done()
    if expect == "entry":
        assert result["type"] is FlowResultType.CREATE_ENTRY, result
    else:
        assert result["type"] is FlowResultType.FORM, result
    return result


def _form_values(fields: list[dict]) -> dict:
    """What the frontend submits untouched: defaults and suggested values, section by section."""
    values: dict = {}
    for field in fields:
        if field.get("type") == "expandable":
            values[field["name"]] = _form_values(field["schema"])
        elif "default" in field:
            values[field["name"]] = field["default"]
        elif "suggested_value" in field.get("description", {}):
            values[field["name"]] = field["description"]["suggested_value"]
    return values


def schedule_switch(hass, entry):
    entity_id = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_immersion_schedule"
    )
    return None if entity_id is None else hass.data[DATA_COMPONENT].get_entity(entity_id)


async def opt_in(hass, entry) -> None:
    """Turn scheduled heating on while the water is warm, so nothing starts yet."""
    water(hass, 54.0)
    await schedule_switch(hass, entry).async_turn_on()
    await hass.async_block_till_done()


class TestCheapestWindow:
    async def test_cold_water_starts_at_window_open_and_stops_at_target(
        self, hass, loaded_entry, real_switch, freezer
    ):
        await opt_in(hass, loaded_entry)
        water(hass, COLD)
        at(freezer, "01:59:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == []
        at(freezer, "02:00:30")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]
        assert "Cheapest rate window (Nightboost 02:00 to 04:00)" in (
            loaded_entry.runtime_data.data.divert_reason
        )
        at(freezer, "03:10:00")
        water(hass, TARGET_REACHED)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on", "turn_off"]

    async def test_warm_water_does_nothing(self, hass, loaded_entry, real_switch, freezer):
        await opt_in(hass, loaded_entry)
        water(hass, 54.0)  # yesterday's solar left it warm
        at(freezer, "02:05:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == []

    async def test_the_window_end_stops_the_heater(self, hass, loaded_entry, real_switch, freezer):
        await opt_in(hass, loaded_entry)
        water(hass, COLD)
        at(freezer, "02:00:30")
        await cycle(hass, loaded_entry)
        water(hass, 52.0)  # not at target yet, and the window is about to close
        at(freezer, "03:59:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]
        at(freezer, "04:00:30")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on", "turn_off"]

    async def test_scheduled_heating_off_does_nothing(
        self, hass, loaded_entry, real_switch, freezer
    ):
        assert schedule_switch(hass, loaded_entry).is_on is False
        water(hass, COLD)
        at(freezer, "02:05:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == []

    async def test_the_opt_in_survives_a_cycle_and_a_turn_off_ends_it(
        self, hass, loaded_entry, real_switch, freezer
    ):
        await opt_in(hass, loaded_entry)
        assert loaded_entry.runtime_data.immersion_schedule_enabled is True
        await schedule_switch(hass, loaded_entry).async_turn_off()
        water(hass, COLD)
        at(freezer, "02:05:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == []

    async def test_a_heater_that_cuts_itself_off_is_turned_on_again(
        self, hass, loaded_entry, real_switch, freezer
    ):
        """The device's own 60 minute auto-off stops it with the water still below target."""
        await opt_in(hass, loaded_entry)
        water(hass, COLD)
        at(freezer, "02:00:30")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]
        water(hass, 51.0)  # inside the restart gap, so only the run in progress explains a restart
        hass.states.async_set(IMMERSION_SWITCH, "off")  # the device cut out
        at(freezer, "03:01:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]  # the cooldown holds the retry back
        at(freezer, "03:12:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on", "turn_on"]
        water(hass, TARGET_REACHED)
        at(freezer, "03:40:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on", "turn_on", "turn_off"]

    async def test_a_device_timer_start_above_target_is_switched_off_again(
        self, hass, loaded_entry, real_switch, freezer
    ):
        await opt_in(hass, loaded_entry)
        water(hass, COLD)
        at(freezer, "02:00:30")
        await cycle(hass, loaded_entry)
        water(hass, TARGET_REACHED)
        at(freezer, "02:50:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on", "turn_off"]
        # A timer of the device switches the heater on with the water already at target.
        hass.states.async_set(IMMERSION_SWITCH, "on")
        at(freezer, "03:20:00")
        await cycle(hass, loaded_entry)  # the toggle is noticed as a run to target
        await cycle(hass, loaded_entry)  # the target is already met, so the run is released
        assert real_switch.calls == ["turn_on", "turn_off", "turn_off"]
        assert loaded_entry.runtime_data.override_immersion is None


class TestDryRun:
    @pytest.fixture
    def config_entry(self):
        return _entry(**{CONF_DRY_RUN: True})

    async def test_dry_run_records_what_it_would_do_and_sends_nothing(
        self, hass, loaded_entry, real_switch, freezer
    ):
        await opt_in(hass, loaded_entry)
        water(hass, COLD)
        at(freezer, "02:00:30")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == []
        skipped = loaded_entry.runtime_data.data.dry_run_last_skipped
        assert "Would turn_on immersion heater" in skipped
        assert "Cheapest rate window" in skipped


class TestNoTemperatureSensor:
    @pytest.fixture
    def config_entry(self):
        data = full_config_data()
        data.pop(CONF_IMMERSION_TEMP_SENSOR)
        return MockConfigEntry(
            domain=DOMAIN,
            title="GivEnergy Inverter Manager",
            data=data,
            unique_id=SERIAL,
            version=1,
        )

    async def test_no_opt_in_exists_and_nothing_is_scheduled(
        self, hass, loaded_entry, real_switch, freezer
    ):
        assert schedule_switch(hass, loaded_entry) is None
        loaded_entry.runtime_data.immersion_schedule_enabled = True  # even if it were set
        at(freezer, "02:05:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == []

    async def test_solar_diversion_still_works_without_a_sensor(
        self, hass, loaded_entry, real_switch, freezer
    ):
        hass.states.async_set(SOLAR, 5500.0)
        hass.states.async_set("sensor.givtcp_ab1234g567_soc", 95.0)
        at(freezer, "12:00:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]


class TestReadyTimes:
    @pytest.fixture
    def config_entry(self):
        return _entry(**{CONF_IMMERSION_READY_TIMES: ["07:00", "19:00"]})

    async def test_a_cold_tank_at_17_00_is_topped_up_to_finish_by_19_00(
        self, hass, loaded_entry, real_switch, freezer
    ):
        await opt_in(hass, loaded_entry)
        water(hass, 46.0)  # 9 degrees short: about 1.2 hours at the assumed rate
        freezer.move_to("2026-12-15 17:00:00+00:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == []
        freezer.move_to("2026-12-15 17:50:00+00:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]
        assert "ready by 19:00" in loaded_entry.runtime_data.data.divert_reason

    async def test_the_sensor_says_whether_the_water_will_be_ready(
        self, hass, loaded_entry, real_switch, freezer
    ):
        await opt_in(hass, loaded_entry)
        water(hass, 46.0)
        freezer.move_to("2026-12-15 12:00:00+00:00")
        await cycle(hass, loaded_entry)
        state = hass.states.get("sensor.givenergy_inverter_manager_immersion_water_temperature")
        assert state.attributes["ready_by"] == "19:00"
        assert state.attributes["expected_ready"] is True
        assert state.attributes["heating_rate_source"] == "assumed"

    async def test_a_warm_tank_needs_nothing(self, hass, loaded_entry, real_switch, freezer):
        await opt_in(hass, loaded_entry)
        water(hass, 55.0)
        freezer.move_to("2026-12-15 18:30:00+00:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == []

    async def test_solar_already_heating_means_no_grid_top_up_is_named(
        self, hass, loaded_entry, real_switch, freezer
    ):
        await opt_in(hass, loaded_entry)
        water(hass, 46.0)
        hass.states.async_set(SOLAR, 5500.0)
        hass.states.async_set("sensor.givtcp_ab1234g567_soc", 95.0)
        freezer.move_to("2026-12-15 12:00:00+00:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]
        assert "Solar surplus" in loaded_entry.runtime_data.data.divert_reason

    async def test_ready_times_do_nothing_until_scheduled_heating_is_on(
        self, hass, loaded_entry, real_switch, freezer
    ):
        water(hass, 46.0)
        freezer.move_to("2026-12-15 18:30:00+00:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == []

    async def test_a_finished_run_teaches_the_heating_rate(
        self, hass, loaded_entry, real_switch, freezer
    ):
        await opt_in(hass, loaded_entry)
        water(hass, 46.0)
        freezer.move_to("2026-12-15 17:50:00+00:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]
        # Cycles are 30 seconds apart in production. Four minutes keeps the test short and is
        # still inside the gap that would split a run.
        for step in range(1, 12):
            freezer.move_to("2026-12-15 17:50:00+00:00")
            freezer.tick(timedelta(minutes=4 * step))
            water(hass, 46.0 + 0.6 * step)  # 9 degrees an hour
            await cycle(hass, loaded_entry)
        water(hass, 55.5)
        freezer.move_to("2026-12-15 18:38:00+00:00")
        await cycle(hass, loaded_entry)
        await cycle(hass, loaded_entry)
        learned = loaded_entry.runtime_data._acc.immersion_heating_rates
        assert len(learned) == 1
        assert learned[0] == pytest.approx(9.0, rel=0.35)


def _config_without_immersion() -> dict:
    data = {**full_config_data(), CONF_IMMERSION_MIN_TEMP: 45}
    data.pop(CONF_IMMERSION_SWITCH)
    data.pop(CONF_IMMERSION_TEMP_SENSOR)
    return data


class TestDevicesAddedLater:
    @pytest.fixture
    def config_entry(self):
        return MockConfigEntry(
            domain=DOMAIN,
            title="GivEnergy Inverter Manager",
            data=_config_without_immersion(),
            unique_id=SERIAL,
            version=1,
        )

    async def test_nothing_is_created_or_evaluated_without_an_immersion_switch(
        self, hass, loaded_entry, freezer
    ):
        assert schedule_switch(hass, loaded_entry) is None
        at(freezer, "02:05:00")
        await cycle(hass, loaded_entry)
        data = loaded_entry.runtime_data.data
        assert data.should_divert_immersion is False
        assert data.immersion_window_heating is False
        assert data.divert_reason == "No immersion switch configured"

    async def test_only_a_switch_gives_no_opt_in_because_the_water_cannot_be_read(
        self, hass, loaded_entry
    ):
        await save_options(hass, loaded_entry, immersion={CONF_IMMERSION_SWITCH: IMMERSION_SWITCH})
        assert schedule_switch(hass, loaded_entry) is None

    async def test_a_switch_and_sensor_added_later_are_scheduled(self, hass, loaded_entry, freezer):
        await save_options(
            hass,
            loaded_entry,
            immersion={
                CONF_IMMERSION_SWITCH: IMMERSION_SWITCH,
                CONF_IMMERSION_TEMP_SENSOR: IMMERSION_TEMP,
            },
        )
        switch = schedule_switch(hass, loaded_entry)
        assert switch is not None
        assert switch.is_on is False
        real_switch = RealSwitch(hass)
        water(hass, 54.0)
        await switch.async_turn_on()
        await hass.async_block_till_done()
        water(hass, COLD)
        at(freezer, "02:00:30")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]


class TestReadyTimesInTheOptions:
    @pytest.fixture
    def config_entry(self):
        return _entry()

    async def test_saved_times_are_sorted_and_kept_as_hh_mm(self, hass, loaded_entry):
        await save_options(hass, loaded_entry, ready=["19:00", "7:00", "19:00:00"])
        assert loaded_entry.options[CONF_IMMERSION_READY_TIMES] == ["07:00", "19:00"]

    async def test_clearing_the_field_clears_the_times(self, hass, loaded_entry):
        await save_options(hass, loaded_entry, ready=["07:00"])
        await save_options(hass, loaded_entry, ready=[])
        assert loaded_entry.options[CONF_IMMERSION_READY_TIMES] == []

    async def test_a_time_that_is_not_a_time_is_refused(self, hass, loaded_entry):
        result = await save_options(hass, loaded_entry, ready=["07:00", "breakfast"], expect="form")
        assert result["errors"] == {"base": "immersion_ready_time_invalid"}
        assert CONF_IMMERSION_READY_TIMES not in loaded_entry.options


class TestParityWithTheOldAutomations:
    """What the three home automations did, now done here with scheduled heating left off."""

    async def _commanded_once(self, hass, entry, freezer) -> None:
        """Let the integration switch the heater on and off once, so it can tell outside toggles."""
        water(hass, 44.0)  # below the minimum of 45
        at(freezer, "10:00:00")
        await cycle(hass, entry)
        water(hass, TARGET_REACHED)
        at(freezer, "10:30:00")
        await cycle(hass, entry)

    @pytest.mark.parametrize("utc", ["06:00:00", "12:00:00", "23:45:00", "03:00:00"])
    async def test_below_the_minimum_the_heater_comes_on_at_any_hour(
        self, hass, loaded_entry, real_switch, freezer, utc
    ):
        water(hass, 44.0)
        at(freezer, utc)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on"]
        assert "below minimum safe temperature" in loaded_entry.runtime_data.data.divert_reason

    async def test_a_timer_run_below_target_heats_to_target_then_stops(
        self, hass, loaded_entry, real_switch, freezer
    ):
        await self._commanded_once(hass, loaded_entry, freezer)
        assert real_switch.calls == ["turn_on", "turn_off"]
        water(hass, 52.0)
        hass.states.async_set(IMMERSION_SWITCH, "on")  # a timer of the device starts it
        at(freezer, "22:00:00")
        await cycle(hass, loaded_entry)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on", "turn_off"]  # left running to the target
        water(hass, TARGET_REACHED)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on", "turn_off", "turn_off"]

    async def test_a_timer_start_with_the_water_at_target_is_switched_off(
        self, hass, loaded_entry, real_switch, freezer
    ):
        await self._commanded_once(hass, loaded_entry, freezer)
        hass.states.async_set(IMMERSION_SWITCH, "on")
        at(freezer, "22:00:00")
        await cycle(hass, loaded_entry)
        await cycle(hass, loaded_entry)
        assert real_switch.calls[-1] == "turn_off"
        assert real_switch.calls.count("turn_off") == 2

    async def test_the_device_auto_off_after_an_hour_ends_a_timer_run_without_a_fight(
        self, hass, loaded_entry, real_switch, freezer
    ):
        """Inching switches the heater off at 60 minutes. That is read as an outside turn-off."""
        await self._commanded_once(hass, loaded_entry, freezer)
        water(hass, 52.0)
        hass.states.async_set(IMMERSION_SWITCH, "on")
        at(freezer, "22:00:00")
        await cycle(hass, loaded_entry)
        await cycle(hass, loaded_entry)
        water(hass, 53.5)
        hass.states.async_set(IMMERSION_SWITCH, "off")
        at(freezer, "23:00:00")
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_on", "turn_off"]
        assert loaded_entry.runtime_data.override_immersion is None

    @pytest.mark.parametrize("utc", ["00:30:00", "03:00:00", "05:00:00", "12:00:00", "23:45:00"])
    async def test_a_heater_above_target_is_never_left_on_at_any_hour(
        self, hass, loaded_entry, real_switch, freezer, utc
    ):
        hass.states.async_set(IMMERSION_SWITCH, "on")
        water(hass, TARGET_REACHED)
        at(freezer, utc)
        await cycle(hass, loaded_entry)
        assert real_switch.calls == ["turn_off"]
