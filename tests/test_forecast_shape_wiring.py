"""The forecast's shape is read from the sensor, remembered with its total and used by the plan."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.givenergy_inverter_manager import sensor_values
from custom_components.givenergy_inverter_manager.accumulation import (
    AccumulationStore,
    _deserialize,
    _serialize,
)
from custom_components.givenergy_inverter_manager.core.solar_shape import SLOTS
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "forecast" / "solcast_tomorrow.json").read_text()
)
ATTRIBUTES = FIXTURE["attributes"]
ENTITY = "sensor.forecast"


def _coordinator(attributes: dict | None) -> FakeCoordinator:
    coord = FakeCoordinator(cfg=_cfg(**{"forecast_entity": ENTITY}))
    coord.set_states(_default_states())
    coord.set_state(ENTITY, "33.5765", attributes)
    return coord


def _shape(attributes: dict | None):
    coord = _coordinator(attributes)
    return coord._collect_raw(coord._effective_cfg()).forecast_shape_tomorrow


class TestReadingTheShape:
    def test_solcasts_half_hourly_attribute_gives_the_shape(self):
        shape = _shape(ATTRIBUTES)
        assert shape is not None and len(shape) == SLOTS
        assert sum(shape) == pytest.approx(1.0, abs=1e-4)

    def test_hourly_detail_alone_is_enough(self):
        shape = _shape({"detailedHourly": ATTRIBUTES["detailedHourly"]})
        assert shape is not None
        assert shape[24] == pytest.approx(shape[25])

    def test_the_half_hourly_attribute_is_preferred_when_both_are_there(self):
        both = _shape(ATTRIBUTES)
        half_only = _shape({"detailedForecast": ATTRIBUTES["detailedForecast"]})
        assert both == half_only

    def test_a_sensor_with_totals_only_has_no_shape(self):
        # Forecast.Solar's tomorrow sensor, and a Solcast with both detail attributes switched off.
        assert _shape({"estimate10": 11.9}) is None
        assert _shape(None) is None

    def test_a_damaged_attribute_is_no_shape_and_does_not_raise(self):
        assert _shape({"detailedForecast": "not a list"}) is None
        assert _shape({"detailedForecast": [{"period_start": 1}] * 48}) is None

    def test_a_damaged_half_hourly_attribute_falls_back_to_the_hourly_one(self):
        shape = _shape({"detailedForecast": "bad", "detailedHourly": ATTRIBUTES["detailedHourly"]})
        assert shape is not None

    def test_no_forecast_sensor_means_no_shape(self):
        coord = FakeCoordinator(cfg=_cfg())
        assert coord._collect_raw(coord._effective_cfg()).forecast_shape_tomorrow is None


def _store() -> AccumulationStore:
    store = AccumulationStore.__new__(AccumulationStore)
    store._store = MagicMock()
    store._bill_start_day = 1
    store.state = _deserialize({})
    return store


SHAPE = (1 / 24,) * 12 + (0.0,) * 24 + (1 / 24,) * 12


class TestRememberingIt:
    def test_the_shape_is_kept_with_the_total_and_becomes_todays_at_midnight(self):
        store = _store()
        store.on_raw_forecast(14.0, 9.0, SHAPE)
        assert store.today_raw_forecast_shape is None  # not today's yet

        store.on_midnight(datetime(2031, 6, 16, tzinfo=timezone.utc))

        assert store.today_raw_forecast_kwh == 14.0
        assert store.today_raw_forecast_shape == pytest.approx(SHAPE)

    def test_a_total_that_arrives_without_a_shape_clears_the_old_shape(self):
        store = _store()
        store.on_raw_forecast(14.0, None, SHAPE)
        store.on_raw_forecast(15.0, None, None)
        store.on_midnight(datetime(2031, 6, 16, tzinfo=timezone.utc))
        assert store.today_raw_forecast_shape is None

    def test_a_reading_with_no_total_leaves_the_shape_alone(self):
        store = _store()
        store.on_raw_forecast(14.0, None, SHAPE)
        store.on_raw_forecast(None, None, None)
        store.on_midnight(datetime(2031, 6, 16, tzinfo=timezone.utc))
        assert store.today_raw_forecast_shape == pytest.approx(SHAPE)

    def test_it_survives_a_save_and_a_restart(self):
        store = _store()
        store.on_raw_forecast(14.0, None, SHAPE)
        store.on_midnight(datetime(2031, 6, 16, tzinfo=timezone.utc))
        store.on_raw_forecast(16.0, None, SHAPE)

        restored = _deserialize(json.loads(json.dumps(_serialize(store.state))))

        assert restored.today_raw_forecast_shape == pytest.approx(list(SHAPE))
        assert restored.pending_raw_forecast_shape == pytest.approx(list(SHAPE))

    @pytest.mark.parametrize("bad", [None, "x", [1, 2, 3], [0.0] * 48, [-1.0] * 48])
    def test_a_stored_shape_that_is_not_one_loads_as_none(self, bad):
        restored = _deserialize({"today_raw_forecast_shape": bad, "pending_raw_forecast_shape": bad})
        assert restored.today_raw_forecast_shape == []
        assert restored.pending_raw_forecast_shape == []

    def test_a_store_from_before_shapes_loads_with_none(self):
        assert _deserialize({"today_raw_forecast_kwh": 5.0}).today_raw_forecast_shape == []


class TestTheSensorAttribute:
    @pytest.mark.parametrize(("used", "source"), [(True, "forecast"), (False, "standard curve")])
    def test_it_says_which_profile_the_plan_used(self, used, source):
        data = MagicMock(solar_shape_used=used)
        assert sensor_values.solar_forecast_attributes(data) == {"solar_profile_source": source}


class TestThePlanUsesTheRememberedShapeBeforeSunrise:
    """From midnight to 08:00 the sensors report the next day, so the plan reads the memory."""

    async def _plan(self, monkeypatch, hour: int, *, shape, live_attributes):
        now = datetime(2031, 6, 15, hour, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(FakeCoordinator, "_now", staticmethod(lambda: now))
        coord = _coordinator(live_attributes)
        coord._acc.state.today_raw_forecast_kwh = 14.0
        coord._acc.state.today_raw_forecast_shape = list(shape or ())
        return await coord.run_cycle()

    async def test_at_three_in_the_morning_the_remembered_shape_is_used(self, monkeypatch):
        west = [0.0] * 30 + [0.1] * 10 + [0.0] * 8  # the sun arrives in the afternoon
        data = await self._plan(monkeypatch, 3, shape=west, live_attributes={})
        assert data.solar_shape_used is True
        assert "Solar follows your forecast's shape." in data.charge_decision.reason

    async def test_the_live_sensor_shape_is_for_the_next_day_so_it_is_not_used_then(
        self, monkeypatch
    ):
        data = await self._plan(monkeypatch, 3, shape=None, live_attributes=ATTRIBUTES)
        assert data.solar_shape_used is False
        assert "forecast's shape" not in data.charge_decision.reason

    async def test_after_sunrise_the_live_sensor_shape_is_used(self, monkeypatch):
        data = await self._plan(monkeypatch, 20, shape=None, live_attributes=ATTRIBUTES)
        assert data.solar_shape_used is True

    async def test_with_no_shape_anywhere_the_plan_is_unchanged(self, monkeypatch):
        data = await self._plan(monkeypatch, 3, shape=None, live_attributes={})
        assert data.solar_shape_used is False
