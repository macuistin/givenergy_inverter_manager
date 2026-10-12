"""Grid energy stored in the battery: reading GivTCP's AC charge counter into every period.

Today takes the counter itself. The week, month and year integrate live power, so each gets
the counter's rise since the last reading. The memory of that reading outlives midnight.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.core import engine
from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
from custom_components.givenergy_inverter_manager.core.counter_guard import screen
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
from tests.conftest import _nightboost_cfg, _raw

NOW = datetime(2026, 6, 15, 7, 0, tzinfo=timezone.utc)


def _growth(memory: CounterMemory, kwh: float, at: datetime) -> float:
    """What a reading of the AC charge counter adds to the longer periods."""
    raw = _raw()
    raw.ac_charge_energy_today_kwh = kwh
    screen(memory, raw, at)
    return memory.ac_charge_rise_kwh


MINUTE = timedelta(minutes=1)


class TestCounterMemory:
    def test_the_first_reading_counts_in_full(self):
        assert _growth(CounterMemory(), 7.5, NOW) == pytest.approx(7.5)

    def test_a_rising_counter_gives_the_rise(self):
        memory = CounterMemory()
        _growth(memory, 7.5, NOW)
        assert _growth(memory, 8.0, NOW + MINUTE) == pytest.approx(0.5)

    def test_an_unchanged_counter_gives_nothing(self):
        memory = CounterMemory()
        _growth(memory, 7.5, NOW)
        assert _growth(memory, 7.5, NOW + MINUTE) == 0.0

    def test_a_counter_that_fell_has_reset_and_counts_in_full(self):
        memory = CounterMemory()
        _growth(memory, 7.5, NOW)
        assert _growth(memory, 0.2, NOW + MINUTE) == pytest.approx(0.2)

    def test_the_reading_is_remembered_across_the_reset(self):
        memory = CounterMemory()
        _growth(memory, 7.5, NOW)
        _growth(memory, 0.2, NOW + MINUTE)
        assert memory.ac_charge_kwh == pytest.approx(0.2)
        assert _growth(memory, 0.5, NOW + 2 * MINUTE) == pytest.approx(0.3)

    def test_a_stale_reading_just_after_midnight_is_not_counted_twice(self):
        """GivTCP can publish yesterday's total for a minute after the reset."""
        memory = CounterMemory()
        total = _growth(memory, 7.5, NOW)
        total += _growth(memory, 7.5, NOW + MINUTE)  # still yesterday's value after midnight
        total += _growth(memory, 0.0, NOW + 2 * MINUTE)  # the reset arrives
        total += _growth(memory, 0.4, NOW + 3 * MINUTE)
        assert total == pytest.approx(7.9)


def _cycle(raw, accumulators: Accumulators, *, minutes: float = 1) -> engine.CoordinatorData:
    """Run one cycle, the given minutes after the last reading the counter memory holds."""
    readings = accumulators.counters.readings
    last = max((at for _, at in readings.values()), default=NOW - MINUTE)
    data, _ = engine.build_coordinator_data(
        CycleInputs(raw=raw, cfg=_nightboost_cfg(), now=last + timedelta(minutes=minutes)),
        accumulators,
        PreviousCycle(BatteryStats(), None, None),
        ForecastContext(),
    )
    return data


def _counter_raw(ac_charge_kwh: float | None, **counters):
    raw = _raw()
    raw.ac_charge_energy_today_kwh = ac_charge_kwh
    for name, value in counters.items():
        setattr(raw, name, value)
    return raw


def _periods(**today_fields) -> Accumulators:
    return Accumulators(
        today=EnergyAccumulator(**today_fields),
        week=EnergyAccumulator(),
        month=EnergyAccumulator(),
        year=EnergyAccumulator(),
        yesterday=EnergyAccumulator(),
        counters=CounterMemory(),
    )


def _after_midnight(accumulators: Accumulators) -> Accumulators:
    """What on_midnight leaves: a new today, the other periods and the counter memory kept."""
    return Accumulators(
        today=EnergyAccumulator(),
        week=accumulators.week,
        month=accumulators.month,
        year=accumulators.year,
        yesterday=accumulators.today,
        counters=accumulators.counters,
    )


class TestToday:
    def test_today_takes_the_counter(self):
        accumulators = _periods()
        _cycle(_counter_raw(7.5), accumulators)
        assert accumulators.today.grid_to_battery_kwh == pytest.approx(7.5)

    def test_the_live_case_reads_about_59_percent_not_zero(self):
        """12.1 kWh imported (7.5 into the battery) against 11.3 kWh of load."""
        raw = _counter_raw(7.5, import_energy_today_kwh=12.1, load_energy_today_kwh=11.3)
        data = _cycle(raw, _periods())
        assert data.today.self_sufficiency_pct == pytest.approx(59.3, abs=0.05)

    def test_without_the_counter_the_same_day_reads_zero_as_before(self):
        raw = _counter_raw(None, import_energy_today_kwh=12.1, load_energy_today_kwh=11.3)
        data = _cycle(raw, _periods())
        assert data.today.self_sufficiency_pct == 0.0

    def test_the_counter_is_reported_available_only_while_it_is_readable(self):
        assert _cycle(_counter_raw(0.0), _periods()).grid_to_battery_counter_available is True
        assert _cycle(_counter_raw(None), _periods()).grid_to_battery_counter_available is False

    def test_a_missing_counter_takes_nothing_off_import(self):
        """Not the last figure: import comes from a live counter, so the pair must agree."""
        accumulators = _periods(grid_to_battery_kwh=3.0)
        _cycle(_counter_raw(None), accumulators)
        assert accumulators.today.grid_to_battery_kwh == 0.0

    def test_the_figure_returns_with_the_counter(self):
        accumulators = _periods(grid_to_battery_kwh=3.0)
        _cycle(_counter_raw(None), accumulators)
        _cycle(_counter_raw(3.5), accumulators)
        assert accumulators.today.grid_to_battery_kwh == pytest.approx(3.5)


class TestLongerPeriods:
    def test_week_month_and_year_receive_the_growth(self):
        accumulators = _periods()
        _cycle(_counter_raw(7.5), accumulators)
        _cycle(_counter_raw(8.0), accumulators)
        for period in (accumulators.week, accumulators.month, accumulators.year):
            assert period.grid_to_battery_kwh == pytest.approx(8.0)

    def test_yesterday_is_a_record_and_gets_nothing(self):
        accumulators = _periods()
        _cycle(_counter_raw(7.5), accumulators)
        assert accumulators.yesterday.grid_to_battery_kwh == 0.0

    def test_the_midnight_reset_adds_the_new_day_without_losing_the_old(self):
        accumulators = _periods()
        _cycle(_counter_raw(7.5), accumulators)
        accumulators = _after_midnight(accumulators)
        _cycle(_counter_raw(0.0), accumulators)
        _cycle(_counter_raw(0.4), accumulators)
        assert accumulators.week.grid_to_battery_kwh == pytest.approx(7.9)
        assert accumulators.today.grid_to_battery_kwh == pytest.approx(0.4)
        assert accumulators.yesterday.grid_to_battery_kwh == pytest.approx(7.5)

    def test_a_stale_reading_after_the_reset_does_not_double_the_week(self):
        accumulators = _periods()
        _cycle(_counter_raw(7.5), accumulators)
        accumulators = _after_midnight(accumulators)  # handled before the counter resets
        _cycle(_counter_raw(7.5), accumulators)
        _cycle(_counter_raw(0.0), accumulators)
        assert accumulators.week.grid_to_battery_kwh == pytest.approx(7.5)

    def test_a_restart_catches_up_the_charge_made_while_it_was_down(self):
        """The memory and today's figure were stored at 6.0. The counter now reads 7.5."""
        accumulators = _periods(grid_to_battery_kwh=6.0)
        accumulators.counters.ac_charge_kwh = 6.0
        _cycle(_counter_raw(7.5), accumulators)
        assert accumulators.week.grid_to_battery_kwh == pytest.approx(1.5)

    def test_a_missing_counter_leaves_the_longer_periods_alone(self):
        accumulators = _periods()
        _cycle(_counter_raw(None), accumulators)
        assert accumulators.week.grid_to_battery_kwh == 0.0
        assert accumulators.counters.ac_charge_kwh == 0.0

    def test_periods_that_are_not_restored_yet_are_skipped(self):
        accumulators = Accumulators(today=EnergyAccumulator())
        _cycle(_counter_raw(7.5), accumulators)
        assert accumulators.today.grid_to_battery_kwh == pytest.approx(7.5)

    def test_week_self_sufficiency_counts_the_stored_charge(self):
        """Five nights of 7.5 kWh in the battery against 60 kWh of load and 80 kWh imported."""
        week = EnergyAccumulator(house_kwh=60.0, import_kwh=80.0)
        accumulators = Accumulators(today=EnergyAccumulator(), week=week, counters=CounterMemory())
        for _night in range(5):
            _cycle(_counter_raw(0.0), accumulators)
            _cycle(_counter_raw(7.5), accumulators, minutes=150)  # a night of charging
            accumulators = _after_midnight(accumulators)
        assert week.grid_to_battery_kwh == pytest.approx(37.5)
        assert week.self_sufficiency_pct == pytest.approx((1 - (80.0 - 37.5) / 60.0) * 100)

    def test_the_clock_does_not_matter_to_the_growth(self):
        accumulators = _periods()
        later = NOW + timedelta(hours=6)
        _cycle(_counter_raw(2.0), accumulators)
        engine.build_coordinator_data(
            CycleInputs(raw=_counter_raw(3.0), cfg=_nightboost_cfg(), now=later),
            accumulators,
            PreviousCycle(BatteryStats(), None, NOW),
            ForecastContext(),
        )
        assert accumulators.week.grid_to_battery_kwh == pytest.approx(3.0)


class TestSelfSufficiencyFollowsTheDocumentedDefinition:
    """Figures from a live review, where the sensor and an import/load ratio seemed to disagree.

    The sensor is 1 - (import - grid to battery) / house load, with grid to battery read from
    the AC charge counter. It is not the battery charge counter, which also holds solar.
    """

    @staticmethod
    def _pct(import_kwh: float, load_kwh: float, ac_charge_kwh: float) -> float:
        raw = _counter_raw(
            ac_charge_kwh, import_energy_today_kwh=import_kwh, load_energy_today_kwh=load_kwh
        )
        return _cycle(raw, _periods()).today.self_sufficiency_pct

    def test_a_day_with_a_large_ev_load_reads_low_but_above_the_plain_ratio(self):
        plain_ratio = (1 - 58.4 / 62.2) * 100
        assert plain_ratio == pytest.approx(6.1, abs=0.05)
        assert self._pct(58.4, 62.2, 5.0) == pytest.approx(14.1, abs=0.05)

    def test_a_reading_taken_earlier_in_the_day_uses_that_moment_counters(self):
        """08:42 that day: import 57.7, load 53.6, AC charge 5.0 gave 1.7 percent."""
        assert self._pct(57.7, 53.6, 5.0) == pytest.approx(1.7, abs=0.05)

    def test_the_figure_is_never_below_the_plain_ratio(self):
        for ac_charge_kwh in (0.0, 2.0, 5.0, 9.3):
            assert self._pct(58.4, 61.4, ac_charge_kwh) >= (1 - 58.4 / 61.4) * 100 - 1e-9

    def test_a_finished_day_reads_above_the_plain_ratio(self):
        """Yesterday: import 20.2, load 27.5, 7.5 kWh of the import stored in the battery."""
        assert self._pct(20.2, 27.5, 7.5) == pytest.approx(53.8, abs=0.05)
