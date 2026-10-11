"""The saving counts the energy the battery holds, so a cheap overnight charge is not a loss.

Energy bought to fill the battery is paid for on the day it is bought and only repaid on the
day it is used. The saving adds the change in stored energy since midnight, valued at the
average cost of the grid energy stored today, or at the cheapest rate when none was.
"""

from datetime import datetime

import pytest

from custom_components.givenergy_inverter_manager.accumulation import (
    _acc_to_dict,
    _deserialize,
    _serialize,
)
from custom_components.givenergy_inverter_manager.core import engine
from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
from custom_components.givenergy_inverter_manager.core.engine import (
    Accumulators,
    CycleInputs,
    ForecastContext,
    PreviousCycle,
)
from custom_components.givenergy_inverter_manager.core.solar_day import HeldSolarDay
from custom_components.givenergy_inverter_manager.core.tariff import (
    CounterMemory,
    EnergyAccumulator,
    build_tariff,
)
from tests.conftest import _nightboost_cfg, _raw

CAPACITY_KWH = 19.0
KEEP = (1 - 0.055) * (1 + 0.09)  # discount, then VAT, as in _nightboost_cfg
NIGHTBOOST = 0.0965 * KEEP  # the cheapest rate, after discount and VAT
NIGHT = 0.1644 * KEEP
DAY = 0.3334 * KEEP
MIDNIGHT = datetime(2026, 10, 6, 0, 0, 30)
CHARGING = datetime(2026, 10, 6, 3, 0)
MORNING = datetime(2026, 10, 6, 11, 5)


def _raw_at(soc: float, *, ac_charge_kwh: float | None = None, capacity_kwh=CAPACITY_KWH):
    raw = _raw(battery_soc=soc, battery_capacity_kwh=capacity_kwh)
    raw.ac_charge_energy_today_kwh = ac_charge_kwh
    return raw


def _cycle(accumulators: Accumulators, now: datetime, raw) -> engine.CoordinatorData:
    data, _ = engine.build_coordinator_data(
        CycleInputs(raw=raw, cfg=_nightboost_cfg(), now=now),
        accumulators,
        PreviousCycle(BatteryStats(), None, None),
        ForecastContext(),
    )
    return data


def _started_cycle(raw) -> engine._Cycle:
    """The values one cycle reads, for steps that are tested without the rest of the engine."""
    return engine._start_cycle(
        CycleInputs(raw=raw, cfg=_nightboost_cfg(), now=MORNING),
        ForecastContext(),
        MORNING,
        HeldSolarDay(),
    )


def _new_day(counters: CounterMemory | None = None) -> Accumulators:
    return Accumulators(
        today=EnergyAccumulator(), counters=counters if counters is not None else CounterMemory()
    )


def _saving_before_the_stored_energy(data: engine.CoordinatorData) -> float:
    """What the saving read before the stored energy was counted."""
    acc = data.today
    return acc.grid_equivalent_load_cost - (acc.total_import_cost - acc.export_earnings)


def _morning_after_a_cheap_charge() -> engine.CoordinatorData:
    """The review's case: 47% at midnight, 12 kWh bought at the Nightboost rate, 86% at 11:05."""
    accumulators = _new_day()
    _cycle(accumulators, MIDNIGHT, _raw_at(47.0, ac_charge_kwh=0.0))
    _cycle(accumulators, CHARGING, _raw_at(70.0, ac_charge_kwh=12.0))
    accumulators.today.import_cost_by_period = {"Nightboost": 12 * NIGHTBOOST}
    accumulators.today.grid_equivalent_load_cost = 0.6
    return _cycle(accumulators, MORNING, _raw_at(86.0, ac_charge_kwh=12.0))


class TestTheReviewsMorning:
    def test_without_the_stored_energy_the_saving_is_a_loss(self):
        data = _morning_after_a_cheap_charge()
        assert _saving_before_the_stored_energy(data) < -0.5

    def test_with_the_stored_energy_the_saving_is_positive(self):
        data = _morning_after_a_cheap_charge()
        assert data.saving_vs_grid_today > 0

    def test_the_change_is_the_soc_rise_times_the_capacity(self):
        data = _morning_after_a_cheap_charge()
        assert data.stored_energy_change_kwh == pytest.approx(0.39 * CAPACITY_KWH)

    def test_it_is_valued_at_the_average_cost_of_the_grid_energy_stored(self):
        data = _morning_after_a_cheap_charge()
        assert data.stored_energy_value == pytest.approx(0.39 * CAPACITY_KWH * NIGHTBOOST)

    def test_the_saving_is_the_old_figure_plus_the_stored_energy(self):
        data = _morning_after_a_cheap_charge()
        expected = _saving_before_the_stored_energy(data) + data.stored_energy_value
        assert data.saving_vs_grid_today == pytest.approx(expected, abs=1e-4)

    def test_the_net_saving_follows_it(self):
        data = _morning_after_a_cheap_charge()
        assert data.net_saving_today == pytest.approx(data.saving_vs_grid_today)


class TestTheRate:
    def test_a_charge_split_across_two_rates_is_valued_at_its_average(self):
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, _raw_at(40.0, ac_charge_kwh=0.0))
        _cycle(accumulators, CHARGING, _raw_at(55.0, ac_charge_kwh=6.0))  # Nightboost
        _cycle(accumulators, datetime(2026, 10, 6, 5, 0), _raw_at(70.0, ac_charge_kwh=12.0))
        data = _cycle(accumulators, MORNING, _raw_at(70.0, ac_charge_kwh=12.0))
        average = (6 * NIGHTBOOST + 6 * NIGHT) / 12
        assert data.stored_energy_value == pytest.approx(0.30 * CAPACITY_KWH * average)

    def test_solar_stored_does_not_lower_the_average(self):
        """Only grid energy has a price. A day that also stored solar still averages the grid."""
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, _raw_at(40.0, ac_charge_kwh=0.0))
        _cycle(accumulators, CHARGING, _raw_at(60.0, ac_charge_kwh=4.0))
        data = _cycle(accumulators, MORNING, _raw_at(100.0, ac_charge_kwh=4.0))
        assert data.stored_energy_value == pytest.approx(0.60 * CAPACITY_KWH * NIGHTBOOST)

    def test_with_no_grid_charge_it_is_the_cheapest_rate(self):
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, _raw_at(40.0, ac_charge_kwh=0.0))
        data = _cycle(accumulators, MORNING, _raw_at(90.0, ac_charge_kwh=0.0))
        assert data.stored_energy_value == pytest.approx(0.50 * CAPACITY_KWH * NIGHTBOOST)

    def test_without_the_counter_it_is_the_cheapest_rate(self):
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, _raw_at(40.0))
        data = _cycle(accumulators, MORNING, _raw_at(90.0))
        assert data.stored_energy_value == pytest.approx(0.50 * CAPACITY_KWH * NIGHTBOOST)

    def test_energy_the_integration_did_not_price_is_left_out_of_the_average(self):
        """12 kWh were stored before the pricing existed, 2 kWh since, at the Night rate."""
        accumulators = _new_day(CounterMemory(12.0))
        accumulators.today.grid_to_battery_kwh = 12.0
        accumulators.today.soc_at_start_pct = 40.0
        _cycle(accumulators, datetime(2026, 10, 6, 5, 0), _raw_at(60.0, ac_charge_kwh=14.0))
        data = _cycle(accumulators, MORNING, _raw_at(60.0, ac_charge_kwh=14.0))
        assert data.today.grid_to_battery_priced_kwh == pytest.approx(2.0)
        assert data.stored_energy_value == pytest.approx(0.20 * CAPACITY_KWH * NIGHT)

    def test_a_flat_tariff_uses_its_one_rate(self):
        cfg = {**_nightboost_cfg(), "rate_periods": []}
        accumulators = _new_day()
        data = None
        for soc in (40.0, 70.0):
            data, _ = engine.build_coordinator_data(
                CycleInputs(raw=_raw_at(soc), cfg=cfg, now=MORNING),
                accumulators,
                PreviousCycle(BatteryStats(), None, None),
                ForecastContext(),
            )
        assert data.stored_energy_value == pytest.approx(0.30 * CAPACITY_KWH * DAY)

    def test_a_charge_is_priced_at_the_rate_in_force_when_the_counter_rose(self):
        accumulators = _new_day(CounterMemory(0.0))
        _cycle(accumulators, CHARGING, _raw_at(60.0, ac_charge_kwh=3.0))
        tariff = build_tariff(_nightboost_cfg())
        assert accumulators.today.grid_to_battery_cost == pytest.approx(
            tariff.calculate_import_cost(3.0, CHARGING)
        )


class TestAFallingBattery:
    def test_a_day_that_starts_full_and_ends_empty_is_charged_for_the_energy(self):
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, _raw_at(100.0))
        data = _cycle(accumulators, datetime(2026, 10, 6, 22, 0), _raw_at(0.0))
        assert data.stored_energy_change_kwh == pytest.approx(-CAPACITY_KWH)
        assert data.stored_energy_value == pytest.approx(-CAPACITY_KWH * NIGHTBOOST)

    def test_the_fall_cancels_the_cost_of_the_load_it_supplied(self):
        """The battery supplied 19 kWh of load with no import: the saving is not a free 19 kWh."""
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, _raw_at(100.0))
        accumulators.today.grid_equivalent_load_cost = CAPACITY_KWH * DAY
        data = _cycle(accumulators, datetime(2026, 10, 6, 22, 0), _raw_at(0.0))
        assert data.saving_vs_grid_today == pytest.approx(
            CAPACITY_KWH * (DAY - NIGHTBOOST), abs=1e-4
        )

    def test_an_empty_battery_at_midnight_is_a_real_starting_point(self):
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, _raw_at(0.0))
        data = _cycle(accumulators, MORNING, _raw_at(50.0))
        assert accumulators.today.soc_at_start_pct == 0.0
        assert data.stored_energy_change_kwh == pytest.approx(0.5 * CAPACITY_KWH)


class TestNothingMoves:
    def test_a_day_with_no_battery_movement_is_unchanged(self):
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, _raw_at(60.0))
        accumulators.today.grid_equivalent_load_cost = 1.5
        accumulators.today.import_cost_by_period = {"Day": 0.4}
        data = _cycle(accumulators, MORNING, _raw_at(60.0))
        assert data.stored_energy_change_kwh == 0.0
        assert data.stored_energy_value == 0.0
        assert data.saving_vs_grid_today == pytest.approx(1.1)

    def test_the_first_cycle_of_a_day_adds_nothing(self):
        data = _cycle(_new_day(), MIDNIGHT, _raw_at(47.0))
        assert data.stored_energy_value == 0.0
        assert data.saving_vs_grid_today == 0.0


class TestMissingReadings:
    def test_an_unknown_battery_capacity_adds_nothing(self):
        acc = EnergyAccumulator(soc_at_start_pct=40.0, grid_equivalent_load_cost=2.0)
        data = engine.CoordinatorData(today=acc)
        engine._set_savings_fields(data, _started_cycle(_raw_at(90.0, capacity_kwh=0.0)))
        assert data.stored_energy_change_kwh == 0.0
        assert data.stored_energy_value == 0.0
        assert data.saving_vs_grid_today == pytest.approx(2.0)

    def test_the_start_is_still_noted_while_the_capacity_is_unknown(self):
        acc = EnergyAccumulator()
        engine._bookmark_start_of_day_soc(acc, _raw_at(40.0, capacity_kwh=0.0))
        assert acc.soc_at_start_pct == 40.0

    def test_an_unavailable_soc_is_not_taken_as_the_start(self):
        raw = _raw_at(0.0)
        raw.unavailable_inputs = ("battery_soc",)
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, raw)
        assert accumulators.today.soc_at_start_pct is None

    def test_an_unavailable_soc_later_adds_nothing_not_a_fall_to_zero(self):
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, _raw_at(80.0))
        raw = _raw_at(0.0)
        raw.unavailable_inputs = ("battery_soc",)
        data = _cycle(accumulators, MORNING, raw)
        assert data.stored_energy_value == 0.0
        assert accumulators.today.soc_at_start_pct == 80.0

    def test_the_start_is_noted_once_the_soc_returns(self):
        raw = _raw_at(0.0)
        raw.unavailable_inputs = ("battery_soc",)
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, raw)
        _cycle(accumulators, MORNING, _raw_at(55.0))
        assert accumulators.today.soc_at_start_pct == 55.0


class TestAcrossMidnight:
    def test_a_new_day_starts_from_where_the_last_one_ended(self):
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, _raw_at(47.0))
        _cycle(accumulators, datetime(2026, 10, 6, 23, 59), _raw_at(30.0))
        tomorrow = Accumulators(
            today=EnergyAccumulator(),
            yesterday=accumulators.today,
            counters=accumulators.counters,
        )
        data = _cycle(tomorrow, datetime(2026, 10, 7, 0, 0, 30), _raw_at(30.0))
        assert tomorrow.today.soc_at_start_pct == 30.0
        assert data.stored_energy_value == 0.0
        assert data.saving_vs_grid_today == 0.0

    def test_yesterday_keeps_its_own_start(self):
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, _raw_at(47.0))
        tomorrow = Accumulators(today=EnergyAccumulator(), yesterday=accumulators.today)
        _cycle(tomorrow, datetime(2026, 10, 7, 0, 0, 30), _raw_at(30.0))
        assert tomorrow.yesterday.soc_at_start_pct == 47.0

    def test_the_counter_memory_carries_across_but_the_price_starts_again(self):
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, _raw_at(47.0, ac_charge_kwh=0.0))
        _cycle(accumulators, CHARGING, _raw_at(70.0, ac_charge_kwh=12.0))
        tomorrow = Accumulators(today=EnergyAccumulator(), counters=accumulators.counters)
        _cycle(tomorrow, datetime(2026, 10, 7, 0, 0, 30), _raw_at(86.0, ac_charge_kwh=12.0))
        assert tomorrow.today.grid_to_battery_priced_kwh == 0.0


def _days_between(soc_points: list[float], charged_kwh: list[float], rate_time: datetime):
    """Run one day per pair of SoC points. charged_kwh is the grid energy stored each day."""
    terms = []
    counters = CounterMemory()
    for day, (start, end) in enumerate(zip(soc_points, soc_points[1:], strict=False)):
        midnight = datetime(2026, 10, 6 + day, 0, 0, 30)
        accumulators = _new_day(counters)
        _cycle(accumulators, midnight, _raw_at(start, ac_charge_kwh=0.0))
        at_charge = rate_time.replace(day=6 + day)
        _cycle(accumulators, at_charge, _raw_at(end, ac_charge_kwh=charged_kwh[day]))
        data = _cycle(accumulators, midnight.replace(hour=22), _raw_at(end))
        terms.append(data.stored_energy_value)
    return terms


class TestAWeek:
    SOC = [40.0, 90.0, 60.0, 80.0, 50.0, 70.0, 55.0, 40.0]  # seven days, ends where it began

    def test_a_week_that_returns_to_the_start_adds_nothing_overall(self):
        terms = _days_between(self.SOC, [9.5, 0, 0, 0, 0, 0, 0], CHARGING)
        assert len(terms) == 7
        assert sum(terms) == pytest.approx(0.0, abs=1e-9)

    def test_a_charge_dearer_than_the_cheapest_rate_leaves_its_premium_in_the_week(self):
        """Bought at the Night rate, then used and valued at the cheapest rate: a real cost."""
        night = datetime(2026, 10, 6, 5, 0)
        terms = _days_between([40.0, 90.0, 40.0], [9.5, 0], night)
        assert sum(terms) == pytest.approx(0.50 * CAPACITY_KWH * (NIGHT - NIGHTBOOST))


class TestARestart:
    def test_the_day_continues_from_the_stored_start_and_price(self):
        accumulators = _new_day()
        _cycle(accumulators, MIDNIGHT, _raw_at(47.0, ac_charge_kwh=0.0))
        _cycle(accumulators, CHARGING, _raw_at(70.0, ac_charge_kwh=12.0))
        stored = _serialize(_state_with(accumulators))
        restored = _deserialize(stored)
        resumed = Accumulators(today=restored.today, counters=restored.counters)
        data = _cycle(resumed, MORNING, _raw_at(86.0, ac_charge_kwh=12.0))
        assert resumed.today.soc_at_start_pct == 47.0
        assert data.stored_energy_value == pytest.approx(0.39 * CAPACITY_KWH * NIGHTBOOST)

    def test_data_saved_before_the_bookmark_existed_starts_it_at_the_first_cycle(self):
        old = {"today": {"import_kwh": 10.0, "house_kwh": 20.0}}
        restored = _deserialize(old)
        assert restored.today.soc_at_start_pct is None
        resumed = Accumulators(today=restored.today, counters=restored.counters)
        data = _cycle(resumed, MORNING, _raw_at(86.0))
        assert resumed.today.soc_at_start_pct == 86.0
        assert data.stored_energy_value == 0.0

    def test_nothing_is_stored_for_an_accumulator_that_never_held_a_reading(self):
        stored = _acc_to_dict(EnergyAccumulator())
        assert "soc_at_start_pct" not in stored
        assert "grid_to_battery_cost" not in stored
        assert "grid_to_battery_priced_kwh" not in stored

    def test_the_figures_are_stored_once_they_exist(self):
        acc = EnergyAccumulator(
            soc_at_start_pct=0.0, grid_to_battery_cost=1.2, grid_to_battery_priced_kwh=12.0
        )
        stored = _acc_to_dict(acc)
        assert stored["soc_at_start_pct"] == 0.0
        assert stored["grid_to_battery_cost"] == 1.2
        assert stored["grid_to_battery_priced_kwh"] == 12.0

    def test_the_bookmark_alone_does_not_make_an_empty_accumulator_look_used(self):
        assert EnergyAccumulator(soc_at_start_pct=50.0) == EnergyAccumulator()


def _state_with(accumulators: Accumulators):
    state = _deserialize({})
    state.today = accumulators.today
    state.counters = accumulators.counters
    return state
