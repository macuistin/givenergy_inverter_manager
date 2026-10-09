"""The record of the immersion's grid heating in the stored accumulation data.

It is read with .get, so no storage version bump is needed: data saved before the record
existed loads with an empty one, and an install without an oil price never stores the key.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.givenergy_inverter_manager.accumulation import (
    _STORAGE_VERSION,
    AccumulationState,
    AccumulationStore,
    _deserialize,
    _serialize,
)

KEY = "immersion_heat_history"


def _store(saved: dict) -> AccumulationStore:
    """A store whose storage is the *saved* dict, so a second store reads what the first saved."""
    store = AccumulationStore.__new__(AccumulationStore)
    ha_store = MagicMock()
    ha_store.async_save = AsyncMock(side_effect=lambda data: saved.__setitem__("data", data))
    ha_store.async_load = AsyncMock(side_effect=lambda: saved.get("data"))
    store._store = ha_store
    store._bill_start_day = 1
    store.state = AccumulationState()
    return store


class TestWhatIsStored:
    def test_an_install_with_no_record_stores_no_key(self):
        assert KEY not in _serialize(AccumulationState())

    def test_a_record_is_stored_under_its_key(self):
        state = AccumulationState()
        state.immersion_heat_log.add(datetime(2026, 12, 15, 13, 5), 0.5, 0.15)
        stored = _serialize(state)[KEY]
        assert stored[0]["date"] == "2026-12-15"
        assert stored[0]["kwh"][13] == pytest.approx(0.5)
        assert stored[0]["cost"][13] == pytest.approx(0.15)

    def test_data_saved_before_the_record_existed_loads_with_an_empty_one(self):
        payload = _serialize(AccumulationState())
        payload.pop(KEY, None)
        assert _deserialize(payload).immersion_heat_log.days == []

    def test_the_storage_version_is_unchanged(self):
        assert _STORAGE_VERSION == 4

    def test_a_damaged_record_loads_empty_and_the_rest_still_loads(self):
        payload = _serialize(AccumulationState())
        payload["today"] = {"solar_kwh": 3.0}
        payload[KEY] = "damaged"
        state = _deserialize(payload)
        assert state.immersion_heat_log.days == []
        assert state.today.solar_kwh == pytest.approx(3.0)

    def test_the_serialised_form_survives_a_second_round_trip(self):
        state = AccumulationState()
        for day in range(1, 20):
            state.immersion_heat_log.add(datetime(2026, 12, day, 13), 1.0, 0.3)
        once = _serialize(state)
        assert _serialize(_deserialize(once)) == once


class TestAcrossARestart:
    def test_the_record_is_read_back_from_storage(self):
        saved: dict = {}
        before = _store(saved)
        for day in range(8, 15):
            before.immersion_heat_log.add(datetime(2026, 12, day, 13, 10), 1.5, 0.45)
        before.immersion_heat_log.add(datetime(2026, 12, 15, 0, 1), 0.0, 0.0)

        asyncio.run(before.async_save())

        after = _store(saved)
        asyncio.run(after.async_load())
        assert [d.date for d in after.immersion_heat_log.days] == [
            f"2026-12-{day:02d}" for day in range(8, 16)
        ]
        assert after.immersion_heat_log.days[0].kwh[13] == pytest.approx(1.5)
        assert after.immersion_heat_log.days[0].cost[13] == pytest.approx(0.45)

    def test_a_restart_does_not_lose_the_day_in_progress(self):
        saved: dict = {}
        before = _store(saved)
        before.immersion_heat_log.add(datetime(2026, 12, 15, 9, 0), 0.7, 0.21)

        asyncio.run(before.async_save())
        after = _store(saved)
        asyncio.run(after.async_load())
        after.immersion_heat_log.add(datetime(2026, 12, 15, 9, 30), 0.3, 0.09)
        assert after.immersion_heat_log.days[0].kwh[9] == pytest.approx(1.0)

    def test_the_store_exposes_the_record_it_holds(self):
        store = _store({})
        assert store.immersion_heat_log is store.state.immersion_heat_log
