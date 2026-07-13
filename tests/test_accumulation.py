"""
test_accumulation.py — Unit tests for multi-period energy accumulation.

All tests are pure Python — AccumulationStore is not instantiated (it requires HA
Storage), but AccumulationState, the serialisation helpers, and on_midnight logic
are all testable without HA.
"""

from __future__ import annotations

from datetime import datetime, timezone

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

    if state.today_forecast_kwh > 0:
        actual = state.today.solar_kwh
        accuracy = min(200.0, round(actual / state.today_forecast_kwh * 100, 1))
        state.yesterday_forecast_accuracy_pct = accuracy
        history = state.forecast_accuracy_history[-6:]
        history.append(accuracy)
        state.forecast_accuracy_history = history

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


class TestForecastAccuracy:
    def test_accuracy_calculated_at_midnight(self):
        state = AccumulationState()
        state.today_forecast_kwh = 10.0
        state.today.solar_kwh = 8.5
        _midnight_reset(state, _tuesday())
        assert state.yesterday_forecast_accuracy_pct == pytest.approx(85.0, rel=0.01)

    def test_perfect_forecast_gives_100_pct(self):
        state = AccumulationState()
        state.today_forecast_kwh = 10.0
        state.today.solar_kwh = 10.0
        _midnight_reset(state, _tuesday())
        assert state.yesterday_forecast_accuracy_pct == pytest.approx(100.0, rel=0.01)

    def test_accuracy_capped_at_200_pct(self):
        state = AccumulationState()
        state.today_forecast_kwh = 5.0
        state.today.solar_kwh = 20.0  # way above forecast
        _midnight_reset(state, _tuesday())
        assert state.yesterday_forecast_accuracy_pct == 200.0

    def test_no_accuracy_calculated_when_no_forecast(self):
        state = AccumulationState()
        state.today_forecast_kwh = 0.0
        state.today.solar_kwh = 8.0
        _midnight_reset(state, _tuesday())
        assert state.yesterday_forecast_accuracy_pct == 0.0

    def test_history_accumulates_over_days(self):
        state = AccumulationState()
        for kwh in [8.0, 9.0, 10.0]:
            state.today_forecast_kwh = 10.0
            state.today.solar_kwh = kwh
            _midnight_reset(state, _tuesday())
        assert len(state.forecast_accuracy_history) == 3

    def test_history_capped_at_7_days(self):
        state = AccumulationState()
        for _ in range(10):
            state.today_forecast_kwh = 10.0
            state.today.solar_kwh = 9.0
            _midnight_reset(state, _tuesday())
        assert len(state.forecast_accuracy_history) <= 7

    def test_forecast_cleared_at_midnight(self):
        state = AccumulationState()
        state.today_forecast_kwh = 10.0
        _midnight_reset(state, _tuesday())
        assert state.today_forecast_kwh == 0.0


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

        from custom_components.givenergy_inverter_manager.core.engine import (
            RawSensorValues,
            accumulate_energy,
        )
        from custom_components.givenergy_inverter_manager.core.tariff import build_tariff
        from tests.conftest import _nightboost_cfg

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

    def test_records_forecast_accuracy_when_forecast_positive(self):
        from datetime import datetime, timezone

        store = self._store()
        store.state.today_forecast_kwh = 10.0
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
