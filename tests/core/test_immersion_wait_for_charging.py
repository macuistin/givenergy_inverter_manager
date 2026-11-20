"""Scheduled immersion heating waits while the car and the house battery charge from the grid.

The three loads together pulled the supply down at 02:00 and the car stopped charging. Solar
surplus and the legionella minimum are not held back.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time

import pytest

from custom_components.givenergy_inverter_manager.core.rules import (
    WAIT_FOR_CHARGING_REASON,
    CheapWindow,
    ImmersionInputs,
    ImmersionRun,
    PowerReadings,
    ReadyPlan,
    WaterState,
    should_divert_to_immersion,
)
from tests.conftest import _raw, _run

CAR_W = 6700.0
BATTERY_W = 3300.0


def run_at(hour: int, minute: int = 0, **raw):
    fields = {
        "solar_power_w": 0.0,
        "battery_soc": 15.0,
        "house_load_w": 1800.0,
        "battery_power_w": 0.0,
        "grid_power_w": 1800.0,
        "immersion_temp": 40.0,
        "immersion_min_temp": 30.0,
        "immersion_heating_rate_c_per_h": 10.0,
        "immersion_rate_source": "learned",
        "immersion_schedule_enabled": True,
    }
    fields.update(raw)
    return _run(raw=_raw(**fields), now=datetime(2026, 12, 15, hour, minute))[0]


CAR_AND_BATTERY = {
    "ev_power_w": CAR_W,
    "ev_plugged_in": True,
    "battery_power_w": BATTERY_W,
    "grid_power_w": CAR_W + BATTERY_W + 1800.0,
}


class TestThroughTheEngine:
    def test_the_cheapest_window_heats_when_nothing_else_is_charging(self):
        data = run_at(2, 30)
        assert data.should_divert_immersion is True
        assert "Cheapest rate window" in data.divert_reason

    def test_it_waits_while_the_car_and_the_battery_both_charge_from_the_grid(self):
        data = run_at(2, 30, **CAR_AND_BATTERY)
        assert data.should_divert_immersion is False
        assert data.divert_reason == WAIT_FOR_CHARGING_REASON

    def test_it_heats_once_the_car_has_stopped(self):
        data = run_at(2, 30, **{**CAR_AND_BATTERY, "ev_power_w": 0.0})
        assert data.should_divert_immersion is True

    def test_it_heats_once_the_battery_has_stopped(self):
        data = run_at(2, 30, **{**CAR_AND_BATTERY, "battery_power_w": 0.0, "battery_soc": 100.0})
        assert data.should_divert_immersion is True

    def test_a_car_charging_on_solar_alone_does_not_make_it_wait(self):
        """The battery is not charging from the grid, and no grid charge is planned at noon."""
        data = run_at(
            12, 0, **{**CAR_AND_BATTERY, "battery_power_w": 0.0, "battery_soc": 100.0}
        )
        assert data.divert_reason != WAIT_FOR_CHARGING_REASON

    def test_it_waits_just_before_the_battery_charge_starts(self):
        """01:58 is inside the three minutes before the 02:00 charge window opens."""
        cold = {"immersion_temp": 30.0, "immersion_ready_times": (time(4, 0),)}
        without_car = run_at(1, 58, **cold)
        assert without_car.should_divert_immersion is True, without_car.divert_reason
        with_car = run_at(
            1, 58, **cold, ev_power_w=CAR_W, ev_plugged_in=True, grid_power_w=CAR_W + 1800.0
        )
        assert with_car.should_divert_immersion is False
        assert with_car.divert_reason == WAIT_FOR_CHARGING_REASON

    def test_a_planned_skip_does_not_make_it_wait(self):
        data = run_at(2, 30, **{**CAR_AND_BATTERY, "battery_power_w": 0.0, "battery_soc": 95.0})
        assert data.should_divert_immersion is True

    def test_the_legionella_minimum_still_heats_while_both_charge(self):
        data = run_at(2, 30, immersion_temp=25.0, **CAR_AND_BATTERY)
        assert data.should_divert_immersion is True
        assert "minimum" in data.divert_reason.lower()

    def test_solar_surplus_still_diverts_while_both_charge(self):
        data = run_at(
            12,
            0,
            immersion_temp=40.0,
            solar_power_w=6000.0,
            battery_soc=90.0,
            house_load_w=1000.0,
            ev_power_w=CAR_W,
            battery_power_w=BATTERY_W,
            grid_power_w=300.0,
        )
        assert data.should_divert_immersion is True
        assert "diverting to immersion" in data.divert_reason


def _inputs(*, waiting: bool, on: bool = False, temp: float = 40.0) -> ImmersionInputs:
    return ImmersionInputs(
        power=PowerReadings(
            solar_power_w=0.0,
            house_load_w=1800.0,
            battery_power_w=0.0,
            battery_soc=20.0,
            inverter_max_w=5000.0,
            immersion_power_w=3000.0,
        ),
        water=WaterState(temp=temp, target_temp=55.0, min_temp=30.0, hysteresis_c=5.0),
        run=ImmersionRun(currently_on=on, grid_loads_charging=waiting),
        window=CheapWindow(enabled=True, open_label="Night Boost 02:00 to 04:00"),
        ready=ReadyPlan(),
    )


class TestTheRule:
    def test_off_without_the_flag_the_window_heats(self):
        assert should_divert_to_immersion(_inputs(waiting=False))[0] is True

    def test_with_the_flag_the_window_waits(self):
        assert should_divert_to_immersion(_inputs(waiting=True)) == (False, WAIT_FOR_CHARGING_REASON)

    def test_a_running_heater_is_turned_off_for_the_wait_and_back_on_after(self):
        running = should_divert_to_immersion(_inputs(waiting=True, on=True))
        assert running == (False, WAIT_FOR_CHARGING_REASON)
        assert should_divert_to_immersion(_inputs(waiting=False, on=True))[0] is True

    def test_a_tank_at_target_gives_the_normal_reason_not_the_wait(self):
        verdict = should_divert_to_immersion(_inputs(waiting=True, temp=55.0))
        assert verdict[0] is False
        assert verdict[1] != WAIT_FOR_CHARGING_REASON

    def test_a_heater_that_nothing_schedules_gives_the_normal_reason(self):
        inputs = replace(_inputs(waiting=True), window=CheapWindow())
        assert should_divert_to_immersion(inputs)[1] != WAIT_FOR_CHARGING_REASON


@pytest.mark.parametrize("waiting", [True, False])
def test_the_wait_never_turns_a_heating_verdict_into_a_start_when_unscheduled(waiting):
    inputs = replace(_inputs(waiting=waiting), window=CheapWindow())
    assert should_divert_to_immersion(inputs)[0] is False
