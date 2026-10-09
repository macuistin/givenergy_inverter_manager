"""Scheduled immersion heating through the engine: the cheapest window plus ready-by times.

Also pins the parity with the three home automations this replaces: heat below the minimum at
any hour, stop at the target whatever started the heater, and never leave it on above target.
"""

from __future__ import annotations

from datetime import datetime, time

import pytest

from tests.conftest import _raw, _run

RATE = 10.0  # degrees per hour
MORNING, EVENING = time(7, 0), time(19, 0)


def run_at(hour: int, minute: int = 0, **raw):
    fields = {
        "solar_power_w": 0.0,
        "battery_soc": 20.0,
        "house_load_w": 400.0,
        "battery_power_w": 0.0,
        "immersion_temp": 40.0,
        "immersion_min_temp": 30.0,
        "immersion_heating_rate_c_per_h": RATE,
        "immersion_rate_source": "learned",
    }
    fields.update(raw)
    return _run(raw=_raw(**fields), now=datetime(2026, 12, 15, hour, minute))[0]


class TestReadyTimes:
    def test_a_cold_tank_at_17_00_is_topped_up_for_19_00(self):
        data = run_at(
            17,
            immersion_temp=30.0,
            immersion_schedule_enabled=True,
            immersion_ready_times=(EVENING,),
        )
        assert data.should_divert_immersion is True
        assert "ready by 19:00" in data.divert_reason
        assert data.immersion_ready_time == EVENING
        assert data.immersion_expected_ready is False

    def test_the_top_up_waits_while_there_is_time(self):
        data = run_at(
            15,
            immersion_temp=45.0,
            immersion_schedule_enabled=True,
            immersion_ready_times=(EVENING,),
        )
        assert data.should_divert_immersion is False
        assert data.immersion_expected_ready is True

    def test_solar_already_heating_means_no_grid_top_up_is_named(self):
        data = run_at(
            12,
            solar_power_w=4500.0,
            battery_soc=90.0,
            immersion_temp=45.0,
            immersion_schedule_enabled=True,
            immersion_ready_times=(EVENING,),
        )
        assert data.should_divert_immersion is True
        assert "Solar surplus" in data.divert_reason

    def test_a_warm_tank_is_left_alone_and_reported_ready(self):
        data = run_at(
            18,
            immersion_temp=55.0,
            immersion_schedule_enabled=True,
            immersion_ready_times=(EVENING,),
        )
        assert data.should_divert_immersion is False
        assert data.immersion_expected_ready is True

    def test_no_ready_times_changes_nothing(self):
        data = run_at(17, immersion_temp=45.0, immersion_schedule_enabled=True)
        assert data.should_divert_immersion is False
        assert data.immersion_ready_time is None
        assert data.immersion_expected_ready is None

    def test_ready_times_do_nothing_until_scheduled_heating_is_on(self):
        data = run_at(18, immersion_temp=40.0, immersion_ready_times=(EVENING,))
        assert data.should_divert_immersion is False
        assert data.immersion_ready_time is None

    def test_without_a_temperature_sensor_ready_times_are_ignored(self):
        data = run_at(
            18,
            immersion_temp=None,
            immersion_schedule_enabled=True,
            immersion_ready_times=(EVENING,),
        )
        assert data.should_divert_immersion is False
        assert data.immersion_ready_time is None

    def test_without_an_immersion_switch_nothing_is_planned(self):
        data = run_at(
            18,
            immersion_switch_configured=False,
            immersion_schedule_enabled=True,
            immersion_ready_times=(EVENING,),
        )
        assert data.should_divert_immersion is False

    def test_the_snapshot_carries_the_rate_and_where_it_came_from(self):
        data = run_at(
            12,
            immersion_schedule_enabled=True,
            immersion_ready_times=(EVENING,),
        )
        assert data.immersion_heating_rate_c_per_h == RATE
        assert data.immersion_rate_source == "learned"


class TestMorningReadyTime:
    def test_the_cheap_window_meets_the_morning_ready_time(self):
        data = run_at(
            2,
            immersion_schedule_enabled=True,
            immersion_ready_times=(MORNING, EVENING),
        )
        assert data.should_divert_immersion is True
        assert data.immersion_window_heating is True
        assert data.immersion_ready_time == MORNING

    def test_the_night_band_after_the_window_tops_up_what_the_window_missed(self):
        data = run_at(
            5,
            45,
            immersion_temp=44.0,
            immersion_schedule_enabled=True,
            immersion_ready_times=(MORNING,),
        )
        assert data.should_divert_immersion is True
        assert "ready by 07:00" in data.divert_reason


class TestParityWithTheOldAutomations:
    """Heat below the minimum at any hour. Stop at the target. Never left on above it."""

    @pytest.mark.parametrize("hour", range(24))
    def test_below_the_minimum_the_heater_runs_at_every_hour(self, hour):
        data = run_at(hour, immersion_temp=44.0, immersion_min_temp=45.0)
        assert data.should_divert_immersion is True
        assert "below minimum safe temperature" in data.divert_reason

    @pytest.mark.parametrize("hour", range(24))
    def test_at_the_target_a_running_heater_is_told_to_stop_at_every_hour(self, hour):
        data = run_at(
            hour,
            immersion_temp=55.0,
            immersion_on=True,
            immersion_schedule_enabled=True,
            immersion_ready_times=(MORNING, EVENING),
        )
        assert data.should_divert_immersion is False

    @pytest.mark.parametrize("hour", [2, 3, 12, 18, 23])
    def test_above_the_target_with_plenty_of_solar_it_still_stops(self, hour):
        data = run_at(
            hour,
            solar_power_w=4500.0,
            battery_soc=95.0,
            immersion_temp=57.0,
            immersion_on=True,
        )
        assert data.should_divert_immersion is False
