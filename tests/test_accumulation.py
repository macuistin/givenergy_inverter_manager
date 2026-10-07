"""
test_accumulation.py — Unit tests for multi-period energy accumulation.

All tests are pure Python — AccumulationStore is not instantiated (it requires HA
Storage), but AccumulationState, the serialisation helpers, and on_midnight logic
are all testable without HA.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.accumulation import (
    AccumulationState,
    _deserialize,
    _serialize,
)
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

# ── Helpers ───────────────────────────────────────────────────────────────────


def _monday() -> datetime:
    """Monday midnight UTC — triggers weekly reset."""
    return datetime(2024, 7, 1, 0, 0, tzinfo=timezone.utc)  # 2024-07-01 is a Monday


def _tuesday() -> datetime:
    return datetime(2024, 7, 2, 0, 0, tzinfo=timezone.utc)


def _bill_day_15() -> datetime:
    return datetime(2024, 7, 15, 0, 0, tzinfo=timezone.utc)


def _midnight_reset(state: AccumulationState, now: datetime, bill_start_day: int = 1) -> None:
    """Apply the same logic as AccumulationStore.on_midnight but without HA Storage."""
    today_date = now.date()

    state.yesterday = state.today

    state.today = EnergyAccumulator()
    state.today_forecast_kwh = 0.0
    state.last_reset_iso = now.isoformat()

    if today_date.isoweekday() == 1:
        state.week = EnergyAccumulator()
        state.week_start_iso = now.isoformat()

    if today_date.day == bill_start_day:
        state.month = EnergyAccumulator()
        state.month_start_iso = now.isoformat()


# ── Midnight reset ────────────────────────────────────────────────────────────


class TestMidnightReset:
    def test_today_data_moves_to_yesterday(self):
        state = AccumulationState()
        state.today.solar_kwh = 12.5
        state.today.import_kwh = 3.2
        _midnight_reset(state, _tuesday())
        assert state.yesterday.solar_kwh == 12.5
        assert state.yesterday.import_kwh == 3.2

    def test_today_resets_to_zero(self):
        state = AccumulationState()
        state.today.solar_kwh = 12.5
        _midnight_reset(state, _tuesday())
        assert state.today.solar_kwh == 0.0
        assert state.today.import_kwh == 0.0

    def test_week_resets_on_monday(self):
        state = AccumulationState()
        state.week.solar_kwh = 80.0
        _midnight_reset(state, _monday())
        assert state.week.solar_kwh == 0.0
        assert state.week_start_iso != ""

    def test_week_does_not_reset_mid_week(self):
        state = AccumulationState()
        state.week.solar_kwh = 80.0
        _midnight_reset(state, _tuesday())
        assert state.week.solar_kwh == 80.0

    def test_month_resets_on_bill_start_day(self):
        state = AccumulationState()
        state.month.import_kwh = 200.0
        _midnight_reset(state, _bill_day_15(), bill_start_day=15)
        assert state.month.import_kwh == 0.0
        assert state.month_start_iso != ""

    def test_month_does_not_reset_on_other_days(self):
        state = AccumulationState()
        state.month.import_kwh = 200.0
        _midnight_reset(state, _tuesday(), bill_start_day=15)
        assert state.month.import_kwh == 200.0

    def test_week_and_month_can_reset_same_day(self):
        """Monday that is also bill start day resets both."""
        state = AccumulationState()
        state.week.solar_kwh = 50.0
        state.month.solar_kwh = 200.0
        # 2024-07-01 is a Monday AND we'll say bill_start_day=1
        _midnight_reset(state, _monday(), bill_start_day=1)
        assert state.week.solar_kwh == 0.0
        assert state.month.solar_kwh == 0.0


# ── Forecast accuracy ─────────────────────────────────────────────────────────


def _accuracy_store():
    """A store without HA Storage, to run the real on_midnight."""
    from unittest.mock import MagicMock

    from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore

    store = AccumulationStore.__new__(AccumulationStore)
    store._store = MagicMock()
    store._bill_start_day = 1
    store.state = AccumulationState()
    return store


def _finish_day(store, raw_forecast_kwh: float, solar_kwh: float, now: datetime) -> None:
    """Run midnight for a day that had *raw_forecast_kwh* forecast and made *solar_kwh*."""
    store.state.today_raw_forecast_kwh = raw_forecast_kwh
    store.state.today.solar_kwh = solar_kwh
    store.on_midnight(now)


class TestForecastAccuracy:
    def test_accuracy_calculated_at_midnight(self):
        store = _accuracy_store()
        _finish_day(store, 10.0, 8.5, _tuesday())
        assert store.state.yesterday_forecast_accuracy_pct == pytest.approx(85.0, rel=0.01)

    def test_perfect_forecast_gives_100_pct(self):
        store = _accuracy_store()
        _finish_day(store, 10.0, 10.0, _tuesday())
        assert store.state.yesterday_forecast_accuracy_pct == pytest.approx(100.0, rel=0.01)

    def test_accuracy_capped_at_200_pct(self):
        store = _accuracy_store()
        _finish_day(store, 5.0, 20.0, _tuesday())  # way above forecast
        assert store.state.yesterday_forecast_accuracy_pct == 200.0

    def test_no_accuracy_calculated_when_no_raw_forecast(self):
        store = _accuracy_store()
        _finish_day(store, 0.0, 8.0, _tuesday())
        assert store.state.yesterday_forecast_accuracy_pct == 0.0
        assert store.state.forecast_accuracy_history == []

    def test_a_charge_decision_forecast_does_not_stand_in_for_a_missing_raw_forecast(self):
        store = _accuracy_store()
        store.on_charge_decision(10.0)
        _finish_day(store, 0.0, 8.0, _tuesday())
        assert store.state.forecast_accuracy_history == []

    def test_day_with_nothing_accumulated_is_skipped(self):
        store = _accuracy_store()
        store.state.today_raw_forecast_kwh = 10.0
        store.on_midnight(_tuesday())
        assert store.state.forecast_accuracy_history == []

    def test_history_accumulates_over_days(self):
        store = _accuracy_store()
        for kwh in [8.0, 9.0, 10.0]:
            _finish_day(store, 10.0, kwh, _tuesday())
        assert store.state.forecast_accuracy_history == [80.0, 90.0, 100.0]

    def test_history_capped_at_7_days(self):
        store = _accuracy_store()
        for _ in range(10):
            _finish_day(store, 10.0, 9.0, _tuesday())
        assert len(store.state.forecast_accuracy_history) == 7

    def test_seven_day_average_follows_the_history(self):
        store = _accuracy_store()
        for kwh in [8.0, 10.0]:
            _finish_day(store, 10.0, kwh, _tuesday())
        assert store.forecast_accuracy_7day_avg_pct == pytest.approx(90.0)

    def test_forecast_cleared_at_midnight(self):
        store = _accuracy_store()
        store.on_charge_decision(10.0)
        store.on_midnight(_tuesday())
        assert store.state.today_forecast_kwh == 0.0


class TestForecastAccuracyAcrossMidnight:
    """The denominator is the raw forecast for the day, not the charge decision's figure."""

    def test_blended_charge_decision_forecast_does_not_set_the_denominator(self):
        store = _accuracy_store()
        day_start = datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)
        store.on_raw_forecast(7.54)  # sensor reading for the 6th, last seen on the 5th
        store.on_midnight(day_start)
        store.on_charge_decision(35.0)  # 01:59 decision: blended, and for another day
        store.state.today.solar_kwh = 6.64
        store.on_raw_forecast(9.0)  # reading for the 7th
        store.on_midnight(day_start + timedelta(days=1))
        assert store.state.yesterday_forecast_accuracy_pct == pytest.approx(88.1)
        assert store.state.forecast_accuracy_history == [88.1]

    def test_raw_forecast_read_after_midnight_does_not_change_the_finished_day(self):
        store = _accuracy_store()
        day_start = datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)
        store.on_raw_forecast(7.54)
        store.on_midnight(day_start)
        store.state.today.solar_kwh = 6.64
        store.on_raw_forecast(20.0)  # tomorrow's forecast arrives during the day
        store.on_midnight(day_start + timedelta(days=1))
        assert store.state.forecast_accuracy_history == [88.1]

    def test_accuracy_agrees_with_the_ratio_history(self):
        store = _accuracy_store()
        day_start = datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)
        store.on_raw_forecast(7.54)
        store.on_midnight(day_start)
        store.state.today.solar_kwh = 6.64
        store.on_midnight(day_start + timedelta(days=1))
        record = store.state.forecast_ratio_history[-1]
        assert store.state.yesterday_forecast_accuracy_pct == pytest.approx(
            record["actual"] / record["forecast"] * 100, abs=0.05
        )


# ── Serialisation / deserialisation ──────────────────────────────────────────


class TestSerialisationRoundtrip:
    def test_empty_state_roundtrip(self):
        state = AccumulationState()
        restored = _deserialize(_serialize(state))
        assert restored.today.solar_kwh == 0.0
        assert restored.week.import_kwh == 0.0

    def test_populated_state_roundtrip(self):
        state = AccumulationState()
        state.today.solar_kwh = 12.5
        state.today.import_kwh = 3.2
        state.today.import_kwh_cheap = 1.8
        state.week.solar_kwh = 80.0
        state.month.import_cost_peak = 4.50
        state.yesterday.immersion_savings = 0.85
        state.today_forecast_kwh = 15.0
        state.yesterday_forecast_accuracy_pct = 92.5
        state.forecast_accuracy_history = [90.0, 85.0, 92.5]
        state.week_start_iso = "2024-07-01T00:00:00+00:00"

        restored = _deserialize(_serialize(state))

        assert restored.today.solar_kwh == pytest.approx(12.5)
        assert restored.today.import_kwh_cheap == pytest.approx(1.8)
        assert restored.week.solar_kwh == pytest.approx(80.0)
        assert restored.month.import_cost_peak == pytest.approx(4.50)
        assert restored.yesterday.immersion_savings == pytest.approx(0.85)
        assert restored.today_forecast_kwh == pytest.approx(15.0)
        assert restored.yesterday_forecast_accuracy_pct == pytest.approx(92.5)
        assert restored.forecast_accuracy_history == [90.0, 85.0, 92.5]
        assert restored.week_start_iso == "2024-07-01T00:00:00+00:00"

    def test_year_and_year_start_survive_a_roundtrip(self):
        state = AccumulationState()
        state.year.solar_kwh = 2100.0
        state.year.export_earnings = 310.5
        state.year_start_iso = "2026-01-01T00:00:00+00:00"

        restored = _deserialize(_serialize(state))

        assert restored.year.solar_kwh == pytest.approx(2100.0)
        assert restored.year.export_earnings == pytest.approx(310.5)
        assert restored.year_start_iso == "2026-01-01T00:00:00+00:00"

    def test_missed_solar_and_derating_minutes_survive_a_roundtrip(self):
        state = AccumulationState()
        state.today.missed_solar_kwh = 1.75
        state.today.inverter_derating_minutes = 42.0
        state.week.missed_solar_kwh = 4.5

        restored = _deserialize(_serialize(state))

        assert restored.today.missed_solar_kwh == pytest.approx(1.75)
        assert restored.today.inverter_derating_minutes == pytest.approx(42.0)
        assert restored.week.missed_solar_kwh == pytest.approx(4.5)

    def test_missing_fields_in_stored_data_use_defaults(self):
        """Old stored data without new fields should restore gracefully."""
        minimal_data = {
            "version": 1,
            "today": {"solar_kwh": 5.0},
            "week": {},
            "month": {},
            "yesterday": {},
        }
        restored = _deserialize(minimal_data)
        assert restored.today.solar_kwh == pytest.approx(5.0)
        assert restored.today.import_kwh_cheap == 0.0  # new field, defaults to 0
        assert restored.today_forecast_kwh == 0.0
        assert restored.forecast_accuracy_history == []


# ── Persistence round-trip ────────────────────────────────────────────────────


class TestPersistence:
    """AccumulationStore must restore exactly what was saved.
    Previously async_load() was never called, so this path was completely untested."""

    def _make_store(self, saved_data_holder):
        """Return an AccumulationStore whose _store is replaced with a mock."""
        import sys
        import types
        from unittest.mock import AsyncMock, MagicMock

        # Ensure homeassistant.helpers.storage is in sys.modules (lazy import in __init__)
        if "homeassistant.helpers.storage" not in sys.modules:
            storage_mod = types.ModuleType("homeassistant.helpers.storage")
            storage_mod.Store = MagicMock
            sys.modules["homeassistant.helpers.storage"] = storage_mod
            sys.modules["homeassistant.helpers"].storage = storage_mod

        mock_ha_store = MagicMock()
        mock_ha_store.async_save = AsyncMock(
            side_effect=lambda d: saved_data_holder.__setitem__("data", d)
        )
        mock_ha_store.async_load = AsyncMock(side_effect=lambda: saved_data_holder.get("data"))
        # Replace Store class so AccumulationStore.__init__ gets our mock
        sys.modules["homeassistant.helpers.storage"].Store = MagicMock(return_value=mock_ha_store)

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore

        store = AccumulationStore(MagicMock(), bill_start_day=1)
        # Ensure our mock is used (in case __init__ already ran with a different mock)
        store._store = mock_ha_store
        return store

    def test_save_then_load_restores_solar_kwh(self):
        import asyncio

        shared = {}
        store = self._make_store(shared)
        store.state.today.solar_kwh = 12.5
        store.state.week.solar_kwh = 55.3
        store.state.month.import_kwh = 88.1
        asyncio.run(store.async_save())

        store2 = self._make_store(shared)
        asyncio.run(store2.async_load())

        assert store2.today.solar_kwh == pytest.approx(12.5)
        assert store2.week.solar_kwh == pytest.approx(55.3)
        assert store2.month.import_kwh == pytest.approx(88.1)

    def test_load_with_no_stored_data_starts_fresh(self):
        """async_load with no saved data must not raise and must start at zero."""
        import asyncio

        store = self._make_store({})
        asyncio.run(store.async_load())

        assert store.today.solar_kwh == pytest.approx(0.0)
        assert store.week.solar_kwh == pytest.approx(0.0)

    def test_load_with_corrupt_data_starts_fresh(self):
        """Corrupt stored data must not crash — falls back to zero state."""
        import asyncio

        store = self._make_store({"data": {"totally": "wrong", "schema": True}})
        asyncio.run(store.async_load())

        assert store.today.solar_kwh == pytest.approx(0.0)


# ── Week / month actually accumulate ─────────────────────────────────────────


class TestWeekMonthFunctional:
    """Verify accumulate_energy actually increments week and month accumulators.
    This was broken: the engine only called accumulate_energy on acc (today)."""

    def _run_accumulation(self, acc, grid_w=-500.0, solar_w=1000.0, elapsed_h=1 / 120):
        """Call accumulate_energy on a given accumulator and return it."""
        from datetime import datetime, timezone

        from custom_components.givenergy_inverter_manager.core.engine import RawSensorValues
        from custom_components.givenergy_inverter_manager.core.tariff import build_tariff
        from tests.conftest import _nightboost_cfg
        from tests.core.flat_engine import accumulate_energy

        cfg = _nightboost_cfg()
        tariff = build_tariff(cfg)
        raw = RawSensorValues()
        raw.solar_power_w = solar_w
        raw.grid_power_w = abs(grid_w)  # positive = importing
        raw.house_load_w = 500.0
        raw.battery_power_w = 0.0
        raw.battery_soc = 80.0
        raw.immersion_on = False
        raw.immersion_wattage_w = 0.0
        raw.ev_power_w = 0.0

        now = datetime(2024, 7, 10, 14, 0, tzinfo=timezone.utc)
        last = datetime(2024, 7, 10, 13, 59, 30, tzinfo=timezone.utc)
        accumulate_energy(acc, raw, tariff, "Day", now, last)
        return acc

    def test_week_import_grows_after_accumulation(self):
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        acc_week = EnergyAccumulator()
        self._run_accumulation(acc_week, grid_w=-500.0)
        assert acc_week.import_kwh > 0, (
            "acc_week.import_kwh should be > 0 after accumulate_energy. "
            "If 0, the week accumulator is not being updated each cycle."
        )

    def test_month_solar_grows_after_accumulation(self):
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        acc_month = EnergyAccumulator()
        self._run_accumulation(acc_month, solar_w=2000.0, grid_w=0.0)
        assert acc_month.solar_kwh > 0, "acc_month.solar_kwh should be > 0 after accumulate_energy."

    def test_today_week_month_all_accumulate_together(self):
        """All three accumulators should grow by the same amount in one cycle."""
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        accs = [EnergyAccumulator() for _ in range(3)]
        for acc in accs:
            self._run_accumulation(acc, solar_w=1000.0, grid_w=-200.0)
        solar_values = [a.solar_kwh for a in accs]
        assert len({round(v, 6) for v in solar_values}) == 1, (
            "today, week, and month should accumulate identically in one cycle"
        )


class TestForecastRecording:
    """on_charge_decision must be called so solar_forecast_today is non-zero."""

    def test_on_charge_decision_sets_today_forecast(self):
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore

        store = AccumulationStore(MagicMock(), 16)
        assert store.today_forecast_kwh == 0.0
        store.on_charge_decision(38.5)
        assert store.today_forecast_kwh == 38.5

    def test_on_charge_decision_ignores_zero(self):
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore

        store = AccumulationStore(MagicMock(), 16)
        store.on_charge_decision(0.0)
        assert store.today_forecast_kwh == 0.0

    def test_on_charge_decision_only_sets_once(self):
        """Once set, a second call must not overwrite (first reading locks it)."""
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore

        store = AccumulationStore(MagicMock(), 16)
        store.on_charge_decision(38.5)
        store.on_charge_decision(10.0)
        assert store.today_forecast_kwh == 38.5


class TestBatteryStatsPersistence:
    """BatteryStats must survive HA restarts via AccumulationStore."""

    def test_save_and_restore_total_cycles(self):
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore
        from custom_components.givenergy_inverter_manager.core.battery import BatteryStats

        store = AccumulationStore(MagicMock(), 16)
        stats = BatteryStats(total_cycles=4.7)
        store.save_battery_stats(stats)
        restored = BatteryStats()
        store.restore_battery_stats(restored)
        assert restored.total_cycles == 4.7

    def test_save_and_restore_tracking_start(self):
        from datetime import date
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore
        from custom_components.givenergy_inverter_manager.core.battery import BatteryStats

        store = AccumulationStore(MagicMock(), 16)
        stats = BatteryStats(
            total_cycles=90.0,
            tracking_start_date=date(2026, 7, 9),
            tracking_start_cycles=79.0,
        )
        store.save_battery_stats(stats)
        restored = BatteryStats()
        store.restore_battery_stats(restored)
        assert restored.tracking_start_date == date(2026, 7, 9)
        assert restored.tracking_start_cycles == 79.0

    def test_tracking_start_survives_serialisation(self):
        from custom_components.givenergy_inverter_manager.accumulation import (
            AccumulationState,
            _deserialize,
            _serialize,
        )

        state = AccumulationState()
        state.battery_tracking_start = "2026-07-09"
        state.battery_tracking_start_cycles = 79.0
        loaded = _deserialize(_serialize(state))
        assert loaded.battery_tracking_start == "2026-07-09"
        assert loaded.battery_tracking_start_cycles == 79.0

    def test_save_and_restore_last_full_charge_date(self):
        from datetime import date
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore
        from custom_components.givenergy_inverter_manager.core.battery import BatteryStats

        store = AccumulationStore(MagicMock(), 16)
        d = date(2026, 7, 9)
        stats = BatteryStats(last_full_charge_date=d)
        store.save_battery_stats(stats)
        restored = BatteryStats()
        store.restore_battery_stats(restored)
        assert restored.last_full_charge_date == d

    def test_restore_leaves_zero_untouched(self):
        """If no saved stats exist, BatteryStats stays at defaults."""
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore
        from custom_components.givenergy_inverter_manager.core.battery import BatteryStats

        store = AccumulationStore(MagicMock(), 16)
        stats = BatteryStats()
        store.restore_battery_stats(stats)
        assert stats.total_cycles == 0.0
        assert stats.last_full_charge_date is None


# ── AccumulationStore property coverage ──────────────────────────────────────


class TestStorePropertyCoverage:
    def _store(self):
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore

        return AccumulationStore(MagicMock(), bill_start_day=1)

    def test_year_property_returns_accumulator(self):
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        store = self._store()
        assert isinstance(store.year, EnergyAccumulator)

    def test_today_forecast_kwh_defaults_to_zero(self):
        store = self._store()
        assert store.today_forecast_kwh == 0.0

    def test_forecast_accuracy_7day_avg_zero_when_no_history(self):
        store = self._store()
        assert store.forecast_accuracy_7day_avg_pct == 0.0

    def test_forecast_accuracy_7day_avg_with_history(self):
        store = self._store()
        store.state.forecast_accuracy_history = [90.0, 95.0, 100.0]
        assert store.forecast_accuracy_7day_avg_pct == pytest.approx(95.0)

    def test_update_bill_start_day(self):
        store = self._store()
        store.update_bill_start_day(16)
        assert store._bill_start_day == 16


# ── async_load / async_save error branches ───────────────────────────────────


class TestStorageErrorBranches:
    def test_async_load_corrupt_data_starts_fresh(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore

        hass = MagicMock()
        store = AccumulationStore(hass, bill_start_day=1)
        mock_ha_store = AsyncMock()
        mock_ha_store.async_load = AsyncMock(return_value={"bad": "data"})
        store._store = mock_ha_store
        store.state.today.solar_kwh = 5.0

        asyncio.run(store.async_load())
        assert store.state.today.solar_kwh == 0.0

    def test_async_save_exception_does_not_raise(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore

        hass = MagicMock()
        store = AccumulationStore(hass, bill_start_day=1)
        mock_ha_store = AsyncMock()
        mock_ha_store.async_save = AsyncMock(side_effect=OSError("disk full"))
        store._store = mock_ha_store

        asyncio.run(store.async_save())


# ── on_midnight resets ────────────────────────────────────────────────────────


class TestOnMidnight:
    def _store(self, bill_start_day=1):
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore

        return AccumulationStore(MagicMock(), bill_start_day=bill_start_day)

    def test_snapshots_today_to_yesterday(self):
        from datetime import datetime, timezone

        store = self._store()
        store.state.today.solar_kwh = 8.5
        store.on_midnight(datetime(2026, 7, 8, 0, 0, tzinfo=timezone.utc))
        assert store.yesterday.solar_kwh == pytest.approx(8.5)

    def test_resets_today_after_snapshot(self):
        from datetime import datetime, timezone

        store = self._store()
        store.state.today.solar_kwh = 8.5
        store.on_midnight(datetime(2026, 7, 8, 0, 0, tzinfo=timezone.utc))
        assert store.state.today.solar_kwh == pytest.approx(0.0)

    def test_records_forecast_accuracy_when_raw_forecast_positive(self):
        from datetime import datetime, timezone

        store = self._store()
        store.state.today_raw_forecast_kwh = 10.0
        store.state.today.solar_kwh = 8.0
        store.on_midnight(datetime(2026, 7, 8, 0, 0, tzinfo=timezone.utc))
        assert store.state.yesterday_forecast_accuracy_pct == pytest.approx(80.0)
        assert 80.0 in store.state.forecast_accuracy_history

    def test_weekly_reset_on_monday(self):
        from datetime import datetime, timezone

        store = self._store()
        store.state.week.solar_kwh = 42.0
        monday = datetime(2026, 7, 13, 0, 0, tzinfo=timezone.utc)  # a Monday
        store.on_midnight(monday)
        assert store.state.week.solar_kwh == pytest.approx(0.0)

    def test_no_weekly_reset_on_non_monday(self):
        from datetime import datetime, timezone

        store = self._store()
        store.state.week.solar_kwh = 42.0
        tuesday = datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc)
        store.on_midnight(tuesday)
        assert store.state.week.solar_kwh == pytest.approx(42.0)

    def test_monthly_reset_on_bill_start_day(self):
        from datetime import datetime, timezone

        store = self._store(bill_start_day=16)
        store.state.month.solar_kwh = 100.0
        bill_day = datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)
        store.on_midnight(bill_day)
        assert store.state.month.solar_kwh == pytest.approx(0.0)

    def test_yearly_reset_on_jan_1(self):
        from datetime import datetime, timezone

        store = self._store()
        store.state.year.solar_kwh = 3000.0
        jan1 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        store.on_midnight(jan1)
        assert store.state.year.solar_kwh == pytest.approx(0.0)

    def test_monthly_reset_snapshots_export_kwh(self):
        # Arrange — build store without HA Storage
        from datetime import datetime, timezone
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import (
            AccumulationState,
            AccumulationStore,
        )

        store = AccumulationStore.__new__(AccumulationStore)
        store.state = AccumulationState()
        store._bill_start_day = 1
        store._store = MagicMock()
        store.state.month.export_kwh = 85.5
        bill_day = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)

        # Act
        store.on_midnight(bill_day)

        # Assert — snapshot captured, month cleared
        assert store.state.monthly_export_snapshots == [pytest.approx(85.5)]
        assert store.state.month.export_kwh == pytest.approx(0.0)

    def test_monthly_snapshots_capped_at_12(self):
        # Arrange — seed 12 existing snapshots
        from datetime import datetime, timezone
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import (
            AccumulationState,
            AccumulationStore,
        )

        store = AccumulationStore.__new__(AccumulationStore)
        store.state = AccumulationState()
        store._bill_start_day = 1
        store._store = MagicMock()
        store.state.monthly_export_snapshots = [float(i) for i in range(12)]  # 0..11
        store.state.month.export_kwh = 99.0
        bill_day = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)

        # Act
        store.on_midnight(bill_day)

        # Assert — oldest entry (0) dropped, new entry appended
        assert len(store.state.monthly_export_snapshots) == 12
        assert store.state.monthly_export_snapshots[-1] == pytest.approx(99.0)
        assert store.state.monthly_export_snapshots[0] == pytest.approx(1.0)

    def test_trailing_12m_export_kwh_property(self):
        # Arrange
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore

        store = AccumulationStore.__new__(AccumulationStore)
        from custom_components.givenergy_inverter_manager.accumulation import AccumulationState

        store.state = AccumulationState()
        store._bill_start_day = 1
        store._store = MagicMock()
        store.state.monthly_export_snapshots = [10.0, 20.5, 30.0]

        # Act / Assert
        assert store.trailing_12m_export_kwh == pytest.approx(60.5)

    def test_trailing_12m_zero_when_no_snapshots(self):
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import (
            AccumulationState,
            AccumulationStore,
        )

        store = AccumulationStore.__new__(AccumulationStore)
        store.state = AccumulationState()
        store._bill_start_day = 1
        store._store = MagicMock()

        assert store.trailing_12m_export_kwh == pytest.approx(0.0)


# ── restore_battery_stats with valid ISO date ─────────────────────────────────


class TestRestoreBatteryStatsISO:
    def test_restores_last_full_charge_date_from_iso_string(self):
        from datetime import date
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore
        from custom_components.givenergy_inverter_manager.core.battery import BatteryStats

        store = AccumulationStore(MagicMock(), bill_start_day=1)
        store.state.last_full_charge_date = "2026-07-01"
        stats = BatteryStats()
        store.restore_battery_stats(stats)
        assert stats.last_full_charge_date == date(2026, 7, 1)


class TestMonthlySnapshots:
    """Complete monthly billing snapshots stored at each month reset."""

    def _make_store(self, bill_start_day=1):
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import (
            AccumulationState,
            AccumulationStore,
        )

        store = AccumulationStore.__new__(AccumulationStore)
        store.state = AccumulationState()
        store._bill_start_day = bill_start_day
        store._store = MagicMock()
        return store

    def test_snapshot_captured_at_monthly_reset(self):
        from datetime import datetime, timezone


        store = self._make_store()
        store.state.month.solar_kwh = 45.0
        store.state.month.export_kwh = 12.5
        bill_day = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
        store.on_midnight(bill_day)
        assert len(store.state.monthly_snapshots) == 1
        assert store.state.monthly_snapshots[0]["solar_kwh"] == pytest.approx(45.0)
        assert store.state.monthly_snapshots[0]["export_kwh"] == pytest.approx(12.5)
        assert store.state.month.solar_kwh == pytest.approx(0.0)

    def test_snapshots_capped_at_12(self):
        from datetime import datetime, timezone

        store = self._make_store()
        store.state.monthly_snapshots = [{"solar_kwh": float(i)} for i in range(12)]
        store.state.month.solar_kwh = 99.9
        bill_day = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
        store.on_midnight(bill_day)
        assert len(store.state.monthly_snapshots) == 12
        assert store.state.monthly_snapshots[-1]["solar_kwh"] == pytest.approx(99.9)
        assert store.state.monthly_snapshots[0]["solar_kwh"] == pytest.approx(1.0)

    def test_trailing_12m_solar(self):
        store = self._make_store()
        store.state.monthly_snapshots = [{"solar_kwh": 10.0, "export_kwh": 2.0} for _ in range(6)]
        assert store.trailing_12m_solar_kwh == pytest.approx(60.0)

    def test_trailing_12m_zero_when_no_snapshots(self):
        store = self._make_store()
        assert store.trailing_12m_solar_kwh == pytest.approx(0.0)
        assert store.trailing_12m_export_kwh == pytest.approx(0.0)

    def test_serialization_roundtrip(self):
        from custom_components.givenergy_inverter_manager.accumulation import (
            AccumulationState,
            _deserialize,
            _serialize,
        )

        state = AccumulationState()
        state.monthly_snapshots = [{"solar_kwh": 30.5, "export_kwh": 5.0, "import_kwh": 20.0}]
        restored = _deserialize(_serialize(state))
        assert len(restored.monthly_snapshots) == 1
        assert restored.monthly_snapshots[0]["solar_kwh"] == pytest.approx(30.5)


# ── Restart across a reset boundary ──────────────────────────────────────────


def _restart(saved: AccumulationState, bill_start_day: int = 1):
    """A new store holding what a previous run wrote to storage."""
    from unittest.mock import MagicMock

    from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore

    store = AccumulationStore(MagicMock(), bill_start_day=bill_start_day)
    store.state = _deserialize(_serialize(saved))
    return store


def _stored_run(last_midnight: datetime) -> AccumulationState:
    """State as left by a run that last passed midnight at *last_midnight*."""
    state = AccumulationState()
    state.last_reset_iso = last_midnight.isoformat()
    state.today.solar_kwh = 9.0
    state.today.import_kwh = 2.0
    state.week.solar_kwh = 50.0
    state.month.solar_kwh = 200.0
    state.year.solar_kwh = 1500.0
    return state


class TestRollForwardOnRestart:
    def test_restart_on_the_same_day_changes_nothing(self):
        store = _restart(_stored_run(datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc)))
        store.state.week_start_iso = "2026-07-13T00:00:00+00:00"
        store.state.month_start_iso = "2026-07-01T00:00:00+00:00"
        store.state.year_start_iso = "2026-01-01T00:00:00+00:00"

        changed = store.roll_forward(datetime(2026, 7, 14, 18, 30, tzinfo=timezone.utc))

        assert changed is False
        assert store.today.solar_kwh == pytest.approx(9.0)
        assert store.yesterday.solar_kwh == 0.0
        assert store.state.last_reset_iso == "2026-07-14T00:00:00+00:00"

    def test_restart_after_one_midnight_moves_today_to_yesterday(self):
        store = _restart(_stored_run(datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc)))

        changed = store.roll_forward(datetime(2026, 7, 15, 7, 0, tzinfo=timezone.utc))

        assert changed is True
        assert store.yesterday.solar_kwh == pytest.approx(9.0)
        assert store.today.solar_kwh == 0.0
        assert store.today.import_kwh == 0.0
        assert store.state.last_reset_iso == "2026-07-15T00:00:00+00:00"
        assert store.week.solar_kwh == pytest.approx(50.0)

    def test_restart_after_several_days_leaves_no_yesterday_data(self):
        store = _restart(_stored_run(datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc)))

        store.roll_forward(datetime(2026, 7, 17, 7, 0, tzinfo=timezone.utc))

        assert store.today.solar_kwh == 0.0
        assert store.yesterday.solar_kwh == 0.0
        assert store.state.last_reset_iso == "2026-07-17T00:00:00+00:00"

    def test_missed_monday_resets_the_week(self):
        # Last run passed midnight on Saturday 11 July. Restart on Tuesday 14 July.
        store = _restart(_stored_run(datetime(2026, 7, 11, 0, 0, tzinfo=timezone.utc)))

        store.roll_forward(datetime(2026, 7, 14, 7, 0, tzinfo=timezone.utc))

        assert store.week.solar_kwh == 0.0
        assert store.state.week_start_iso == "2026-07-13T00:00:00+00:00"
        assert store.month.solar_kwh == pytest.approx(200.0)

    def test_week_is_kept_when_no_monday_was_missed(self):
        store = _restart(_stored_run(datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc)))
        store.state.week_start_iso = "2026-07-13T00:00:00+00:00"

        store.roll_forward(datetime(2026, 7, 16, 7, 0, tzinfo=timezone.utc))

        assert store.week.solar_kwh == pytest.approx(50.0)
        assert store.state.week_start_iso == "2026-07-13T00:00:00+00:00"

    def test_missed_bill_day_resets_the_month_and_snapshots_it(self):
        store = _restart(
            _stored_run(datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc)), bill_start_day=16
        )
        store.state.month.export_kwh = 80.0

        store.roll_forward(datetime(2026, 7, 18, 7, 0, tzinfo=timezone.utc))

        assert store.month.solar_kwh == 0.0
        assert store.state.month_start_iso == "2026-07-16T00:00:00+00:00"
        assert store.monthly_export_snapshots == [pytest.approx(80.0)]
        assert store.monthly_snapshots[-1]["solar_kwh"] == pytest.approx(200.0)

    def test_several_missed_bill_days_add_one_snapshot_each(self):
        store = _restart(_stored_run(datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)))

        store.roll_forward(datetime(2026, 8, 5, 7, 0, tzinfo=timezone.utc))

        assert len(store.monthly_snapshots) == 2
        assert store.monthly_snapshots[0]["solar_kwh"] == pytest.approx(200.0)
        assert store.monthly_snapshots[1]["solar_kwh"] == 0.0
        assert store.state.month_start_iso == "2026-08-01T00:00:00+00:00"

    def test_missed_new_year_resets_the_year(self):
        store = _restart(_stored_run(datetime(2025, 12, 30, 0, 0, tzinfo=timezone.utc)))

        store.roll_forward(datetime(2026, 1, 2, 7, 0, tzinfo=timezone.utc))

        assert store.year.solar_kwh == 0.0
        assert store.state.year_start_iso == "2026-01-01T00:00:00+00:00"

    def test_year_is_kept_inside_the_same_year(self):
        store = _restart(_stored_run(datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc)))

        store.roll_forward(datetime(2026, 7, 20, 7, 0, tzinfo=timezone.utc))

        assert store.year.solar_kwh == pytest.approx(1500.0)

    def test_forecast_accuracy_is_recorded_once_for_the_stored_day(self):
        saved = _stored_run(datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc))
        saved.today_raw_forecast_kwh = 10.0
        saved.today_forecast_kwh = 10.0
        store = _restart(saved)

        store.roll_forward(datetime(2026, 7, 17, 7, 0, tzinfo=timezone.utc))

        assert store.state.forecast_accuracy_history == [90.0]
        assert store.state.today_forecast_kwh == 0.0

    def test_days_missed_while_down_do_not_record_zero_accuracy(self):
        saved = _stored_run(datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc))
        saved.today_raw_forecast_kwh = 10.0
        saved.pending_raw_forecast_kwh = 8.0  # forecast for the 15th, a day Home Assistant missed
        store = _restart(saved)

        store.roll_forward(datetime(2026, 7, 17, 7, 0, tzinfo=timezone.utc))

        assert store.state.forecast_accuracy_history == [90.0]

    def test_dst_zone_keeps_local_midnight_stamps(self):
        from zoneinfo import ZoneInfo

        dublin = ZoneInfo("Europe/Dublin")
        store = _restart(_stored_run(datetime(2026, 3, 27, 0, 0, tzinfo=dublin)))

        store.roll_forward(datetime(2026, 3, 30, 9, 0, tzinfo=dublin))

        assert store.state.last_reset_iso == "2026-03-30T00:00:00+01:00"
        assert store.state.week_start_iso == "2026-03-30T00:00:00+01:00"

    def test_first_ever_start_stamps_today_and_keeps_data(self):
        store = _restart(AccumulationState())

        changed = store.roll_forward(datetime(2026, 7, 15, 7, 0, tzinfo=timezone.utc))

        assert changed is True
        assert store.state.last_reset_iso == "2026-07-15T00:00:00+00:00"
        assert store.yesterday.solar_kwh == 0.0

    def test_empty_period_starts_default_to_the_current_period(self):
        store = _restart(AccumulationState(), bill_start_day=16)

        store.roll_forward(datetime(2026, 7, 15, 7, 0, tzinfo=timezone.utc))

        assert store.state.week_start_iso == "2026-07-13T00:00:00+00:00"
        assert store.state.month_start_iso == "2026-06-16T00:00:00+00:00"
        assert store.state.year_start_iso == "2026-01-01T00:00:00+00:00"

    def test_existing_period_starts_are_not_overwritten(self):
        saved = _stored_run(datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc))
        saved.week_start_iso = "2026-07-06T00:00:00+00:00"
        store = _restart(saved)

        store.roll_forward(datetime(2026, 7, 14, 18, 0, tzinfo=timezone.utc))

        assert store.state.week_start_iso == "2026-07-06T00:00:00+00:00"


class TestScheduleSave:
    def test_delayed_save_serialises_the_state_at_write_time(self):
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore

        store = AccumulationStore(MagicMock(), bill_start_day=1)
        store._store = MagicMock()

        store.schedule_save()
        store.state.today.solar_kwh = 7.0

        data_func, delay = store._store.async_delay_save.call_args.args
        assert delay > 0
        assert data_func()["today"]["solar_kwh"] == pytest.approx(7.0)
# ── Storage version migration ─────────────────────────────────────────────────


def _v1_payload() -> dict:
    """A payload as written by storage version 1 (both-directions cycle count)."""
    payload = _serialize(AccumulationState())
    payload["version"] = 1
    payload["battery_cycles"] = 62.6
    payload["battery_tracking_start"] = "2026-01-10"
    payload["battery_tracking_start_cycles"] = 10.0
    payload["last_full_charge_date"] = "2026-10-01"
    payload["today"]["solar_kwh"] = 7.5
    return payload


class TestStorageMigration:
    def test_storage_version_is_bumped(self):
        from custom_components.givenergy_inverter_manager import accumulation

        assert accumulation._STORAGE_VERSION == 3

    def test_version_1_cycle_figures_are_halved(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        migrated = migrate_storage(1, _v1_payload())
        assert migrated["battery_cycles"] == pytest.approx(31.3)
        assert migrated["battery_tracking_start_cycles"] == pytest.approx(5.0)
        assert migrated["version"] == 3

    def test_other_fields_are_left_alone(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        migrated = migrate_storage(1, _v1_payload())
        assert migrated["today"]["solar_kwh"] == pytest.approx(7.5)
        assert migrated["battery_tracking_start"] == "2026-01-10"
        assert migrated["last_full_charge_date"] == "2026-10-01"

    def test_input_payload_is_not_mutated(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        payload = _v1_payload()
        migrate_storage(1, payload)
        assert payload["battery_cycles"] == pytest.approx(62.6)

    def test_current_version_payload_is_not_halved(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        payload = _serialize(AccumulationState())
        payload["battery_cycles"] = 31.3
        assert migrate_storage(3, payload)["battery_cycles"] == pytest.approx(31.3)

    def test_migrating_twice_halves_only_once(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        once = migrate_storage(1, _v1_payload())
        twice = migrate_storage(1, once)
        assert twice["battery_cycles"] == pytest.approx(31.3)
        assert twice["battery_tracking_start_cycles"] == pytest.approx(5.0)

    def test_missing_or_bad_cycle_fields_become_zero(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        payload = _v1_payload()
        del payload["battery_cycles"]
        payload["battery_tracking_start_cycles"] = "not a number"
        migrated = migrate_storage(1, payload)
        assert migrated["battery_cycles"] == 0.0
        assert migrated["battery_tracking_start_cycles"] == 0.0

    def test_migrated_payload_loads_into_state(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        state = _deserialize(migrate_storage(1, _v1_payload()))
        assert state.battery_cycles == pytest.approx(31.3)
        assert state.battery_tracking_start_cycles == pytest.approx(5.0)
        assert state.today.solar_kwh == pytest.approx(7.5)

    @pytest.mark.asyncio
    async def test_store_hook_migrates_old_data(self):
        import sys
        import types
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager import accumulation

        class _BaseStore:
            def __init__(self, hass, version, key):
                self.version = version
                self.key = key

        storage_mod = types.ModuleType("homeassistant.helpers.storage")
        storage_mod.Store = _BaseStore
        saved = {name: sys.modules.get(name) for name in ("homeassistant.helpers.storage",)}
        sys.modules["homeassistant.helpers.storage"] = storage_mod
        try:
            store = accumulation._create_store(MagicMock())
            migrated = await store._async_migrate_func(1, 1, _v1_payload())
        finally:
            if saved["homeassistant.helpers.storage"] is None:
                del sys.modules["homeassistant.helpers.storage"]
            else:
                sys.modules["homeassistant.helpers.storage"] = saved["homeassistant.helpers.storage"]

        assert store.version == 3
        assert migrated["battery_cycles"] == pytest.approx(31.3)


def _v2_payload(ratio_history: list) -> dict:
    """A version 2 payload whose accuracy figures came from the blended forecast."""
    payload = _serialize(AccumulationState())
    payload["version"] = 2
    payload["yesterday_forecast_accuracy_pct"] = 19.0
    payload["forecast_accuracy_history"] = [19.0, 22.0, 131.0]
    payload["forecast_ratio_history"] = ratio_history
    return payload


def _ratio(forecast: float, actual: float) -> dict:
    return {"forecast": forecast, "actual": actual, "clipped": False}


class TestForecastAccuracyMigration:
    """Version 3 rebuilds the accuracy history from the raw forecast and actual of each day."""

    def test_history_is_rebuilt_from_the_ratio_history(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        payload = _v2_payload([_ratio(10.0, 8.0), _ratio(7.54, 6.64)])
        migrated = migrate_storage(2, payload)
        assert migrated["forecast_accuracy_history"] == [80.0, 88.1]
        assert migrated["yesterday_forecast_accuracy_pct"] == pytest.approx(88.1)
        assert migrated["version"] == 3

    def test_old_blended_figures_are_not_kept(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        migrated = migrate_storage(2, _v2_payload([_ratio(10.0, 9.0)]))
        assert 19.0 not in migrated["forecast_accuracy_history"]
        assert migrated["yesterday_forecast_accuracy_pct"] == pytest.approx(90.0)

    def test_no_ratio_history_starts_the_accuracy_fresh(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        migrated = migrate_storage(2, _v2_payload([]))
        assert migrated["forecast_accuracy_history"] == []
        assert migrated["yesterday_forecast_accuracy_pct"] == 0.0

    def test_only_the_last_seven_days_are_kept(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        records = [_ratio(10.0, float(kwh)) for kwh in range(1, 11)]
        migrated = migrate_storage(2, _v2_payload(records))
        assert migrated["forecast_accuracy_history"] == [40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]

    def test_days_without_solar_or_forecast_and_unreadable_records_are_skipped(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        records = [_ratio(10.0, 0.0), _ratio(0.0, 5.0), {"forecast": "x"}, "junk", _ratio(10.0, 9.0)]
        migrated = migrate_storage(2, _v2_payload(records))
        assert migrated["forecast_accuracy_history"] == [90.0]

    def test_accuracy_is_capped_at_200(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        migrated = migrate_storage(2, _v2_payload([_ratio(2.0, 9.0)]))
        assert migrated["forecast_accuracy_history"] == [200.0]

    def test_a_version_3_payload_keeps_its_accuracy_history(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        payload = _v2_payload([_ratio(10.0, 8.0)])
        payload["version"] = 3
        assert migrate_storage(2, payload)["forecast_accuracy_history"] == [19.0, 22.0, 131.0]

    def test_migrating_twice_gives_the_same_result(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        once = migrate_storage(2, _v2_payload([_ratio(10.0, 8.0)]))
        assert migrate_storage(2, once) == once

    def test_version_1_payload_gets_both_migrations(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        payload = _v1_payload()
        payload["forecast_ratio_history"] = [_ratio(10.0, 8.0)]
        payload["forecast_accuracy_history"] = [19.0]
        migrated = migrate_storage(1, payload)
        assert migrated["battery_cycles"] == pytest.approx(31.3)
        assert migrated["forecast_accuracy_history"] == [80.0]
        assert migrated["version"] == 3

    def test_migrated_payload_loads_into_state(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        state = _deserialize(migrate_storage(2, _v2_payload([_ratio(7.54, 6.64)])))
        assert state.yesterday_forecast_accuracy_pct == pytest.approx(88.1)
        assert state.forecast_accuracy_history == [88.1]


# ── Register write count persistence ──────────────────────────────────────────


class TestRegisterWriteCountPersistence:
    def test_defaults_to_zero(self):
        assert AccumulationState().register_write_count == 0

    def test_round_trips_through_serialisation(self):
        state = AccumulationState()
        state.register_write_count = 4321
        assert _deserialize(_serialize(state)).register_write_count == 4321

    def test_payload_without_the_field_loads_as_zero(self):
        payload = _serialize(AccumulationState())
        del payload["register_write_count"]
        assert _deserialize(payload).register_write_count == 0

    def test_version_1_payload_loads_as_zero(self):
        from custom_components.givenergy_inverter_manager.accumulation import migrate_storage

        payload = _v1_payload()
        del payload["register_write_count"]
        migrated = migrate_storage(1, payload)
        assert migrated["register_write_count"] == 0
        assert _deserialize(migrated).register_write_count == 0

    @pytest.mark.parametrize("bad", ["many", None, -5])
    def test_bad_values_load_as_zero_without_losing_other_state(self, bad):
        payload = _serialize(AccumulationState())
        payload["register_write_count"] = bad
        payload["today"]["solar_kwh"] = 3.0
        state = _deserialize(payload)
        assert state.register_write_count == 0
        assert state.today.solar_kwh == pytest.approx(3.0)


class TestRegisterWriteLogPersistence:
    @staticmethod
    def _entry(n: int) -> dict:
        return {
            "time": f"2026-10-07T01:{n:02d}:00+01:00",
            "entity_id": "number.target_soc",
            "value": str(n),
            "reason": "charge target",
        }

    def test_defaults_to_empty(self):
        assert AccumulationState().register_write_log == []

    def test_round_trips_through_serialisation(self):
        state = AccumulationState()
        state.register_write_log = [self._entry(1), {**self._entry(2), "reason": "external",
                                                     "user_id": "u", "parent_id": "p"}]
        assert _deserialize(_serialize(state)).register_write_log == state.register_write_log

    def test_payload_without_the_field_loads_empty(self):
        payload = _serialize(AccumulationState())
        del payload["register_write_log"]
        assert _deserialize(payload).register_write_log == []

    def test_a_stored_log_longer_than_the_bound_loads_trimmed_to_the_newest(self):
        from custom_components.givenergy_inverter_manager.const import (
            REGISTER_WRITE_LOG_MAX_ENTRIES,
        )

        state = AccumulationState()
        state.register_write_log = [self._entry(n) for n in range(REGISTER_WRITE_LOG_MAX_ENTRIES + 7)]
        loaded = _deserialize(_serialize(state)).register_write_log
        assert len(loaded) == REGISTER_WRITE_LOG_MAX_ENTRIES
        assert loaded[-1] == state.register_write_log[-1]

    def test_a_damaged_log_loads_empty_without_losing_other_state(self):
        payload = _serialize(AccumulationState())
        payload["register_write_log"] = "not a list"
        payload["today"]["solar_kwh"] = 3.0
        state = _deserialize(payload)
        assert state.register_write_log == []
        assert state.today.solar_kwh == pytest.approx(3.0)

