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
