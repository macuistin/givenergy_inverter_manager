"""The EV charging sessions in the stored accumulation data.

They are read with .get, so no storage version bump is needed: data saved before the sessions
existed loads with an empty log, and an install that never plugs a car in never stores the key.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.givenergy_inverter_manager.accumulation import (
    _STORAGE_VERSION,
    AccumulationState,
    AccumulationStore,
    _deserialize,
    _serialize,
)
from custom_components.givenergy_inverter_manager.core.ev_session import (
    EVSessionStep,
    track_session,
)
from custom_components.givenergy_inverter_manager.discovery import EVChargerState

KEY = "ev_sessions"
START = datetime(2031, 10, 15, 23, 10, tzinfo=timezone.utc)


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


def _plug_in_and_charge(log, kwh: float, cost: float) -> None:
    track_session(log, EVSessionStep(START, EVChargerState.CONNECTED))
    later = START + timedelta(hours=1)
    track_session(log, EVSessionStep(later, EVChargerState.CHARGING, kwh, cost))


class TestWhatIsStored:
    def test_an_install_with_no_session_stores_no_key(self):
        assert KEY not in _serialize(AccumulationState())

    def test_a_running_session_is_stored_under_its_key(self):
        state = AccumulationState()
        _plug_in_and_charge(state.ev_sessions, 4.0, 0.4)
        stored = _serialize(state)[KEY]
        assert stored["current"]["start"] == START.isoformat()
        assert stored["current"]["energy_kwh"] == pytest.approx(4.0)
        assert stored["plugged_in"] is True

    def test_data_saved_before_the_sessions_existed_loads_with_an_empty_log(self):
        payload = _serialize(AccumulationState())
        payload.pop(KEY, None)
        assert _deserialize(payload).ev_sessions.is_empty

    def test_the_storage_version_is_unchanged(self):
        assert _STORAGE_VERSION == 4

    def test_a_damaged_log_loads_empty_and_the_rest_still_loads(self):
        payload = _serialize(AccumulationState())
        payload["today"] = {"solar_kwh": 3.0}
        payload[KEY] = "damaged"
        state = _deserialize(payload)
        assert state.ev_sessions.is_empty
        assert state.today.solar_kwh == pytest.approx(3.0)


class TestAcrossARestart:
    def test_the_running_session_and_the_list_come_back(self):
        saved: dict = {}
        before = _store(saved)
        log = before.ev_sessions
        _plug_in_and_charge(log, 7.0, 0.7)
        track_session(log, EVSessionStep(START + timedelta(hours=2), EVChargerState.DISCONNECTED))
        _plug_in_and_charge(log, 2.0, 0.3)

        asyncio.run(before.async_save())
        after = _store(saved)
        asyncio.run(after.async_load())

        assert after.ev_sessions == log
        assert after.ev_sessions.current.energy_kwh == pytest.approx(2.0)
        assert after.ev_sessions.recent[0].cost == pytest.approx(0.7)

    def test_a_session_restored_while_plugged_in_keeps_counting(self):
        saved: dict = {}
        before = _store(saved)
        _plug_in_and_charge(before.ev_sessions, 3.0, 0.3)
        asyncio.run(before.async_save())

        after = _store(saved)
        asyncio.run(after.async_load())
        later = START + timedelta(hours=3)
        track_session(after.ev_sessions, EVSessionStep(later, EVChargerState.CHARGING, 1.0, 0.1))
        assert after.ev_sessions.current.start == START
        assert after.ev_sessions.current.energy_kwh == pytest.approx(4.0)

    def test_the_store_exposes_the_log_it_holds(self):
        store = _store({})
        assert store.ev_sessions is store.state.ev_sessions
