"""The recorder glue that seeds the forecast accuracy history, with the recorder faked.

tests/ha_e2e/test_forecast_seeding_e2e.py runs the same flow against a real recorder.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager import forecast_seeding
from custom_components.givenergy_inverter_manager.accumulation import (
    AccumulationState,
    AccumulationStore,
)
from custom_components.givenergy_inverter_manager.const import CONF_FORECAST_ENTITY
from custom_components.givenergy_inverter_manager.core.forecast_seeding import (
    Reading,
    query_start,
)
from custom_components.givenergy_inverter_manager.forecast_seeding import (
    async_recorded_readings,
    async_seed_forecast_accuracy,
)
from tests.test_coordinator import FakeCoordinator, _cfg, _MemoryStore

DUBLIN = ZoneInfo("Europe/Dublin")
NOW = datetime(2026, 6, 15, 9, 30, tzinfo=DUBLIN)
FORECAST = "sensor.solcast_pv_forecast_forecast_tomorrow"
SOLAR = "sensor.givtcp_fd2309f069_pv_energy_today_kwh"


def _store() -> AccumulationStore:
    store = AccumulationStore.__new__(AccumulationStore)
    store.state = AccumulationState()
    store._bill_start_day = 1
    store._store = _MemoryStore()
    return store


def _at(days_ago: int, hour: int, minute: int = 0) -> datetime:
    day = NOW.date() - timedelta(days=days_ago)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=DUBLIN)


def _recorded(days: int, forecast: float = 20.0, actual: float = 14.0) -> dict[str, list[Reading]]:
    """The recorder's view of `days` finished days: a forecast each evening, a solar total."""
    return {
        FORECAST: [Reading(_at(n + 2, 23, 50), forecast) for n in range(days)],
        SOLAR: [Reading(_at(n, 21), actual) for n in range(1, days + 1)],
    }


def _fake_recorder(monkeypatch, result=None, error: Exception | None = None) -> list[tuple]:
    """Replace the recorder query, returning the list of calls it receives."""
    calls: list[tuple] = []

    async def fake(hass, entity_ids, start, end):
        calls.append((entity_ids, start, end))
        if error is not None:
            raise error
        return result if result is not None else {}

    monkeypatch.setitem(async_seed_forecast_accuracy.__globals__, "async_recorded_readings", fake)
    return calls


async def _seed(store: AccumulationStore, sources=(FORECAST, SOLAR)) -> int:
    return await async_seed_forecast_accuracy(MagicMock(), store, sources, NOW)


class TestSeeding:
    async def test_an_empty_history_is_filled_from_the_recorded_days(self, monkeypatch):
        _fake_recorder(monkeypatch, _recorded(9))
        store = _store()

        added = await _seed(store)

        assert added == 9
        assert store.state.forecast_ratio_history == [
            {"forecast": 20.0, "actual": 14.0, "clipped": False}
        ] * 9

    async def test_seeded_days_apply_the_correction_straight_away(self, monkeypatch):
        _fake_recorder(monkeypatch, _recorded(9))
        store = _store()

        await _seed(store)

        assert store.forecast_accuracy.status == "Applied: x0.70 from 9 usable days"
        assert store.forecast_correction_factor == pytest.approx(0.7)

    async def test_the_query_covers_the_last_fourteen_days_for_both_sensors(self, monkeypatch):
        calls = _fake_recorder(monkeypatch, _recorded(3))

        await _seed(_store())

        (entity_ids, start, end), = calls
        assert entity_ids == [FORECAST, SOLAR]
        assert start == query_start(NOW.date(), 14, DUBLIN)
        assert end == NOW

    async def test_no_more_than_the_stored_history_length_is_kept(self, monkeypatch):
        _fake_recorder(monkeypatch, _recorded(20))
        store = _store()

        await _seed(store)

        assert len(store.state.forecast_ratio_history) <= 14

    async def test_a_history_that_already_holds_a_night_is_left_alone(self, monkeypatch):
        calls = _fake_recorder(monkeypatch, _recorded(9))
        store = _store()
        kept = [{"forecast": 10.0, "actual": 9.0, "clipped": True}]
        store.state.forecast_ratio_history = list(kept)

        added = await _seed(store)

        assert added == 0
        assert store.state.forecast_ratio_history == kept
        assert calls == []

    async def test_a_night_recorded_while_the_query_ran_is_not_overwritten(self, monkeypatch):
        store = _store()
        night = [{"forecast": 11.0, "actual": 8.0, "clipped": False}]

        async def slow_recorder(hass, entity_ids, start, end):
            store.state.forecast_ratio_history = list(night)  # midnight ran meanwhile
            return _recorded(9)

        monkeypatch.setitem(
            async_seed_forecast_accuracy.__globals__, "async_recorded_readings", slow_recorder
        )

        assert await _seed(store) == 0
        assert store.state.forecast_ratio_history == night

    @pytest.mark.parametrize("sources", [(None, SOLAR), (FORECAST, None), (None, None), ("", SOLAR)])
    async def test_a_missing_sensor_means_nothing_is_queried(self, monkeypatch, sources):
        calls = _fake_recorder(monkeypatch, _recorded(9))
        store = _store()

        assert await _seed(store, sources) == 0
        assert calls == []
        assert store.state.forecast_ratio_history == []

    async def test_a_recorder_with_no_history_leaves_the_history_empty(self, monkeypatch):
        _fake_recorder(monkeypatch, {})
        store = _store()

        assert await _seed(store) == 0
        assert store.state.forecast_ratio_history == []

    async def test_a_failing_recorder_is_swallowed(self, monkeypatch):
        _fake_recorder(monkeypatch, error=RuntimeError("database is locked"))
        store = _store()

        assert await _seed(store) == 0
        assert store.state.forecast_ratio_history == []

    async def test_a_naive_clock_is_refused_not_guessed(self, monkeypatch):
        calls = _fake_recorder(monkeypatch, _recorded(9))

        added = await async_seed_forecast_accuracy(
            MagicMock(), _store(), (FORECAST, SOLAR), NOW.replace(tzinfo=None)
        )

        assert added == 0
        assert calls == []


class TestRecorderAccess:
    async def test_without_the_recorder_nothing_is_read(self):
        hass = MagicMock()
        hass.config.components = {"sensor"}

        assert await async_recorded_readings(hass, [FORECAST], NOW, NOW) == {}

    def test_only_numeric_states_become_readings(self):
        states = [
            SimpleNamespace(state="14.2", last_updated=_at(1, 23)),
            SimpleNamespace(state="unavailable", last_updated=_at(1, 22)),
            SimpleNamespace(state="unknown", last_updated=_at(1, 21)),
            SimpleNamespace(state="", last_updated=_at(1, 20)),
            SimpleNamespace(state="nan", last_updated=_at(1, 19)),
            SimpleNamespace(state="inf", last_updated=_at(1, 18)),
            SimpleNamespace(state="sunny", last_updated=_at(1, 17)),
            SimpleNamespace(state="0", last_updated=_at(1, 16)),
        ]

        assert forecast_seeding._readings(states) == [
            Reading(_at(1, 23), 14.2),
            Reading(_at(1, 16), 0.0),
        ]


class TestCoordinatorWiring:
    """The coordinator starts seeding only on an install that has nothing stored."""

    def _coord(self, **cfg) -> FakeCoordinator:
        coord = FakeCoordinator(cfg=_cfg(**cfg))
        coord._acc = _store()
        return coord

    def _started(self, coord: FakeCoordinator) -> int:
        coord._start_forecast_seeding()
        started = len(coord.tasks_created)
        for task in coord.tasks_created:
            task.close()
        return started

    def test_a_new_install_with_a_forecast_sensor_and_serial_starts_seeding(self):
        coord = self._coord(**{CONF_FORECAST_ENTITY: FORECAST, "inverter_serial": "fd2309f069"})

        assert self._started(coord) == 1

    def test_the_daily_solar_counter_comes_from_the_inverter_serial(self):
        coord = self._coord(**{CONF_FORECAST_ENTITY: FORECAST, "inverter_serial": "fd2309f069"})

        assert coord._forecast_seed_sources() == (FORECAST, SOLAR)

    def test_a_stored_history_is_not_reseeded(self):
        coord = self._coord(**{CONF_FORECAST_ENTITY: FORECAST, "inverter_serial": "fd2309f069"})
        coord._acc.state.forecast_ratio_history = [
            {"forecast": 10.0, "actual": 8.0, "clipped": False}
        ]

        assert self._started(coord) == 0

    def test_no_forecast_sensor_means_no_seeding(self):
        coord = self._coord(**{"inverter_serial": "fd2309f069"})

        assert self._started(coord) == 0

    def test_no_inverter_serial_means_no_seeding(self):
        coord = self._coord(**{CONF_FORECAST_ENTITY: FORECAST})

        assert self._started(coord) == 0

    async def test_seeded_days_are_stored_and_saved(self, monkeypatch):
        class _Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW

        monkeypatch.setitem(FakeCoordinator._seed_forecast_accuracy.__globals__, "datetime", _Clock)
        _fake_recorder(monkeypatch, _recorded(9))
        coord = self._coord(**{CONF_FORECAST_ENTITY: FORECAST, "inverter_serial": "fd2309f069"})

        await coord._seed_forecast_accuracy((FORECAST, SOLAR))

        assert len(coord._acc.state.forecast_ratio_history) == 9
        assert coord._acc._store.saves == 1

    async def test_nothing_is_saved_when_nothing_was_seeded(self, monkeypatch):
        _fake_recorder(monkeypatch, {})
        coord = self._coord(**{CONF_FORECAST_ENTITY: FORECAST, "inverter_serial": "fd2309f069"})

        await coord._seed_forecast_accuracy((FORECAST, SOLAR))

        assert coord._acc._store.saves == 0
