"""A counter that steps by more than the system could deliver is not energy."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.core import engine
from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
from custom_components.givenergy_inverter_manager.core.engine import (
    Accumulators,
    CycleInputs,
    ForecastContext,
    PreviousCycle,
)
from custom_components.givenergy_inverter_manager.core.tariff import (
    CounterMemory,
    EnergyAccumulator,
)
from custom_components.givenergy_inverter_manager.lib.guards.counter import (
    FIRST,
    JUMP,
    NEGATIVE,
    OK,
    RESET,
    TOO_LARGE,
    UNIT_CHANGE,
    allowed_rise_kwh,
    judge,
    largest_day_kwh,
    screen,
)
from tests.conftest import _nightboost_cfg, _raw

POWER_W = 5000.0
START = datetime(2031, 3, 4, 7, 0, tzinfo=timezone.utc)
STEP_S = 30.0


class TestJudge:
    def test_the_first_reading_is_trusted_and_all_of_it_is_new(self):
        verdict = judge(None, 7.5, None, POWER_W)

        assert (verdict.kind, verdict.trusted, verdict.rise_kwh) == (FIRST, True, 7.5)

    def test_a_normal_rise_in_one_cycle_is_energy(self):
        verdict = judge(10.0, 10.02, STEP_S, POWER_W)

        assert (verdict.kind, verdict.trusted) == (OK, True)
        assert verdict.rise_kwh == pytest.approx(0.02)

    def test_a_rise_the_system_could_not_deliver_in_the_time_is_not_energy(self):
        verdict = judge(10.0, 18.0, STEP_S, POWER_W)  # 8 kWh in 30 seconds on 5 kW

        assert (verdict.kind, verdict.trusted, verdict.rise_kwh) == (JUMP, False, 0.0)

    def test_the_same_rise_after_hours_is_energy(self):
        verdict = judge(10.0, 18.0, 4 * 3600, POWER_W)  # 8 kWh in 4 hours on 5 kW

        assert (verdict.kind, verdict.trusted) == (OK, True)

    def test_a_step_of_about_a_thousand_times_is_a_probable_unit_change(self):
        verdict = judge(12.0, 12000.0, STEP_S, POWER_W)

        assert (verdict.kind, verdict.trusted, verdict.rise_kwh) == (UNIT_CHANGE, False, 0.0)

    def test_a_unit_step_is_caught_even_when_the_time_is_not_known(self):
        verdict = judge(12.0, 12000.0, None, POWER_W)

        assert verdict.kind == UNIT_CHANGE and not verdict.trusted

    def test_a_small_old_value_is_not_called_a_unit_change(self):
        """0.01 kWh just after midnight, then 6 kWh after a long gap, is a day of solar."""
        verdict = judge(0.01, 6.0, 3 * 3600, POWER_W)

        assert (verdict.kind, verdict.trusted) == (OK, True)

    def test_a_fall_is_the_daily_reset_and_the_new_value_is_all_new(self):
        verdict = judge(21.0, 0.2, STEP_S, POWER_W)

        assert (verdict.kind, verdict.trusted, verdict.rise_kwh) == (RESET, True, 0.2)

    def test_a_reset_that_reads_too_much_for_the_time_is_not_trusted(self):
        verdict = judge(21.0, 9.0, STEP_S, POWER_W)

        assert not verdict.trusted

    def test_a_negative_reading_is_never_trusted(self):
        assert judge(5.0, -1.0, STEP_S, POWER_W).kind == NEGATIVE

    def test_more_than_a_day_could_hold_is_never_trusted(self):
        too_much = largest_day_kwh(POWER_W) + 1

        assert judge(None, too_much, None, POWER_W).kind == TOO_LARGE
        assert not judge(None, too_much, None, POWER_W).trusted

    def test_the_allowance_grows_with_power_and_time_and_has_a_floor(self):
        assert allowed_rise_kwh(5000, 0) > 0
        assert allowed_rise_kwh(10000, 3600) > allowed_rise_kwh(5000, 3600)
        assert allowed_rise_kwh(5000, 7200) > allowed_rise_kwh(5000, 3600)


def _raw_with(**counters):
    raw = _raw()
    raw.inverter_max_w = POWER_W
    for name, value in counters.items():
        setattr(raw, name, value)
    return raw


class TestScreen:
    def test_trusted_readings_pass_through_unchanged(self):
        memory = CounterMemory()
        raw = _raw_with(import_energy_today_kwh=3.1, solar_energy_today_kwh=12.4)

        assert screen(memory, raw, START) is raw

    def test_a_counter_that_jumped_is_left_out_and_the_others_are_kept(self):
        memory = CounterMemory()
        screen(memory, _raw_with(import_energy_today_kwh=3.1, export_energy_today_kwh=4.0), START)
        later = START + timedelta(seconds=STEP_S)

        screened = screen(
            memory,
            _raw_with(import_energy_today_kwh=3100.0, export_energy_today_kwh=4.01),
            later,
        )

        assert screened.import_energy_today_kwh is None
        assert screened.export_energy_today_kwh == 4.01

    def test_the_input_is_not_changed(self):
        memory = CounterMemory()
        screen(memory, _raw_with(import_energy_today_kwh=3.1), START)
        raw = _raw_with(import_energy_today_kwh=3100.0)

        screen(memory, raw, START + timedelta(seconds=STEP_S))

        assert raw.import_energy_today_kwh == 3100.0

    def test_it_is_logged_once_as_a_probable_unit_change(self, caplog):
        memory = CounterMemory()
        screen(memory, _raw_with(import_energy_today_kwh=3.1), START)

        with caplog.at_level(logging.WARNING):
            for n in (1, 2, 3):
                screen(
                    memory,
                    _raw_with(import_energy_today_kwh=3100.0 + n),
                    START + timedelta(seconds=STEP_S * n),
                )

        lines = [r.getMessage() for r in caplog.records if "energy counter" in r.getMessage()]
        assert len(lines) == 1
        assert "probable unit change" in lines[0]

    def test_it_stays_left_out_until_the_counter_falls(self):
        memory = CounterMemory()
        screen(memory, _raw_with(import_energy_today_kwh=3.1), START)
        at = START + timedelta(seconds=STEP_S)
        assert screen(memory, _raw_with(import_energy_today_kwh=3100.0), at).import_energy_today_kwh is None

        at += timedelta(seconds=STEP_S)
        assert screen(memory, _raw_with(import_energy_today_kwh=3100.01), at).import_energy_today_kwh is None

        at += timedelta(seconds=STEP_S)
        back = screen(memory, _raw_with(import_energy_today_kwh=0.02), at)
        assert back.import_energy_today_kwh == 0.02

    def test_a_restart_keeps_only_the_saved_ac_charge_baseline(self):
        memory = CounterMemory(ac_charge_kwh=7.5)  # what the store gives back
        raw = _raw_with(ac_charge_energy_today_kwh=8.0)

        screen(memory, raw, START)

        assert memory.ac_charge_rise_kwh == pytest.approx(0.5)

    def test_a_unit_step_in_the_ac_charge_counter_is_caught_after_a_restart(self):
        memory = CounterMemory(ac_charge_kwh=7.5)

        screened = screen(memory, _raw_with(ac_charge_energy_today_kwh=7500.0), START)

        assert screened.ac_charge_energy_today_kwh is None
        assert memory.ac_charge_rise_kwh == 0.0
        assert memory.ac_charge_kwh == 7500.0  # the baseline moves to what it reads now


def _cycle(raw, accumulators: Accumulators, at: datetime) -> engine.CoordinatorData:
    data, _ = engine.build_coordinator_data(
        CycleInputs(raw=raw, cfg=_nightboost_cfg(), now=at),
        accumulators,
        PreviousCycle(BatteryStats(), None, None),
        ForecastContext(),
    )
    return data


def _accumulators() -> Accumulators:
    return Accumulators(
        today=EnergyAccumulator(),
        week=EnergyAccumulator(),
        month=EnergyAccumulator(),
        year=EnergyAccumulator(),
        counters=CounterMemory(),
    )


class TestThroughTheEngine:
    def test_a_counter_that_steps_a_thousand_times_books_nothing_and_resets_the_baseline(self):
        accumulators = _accumulators()
        _cycle(_raw_with(ac_charge_energy_today_kwh=7.5, import_energy_today_kwh=12.0), accumulators, START)
        week_before = accumulators.week.grid_to_battery_kwh
        today_before = accumulators.today.import_kwh

        _cycle(
            _raw_with(ac_charge_energy_today_kwh=7500.0, import_energy_today_kwh=12000.0),
            accumulators,
            START + timedelta(seconds=STEP_S),
        )

        assert accumulators.week.grid_to_battery_kwh == week_before
        assert accumulators.month.grid_to_battery_kwh == week_before
        assert accumulators.year.grid_to_battery_kwh == week_before
        assert accumulators.today.import_kwh == today_before  # today keeps what it had
        assert accumulators.today.grid_to_battery_kwh == 7.5  # and so does the stored charge
        assert accumulators.counters.ac_charge_kwh == 7500.0

    def test_after_a_step_nothing_is_booked_until_the_counter_falls(self):
        accumulators = _accumulators()
        at = START
        _cycle(_raw_with(ac_charge_energy_today_kwh=7.5), accumulators, at)
        at += timedelta(seconds=STEP_S)
        _cycle(_raw_with(ac_charge_energy_today_kwh=7500.0), accumulators, at)
        at += timedelta(seconds=STEP_S)
        _cycle(_raw_with(ac_charge_energy_today_kwh=7500.01), accumulators, at)
        assert accumulators.week.grid_to_battery_kwh == pytest.approx(7.5)
        assert accumulators.counters.ac_charge_kwh == pytest.approx(7500.01)  # the new baseline

        at += timedelta(seconds=STEP_S)
        _cycle(_raw_with(ac_charge_energy_today_kwh=0.0), accumulators, at)  # the daily reset
        at += timedelta(seconds=STEP_S)
        _cycle(_raw_with(ac_charge_energy_today_kwh=0.2), accumulators, at)

        assert accumulators.week.grid_to_battery_kwh == pytest.approx(7.7)

    def test_a_spike_that_falls_back_books_only_what_it_added(self):
        accumulators = _accumulators()
        at = START
        _cycle(_raw_with(ac_charge_energy_today_kwh=7.5, import_energy_today_kwh=12.0), accumulators, at)
        at += timedelta(seconds=STEP_S)
        _cycle(_raw_with(ac_charge_energy_today_kwh=30.0, import_energy_today_kwh=12.0), accumulators, at)
        assert accumulators.week.grid_to_battery_kwh == pytest.approx(7.5)

        at += timedelta(seconds=STEP_S)
        _cycle(_raw_with(ac_charge_energy_today_kwh=7.52, import_energy_today_kwh=12.03), accumulators, at)

        assert accumulators.week.grid_to_battery_kwh == pytest.approx(7.52)
        assert accumulators.today.import_kwh == pytest.approx(12.03)  # trusted again

    def test_an_unchanged_system_books_its_energy_as_before(self):
        accumulators = _accumulators()
        _cycle(_raw_with(ac_charge_energy_today_kwh=7.5, import_energy_today_kwh=12.0), accumulators, START)

        _cycle(
            _raw_with(ac_charge_energy_today_kwh=7.52, import_energy_today_kwh=12.03),
            accumulators,
            START + timedelta(seconds=STEP_S),
        )

        assert accumulators.today.import_kwh == pytest.approx(12.03)
        assert accumulators.week.grid_to_battery_kwh == pytest.approx(7.52)
