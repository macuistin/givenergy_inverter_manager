"""Tonight's charge plan with a battery pause: the forward simulation and the skip check.

In a paused slot the grid serves the house, so a shortfall of solar there does not run the battery
down. A surplus still charges it. The plan therefore asks for less charge, and it can skip a night
that the battery lasts only because of the pause. A plan with no pause is the one it always was.
"""

from __future__ import annotations

from datetime import datetime, time, timezone

import pytest

from custom_components.givenergy_inverter_manager.core import rules
from custom_components.givenergy_inverter_manager.core.battery_pause import PauseWindow
from custom_components.givenergy_inverter_manager.core.rules import (
    ChargeInputs,
    SolarForecast,
    calculate_overnight_charge_target,
)

NIGHT = PauseWindow(time(23, 0), time(8, 0))
NOTE = "The battery is paused from 23:00 to 08:00."
JUNE_EVENING = datetime(2031, 6, 15, 22, 0, tzinfo=timezone.utc)
JUNE_EVENING_20 = datetime(2031, 6, 15, 20, 0, tzinfo=timezone.utc)


def _day(pause: PauseWindow | None, *, solar_weights=None, load_kwh=0.2, forecast_kwh=0.0):
    fields = {} if solar_weights is None else {"solar_weights": solar_weights}
    return rules._SimulatedDay(forecast_kwh, 10.0, [load_kwh] * 48, pause=pause, **fields)


class TestTheSlotsOfTheSimulation:
    def test_without_a_pause_every_slot_runs_the_battery_down(self):
        # 0.2 kWh a slot on a 10 kWh battery is 2 points, 96 over the day.
        assert rules._simulate_min_soc(100.0, _day(None)) == pytest.approx(4.0)

    def test_the_paused_slots_do_not(self):
        # 23:00 to 08:00 is 18 of the 48 slots, so 30 slots run the battery down.
        assert rules._simulate_min_soc(100.0, _day(NIGHT)) == pytest.approx(40.0)

    def test_a_pause_that_is_off_the_clock_changes_nothing(self):
        nothing = PauseWindow(time(5, 0), time(5, 0))

        assert rules._simulate_min_soc(100.0, _day(nothing)) == rules._simulate_min_soc(
            100.0, _day(None)
        )

    def test_a_slot_that_is_half_paused_runs_the_battery_down_by_half(self):
        half = PauseWindow(time(23, 15), time(8, 0))
        day = _day(half)

        assert rules._slot_net_pct(day, 46, 0.0, 0.2) == pytest.approx(-1.0)
        assert rules._slot_net_pct(day, 45, 0.0, 0.2) == pytest.approx(-2.0)
        assert rules._slot_net_pct(day, 47, 0.0, 0.2) == 0.0

    def test_a_surplus_of_solar_charges_the_battery_paused_or_not(self):
        weights = tuple(1.0 if slot == 10 else 0.0 for slot in range(48))
        paused = _day(PauseWindow(time(5, 0), time(6, 0)), solar_weights=weights, forecast_kwh=10.0)
        free = _day(None, solar_weights=weights, forecast_kwh=10.0)

        # Slot 10 is 05:00 to 05:30. Solar of 10 kWh less 0.2 kWh of load charges 98 points.
        assert rules._slot_net_pct(paused, 10, 1.0, 0.2) == pytest.approx(98.0)
        assert rules._slot_net_pct(free, 10, 1.0, 0.2) == pytest.approx(98.0)

    def test_a_shortfall_of_solar_is_met_by_the_grid_while_paused(self):
        weights = tuple(0.5 if slot == 10 else 0.0 for slot in range(48))
        paused = _day(PauseWindow(time(5, 0), time(6, 0)), solar_weights=weights, forecast_kwh=0.2)

        # 0.1 kWh of solar against 0.2 kWh of load: 1 point short without the pause, none with.
        assert rules._slot_net_pct(paused, 10, 0.5, 0.2) == pytest.approx(0.0)
        assert rules._slot_net_pct(_day(None, solar_weights=weights, forecast_kwh=0.2), 10, 0.5, 0.2) == (
            pytest.approx(-1.0)
        )


def _inputs(**changes) -> ChargeInputs:
    base = {
        "current_soc": 30.0,
        "battery_capacity_kwh": 10.0,
        "min_soc": 10,
        "skip_charge_threshold": 101,
        "car_plugged_in": False,
        "inverter_max_kw": 5.0,
        "average_daily_consumption_kwh": 9.6,
        "cheapest_rate": 0.1,
    }
    return ChargeInputs(**{**base, **changes})


def _decide(inputs: ChargeInputs, forecast_kwh: float = 0.0, dt: datetime = JUNE_EVENING):
    return calculate_overnight_charge_target(inputs, SolarForecast(forecast_kwh=forecast_kwh), dt)


class TestTheTarget:
    def test_without_a_pause_a_dark_day_needs_a_full_battery(self):
        decision = _decide(_inputs())

        assert decision.target_soc == 100
        assert "paused" not in decision.reason

    def test_a_pause_over_the_night_needs_only_the_load_of_the_unpaused_slots(self):
        # No solar. 30 slots at 2 points need 60 points above the 10% minimum.
        decision = _decide(_inputs(battery_pause=NIGHT))

        assert decision.target_soc == 70

    def test_the_reason_says_the_battery_is_paused_once(self):
        decision = _decide(_inputs(battery_pause=NIGHT))

        assert decision.reason.endswith(NOTE)
        assert decision.reason.count("paused") == 1

    def test_a_shorter_pause_spares_only_its_own_slots(self):
        small_hours = PauseWindow(time(0, 0), time(4, 0))  # 8 of the 48 slots

        assert _decide(_inputs(battery_pause=small_hours)).target_soc == 10 + 40 * 2

    def test_a_pause_with_solar_only_spares_the_load_solar_does_not_cover(self):
        free = _decide(_inputs(average_daily_consumption_kwh=6.0), forecast_kwh=3.0)
        paused = _decide(
            _inputs(average_daily_consumption_kwh=6.0, battery_pause=NIGHT), forecast_kwh=3.0
        )

        assert paused.target_soc < free.target_soc

    def test_a_winter_month_still_charges_to_full(self):
        winter = datetime(2031, 12, 15, 22, 0, tzinfo=timezone.utc)

        decision = _decide(_inputs(battery_pause=NIGHT), dt=winter)

        assert decision.target_soc == 100
        assert "paused" not in decision.reason


def _skip_inputs(**changes) -> ChargeInputs:
    base = {
        "current_soc": 80.0,
        "skip_charge_threshold": 75,
        "average_daily_consumption_kwh": 20.0,
    }
    return _inputs(**{**base, **changes})


class TestTheSkipCheck:
    def test_without_a_pause_a_battery_that_will_not_last_the_night_is_not_skipped(self):
        # 12 hours to sunrise at 0.83 kWh is 10 kWh against the 7 kWh above the minimum.
        decision = _decide(_skip_inputs(), forecast_kwh=30.0, dt=JUNE_EVENING_20)

        assert decision.skip_charge is False
        assert "Not skipping: Battery may run low" in decision.reason

    def test_with_a_pause_it_lasts_and_the_charge_is_skipped(self):
        # Only 20:00 to 23:00 runs the battery down: 2.5 kWh.
        decision = _decide(_skip_inputs(battery_pause=NIGHT), forecast_kwh=30.0, dt=JUNE_EVENING_20)

        assert decision.skip_charge is True
        assert decision.reason.endswith(NOTE)
        assert decision.reason.count("paused") == 1

    def test_a_skip_that_the_pause_does_not_decide_does_not_name_it(self):
        daytime = PauseWindow(time(12, 0), time(14, 0))
        decision = _decide(
            _skip_inputs(average_daily_consumption_kwh=6.0, battery_pause=daytime),
            forecast_kwh=30.0,
            dt=JUNE_EVENING_20,
        )

        assert decision.skip_charge is True
        assert "paused" not in decision.reason

    def test_a_blocked_skip_names_the_pause_once(self):
        # 66 points above the minimum is 6.6 kWh. Three unpaused hours at 2.5 kWh an hour need
        # 7.5 kWh, so the pause does not save the night and the plan still charges.
        decision = _decide(
            _skip_inputs(current_soc=76.0, average_daily_consumption_kwh=60.0, battery_pause=NIGHT),
            forecast_kwh=30.0,
            dt=JUNE_EVENING_20,
        )

        assert decision.skip_charge is False
        assert "Not skipping: Battery may run low" in decision.reason
        assert decision.reason.count(NOTE) == 1
