"""Persisted per-slot load history and raw forecast accuracy history in AccumulationStore."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from custom_components.givenergy_inverter_manager.accumulation import (
    AccumulationState,
    AccumulationStore,
    _deserialize,
    _serialize,
)


def _store() -> AccumulationStore:
    store = AccumulationStore.__new__(AccumulationStore)
    store._store = MagicMock()
    store._bill_start_day = 16
    store.state = AccumulationState()
    return store


def _at(day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 6, day, hour, minute, tzinfo=timezone.utc)


def _fill_day(store: AccumulationStore, day: int, per_slot_kwh: float, slots=range(48)) -> None:
    for slot in slots:
        store.record_slot_load(_at(day, slot // 2, (slot % 2) * 30), slot, per_slot_kwh, 0.5)


class TestSlotLoadHistory:
    def test_full_day_archived_at_midnight_with_full_coverage(self):
        store = _store()
        _fill_day(store, 15, 0.4)
        store.on_midnight(_at(16, 0, 0))
        entry = store.state.slot_load_history[0]
        assert entry["date"] == "2026-06-15"
        assert entry["coverage"] == pytest.approx(1.0)
        assert entry["slots"] == pytest.approx([0.4] * 48)
        assert store.state.slot_load_today == [0.0] * 48

    def test_partial_day_after_restart_has_low_coverage_and_is_not_in_profile(self):
        store = _store()
        _fill_day(store, 15, 0.4)
        store.on_midnight(_at(16, 0, 0))
        _fill_day(store, 16, 0.4)
        store.on_midnight(_at(17, 0, 0))
        _fill_day(store, 17, 5.0, slots=range(30, 48))
        store.on_midnight(_at(18, 0, 0))
        assert store.state.slot_load_history[-1]["coverage"] == pytest.approx(18 / 48)
        profile = store.slot_load_profile(0)
        assert profile == pytest.approx([0.4] * 48)

    def test_profile_none_with_fewer_than_two_complete_days(self):
        store = _store()
        _fill_day(store, 15, 0.4)
        store.on_midnight(_at(16, 0, 0))
        assert store.slot_load_profile(0) is None

    def test_gap_longer_than_a_slot_is_not_recorded(self):
        store = _store()
        store.record_slot_load(_at(15, 3), 6, 9.9, 1.2)
        assert store.state.slot_load_today[6] == 0.0
        assert store.state.slot_load_date == ""

    def test_missed_midnight_archives_previous_day_on_next_record(self):
        store = _store()
        _fill_day(store, 15, 0.4)
        store.record_slot_load(_at(16, 8), 16, 0.3, 0.5)
        assert [e["date"] for e in store.state.slot_load_history] == ["2026-06-15"]
        assert store.state.slot_load_today[16] == pytest.approx(0.3)
        assert store.state.slot_load_date == "2026-06-16"

    def test_midnight_after_early_rotation_does_not_archive_new_day(self):
        store = _store()
        _fill_day(store, 15, 0.4)
        store.record_slot_load(_at(16, 0, 1), 0, 0.01, 0.01)
        store.on_midnight(_at(16, 0, 0))
        assert [e["date"] for e in store.state.slot_load_history] == ["2026-06-15"]

    def test_history_capped_at_28_days(self):
        store = _store()
        for n in range(30):
            store.record_slot_load(datetime(2026, 5, 1 + n % 28, 12, tzinfo=timezone.utc), 24, 0.4, 0.5)
            store.state.slot_load_date = f"2026-05-{1 + n % 28:02d}"
            store._archive_slot_day()
        assert len(store.state.slot_load_history) == 28

    def test_survives_save_and_load(self):
        store = _store()
        _fill_day(store, 15, 0.4)
        store.on_midnight(_at(16, 0, 0))
        _fill_day(store, 16, 0.2, slots=range(10))
        restored = _deserialize(_serialize(store.state))
        assert restored.slot_load_history == store.state.slot_load_history
        assert restored.slot_load_today == store.state.slot_load_today
        assert restored.slot_hours_today == store.state.slot_hours_today
        assert restored.slot_load_date == "2026-06-16"

    def test_old_storage_without_new_keys_loads_with_defaults(self):
        state = _deserialize({"today_forecast_kwh": 3.0})
        assert state.slot_load_history == []
        assert state.slot_load_today == [0.0] * 48
        assert state.forecast_ratio_history == []
        assert state.today_raw_forecast_kwh == 0.0

    def test_malformed_slot_arrays_reset_to_defaults(self):
        state = _deserialize({"slot_load_today": [1.0, 2.0], "slot_hours_today": "x"})
        assert state.slot_load_today == [0.0] * 48
        assert state.slot_hours_today == [0.0] * 48


class TestRawForecastHistory:
    def _day(self, store, day, raw_forecast_tomorrow, solar_kwh, clipping=False):
        store.on_raw_forecast(raw_forecast_tomorrow)
        store.state.today.solar_kwh = solar_kwh
        if clipping:
            store.note_clipping()
        store.on_midnight(_at(day, 0, 0))

    def test_forecast_seen_before_midnight_pairs_with_the_day_that_follows(self):
        store = _store()
        self._day(store, 16, 12.0, 0.0)  # forecast for 16th, no record yet
        assert store.state.forecast_ratio_history == []
        assert store.state.today_raw_forecast_kwh == 12.0
        self._day(store, 17, 20.0, 9.0)  # 16th finished with 9 kWh against 12 forecast
        assert store.state.forecast_ratio_history == [
            {"forecast": 12.0, "actual": 9.0, "clipped": False}
        ]

    def test_pending_forecast_is_not_reused_after_midnight(self):
        store = _store()
        self._day(store, 16, 12.0, 0.0)
        self._day(store, 17, None, 9.0)  # sensor unavailable on the 16th
        self._day(store, 18, None, 9.0)
        assert len(store.state.forecast_ratio_history) == 1

    def test_clipping_flag_recorded_and_cleared(self):
        store = _store()
        self._day(store, 16, 12.0, 0.0)
        self._day(store, 17, 12.0, 9.0, clipping=True)
        self._day(store, 18, 12.0, 9.0)
        assert [r["clipped"] for r in store.state.forecast_ratio_history] == [True, False]

    def test_zero_and_none_forecast_ignored(self):
        store = _store()
        store.on_raw_forecast(0.0)
        store.on_raw_forecast(None)
        assert store.state.pending_raw_forecast_kwh == 0.0

    def test_p10_forecast_follows_the_same_path_as_the_p50(self):
        store = _store()
        store.on_raw_forecast(12.0, 4.0)
        assert store.today_raw_forecast_p10_kwh is None
        store.on_midnight(_at(16, 0, 0))
        assert store.today_raw_forecast_kwh == 12.0
        assert store.today_raw_forecast_p10_kwh == 4.0
        assert store.state.pending_raw_forecast_p10_kwh == 0.0

    def test_missing_p10_keeps_the_last_good_value(self):
        store = _store()
        store.on_raw_forecast(12.0, 4.0)
        store.on_raw_forecast(12.0, None)
        store.on_raw_forecast(12.0, 0.0)
        assert store.state.pending_raw_forecast_p10_kwh == 4.0

    def test_today_forecast_is_none_until_one_is_remembered(self):
        assert _store().today_raw_forecast_kwh is None

    def test_a_forecast_that_arrives_after_midnight_belongs_to_tomorrow(self):
        """A forecast first seen at 06:00 leaves today without a provider forecast."""
        store = _store()
        store.on_midnight(_at(16, 0, 0))  # no forecast seen before midnight
        store.on_raw_forecast(30.0)  # the sensor wakes up at 06:00 and reports tomorrow
        assert store.today_raw_forecast_kwh is None
        store.on_midnight(_at(17, 0, 0))
        assert store.today_raw_forecast_kwh == 30.0

    def test_correction_factor_needs_five_usable_days(self):
        store = _store()
        self._day(store, 10, 10.0, 0.0)
        for day in range(11, 15):
            self._day(store, day, 10.0, 8.0)
        assert store.forecast_correction_factor is None
        self._day(store, 15, 10.0, 8.0)
        assert store.forecast_correction_factor == pytest.approx(0.8)

    def test_history_capped_at_14_days(self):
        store = _store()
        for day in range(1, 25):
            self._day(store, day, 10.0, 8.0)
        assert len(store.state.forecast_ratio_history) == 14

    def test_survives_save_and_load(self):
        store = _store()
        self._day(store, 16, 12.0, 0.0)
        self._day(store, 17, 12.0, 9.0)
        store.on_raw_forecast(7.0)
        store.note_clipping()
        restored = _deserialize(_serialize(store.state))
        assert restored.forecast_ratio_history == store.state.forecast_ratio_history
        assert restored.pending_raw_forecast_kwh == 7.0
        assert restored.today_raw_forecast_kwh == 12.0
        assert restored.today_clipping is True

    def test_p10_forecast_survives_save_and_load(self):
        store = _store()
        store.on_raw_forecast(12.0, 4.0)
        store.on_midnight(_at(16, 0, 0))
        store.on_raw_forecast(9.0, 3.0)
        restored = _deserialize(_serialize(store.state))
        assert restored.today_raw_forecast_p10_kwh == 4.0
        assert restored.pending_raw_forecast_p10_kwh == 3.0

    def test_state_default_is_independent_per_instance(self):
        a, b = AccumulationState(), AccumulationState()
        a.slot_load_today[0] = 1.0
        assert b.slot_load_today[0] == 0.0
