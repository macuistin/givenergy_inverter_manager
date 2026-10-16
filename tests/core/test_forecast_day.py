"""The overnight charge decision reads the forecast for the solar day it serves.

The forecast sensor reports "tomorrow". At midnight it moves on a day, so a decision made
between midnight and sunrise must read the forecast remembered from before midnight.
"""

from datetime import datetime

import pytest

from custom_components.givenergy_inverter_manager.const import CONF_FORECAST_ENTITY_D2
from tests.conftest import _nightboost_cfg, _raw, _run

BEFORE_MIDNIGHT = datetime(2026, 10, 5, 21, 0)
AFTER_MIDNIGHT = datetime(2026, 10, 6, 1, 59)
AFTER_SUNRISE = datetime(2026, 10, 6, 12, 0)

WRONG_DAY_KWH = 34.8
TODAY_KWH = 7.1


def _decision(
    now, *, tomorrow, remembered=None, p10=None, remembered_p10=None, d2=None, d2_sensor=False
):
    raw = _raw(battery_soc=40.0, battery_capacity_kwh=19.0, forecast_kwh_tomorrow=tomorrow)
    raw.forecast_kwh_p10 = p10
    raw.forecast_kwh_d2 = d2
    cfg = {**_nightboost_cfg(), CONF_FORECAST_ENTITY_D2: "sensor.day_after"} if d2_sensor else None
    data, _ = _run(
        raw=raw,
        cfg=cfg,
        now=now,
        today_raw_forecast_kwh=remembered,
        today_raw_forecast_p10_kwh=remembered_p10,
    )
    return data.charge_decision


class TestForecastDay:
    def test_before_midnight_reads_the_tomorrow_sensor(self):
        decision = _decision(BEFORE_MIDNIGHT, tomorrow=TODAY_KWH, remembered=WRONG_DAY_KWH)
        assert decision.forecast_kwh == pytest.approx(TODAY_KWH)

    def test_after_midnight_reads_the_forecast_remembered_before_midnight(self):
        decision = _decision(AFTER_MIDNIGHT, tomorrow=WRONG_DAY_KWH, remembered=TODAY_KWH)
        assert decision.forecast_kwh == pytest.approx(TODAY_KWH)

    def test_after_sunrise_reads_the_tomorrow_sensor_again(self):
        decision = _decision(AFTER_SUNRISE, tomorrow=TODAY_KWH, remembered=WRONG_DAY_KWH)
        assert decision.forecast_kwh == pytest.approx(TODAY_KWH)

    def test_after_midnight_without_a_remembered_forecast_falls_back_to_the_estimate(self):
        decision = _decision(AFTER_MIDNIGHT, tomorrow=WRONG_DAY_KWH, remembered=None)
        assert decision.forecast_kwh != pytest.approx(WRONG_DAY_KWH)
        assert "seasonal" in decision.reason


class TestForecastDayP10:
    def test_after_midnight_ignores_the_p10_sensor_for_the_wrong_day(self):
        decision = _decision(
            AFTER_MIDNIGHT, tomorrow=WRONG_DAY_KWH, remembered=TODAY_KWH, p10=1.0
        )
        assert decision.forecast_kwh == pytest.approx(TODAY_KWH)

    def test_after_midnight_blends_the_remembered_p10(self):
        decision = _decision(
            AFTER_MIDNIGHT,
            tomorrow=WRONG_DAY_KWH,
            remembered=TODAY_KWH,
            p10=30.0,
            remembered_p10=2.0,
        )
        assert decision.forecast_kwh < TODAY_KWH


class TestOvermorrowAfterMidnight:
    def test_the_tomorrow_sensor_becomes_the_day_after_the_one_charged_for(self):
        without = _decision(AFTER_MIDNIGHT, tomorrow=None, remembered=5.0, d2_sensor=True)
        strong_next_day = _decision(AFTER_MIDNIGHT, tomorrow=25.0, remembered=5.0, d2_sensor=True)
        assert strong_next_day.target_soc < without.target_soc
        assert "Overmorrow" in strong_next_day.reason

    def test_it_does_not_without_a_day_after_sensor(self):
        without = _decision(AFTER_MIDNIGHT, tomorrow=None, remembered=5.0)
        strong_next_day = _decision(AFTER_MIDNIGHT, tomorrow=25.0, remembered=5.0)
        assert strong_next_day.target_soc == without.target_soc
        assert "Overmorrow" not in strong_next_day.reason


class TestProviderForecastForToday:
    """The snapshot carries the forecast remembered before midnight next to the plan's blend."""

    def _data(self, remembered):
        raw = _raw(battery_soc=40.0, battery_capacity_kwh=19.0, forecast_kwh_tomorrow=WRONG_DAY_KWH)
        data, _ = _run(raw=raw, now=AFTER_SUNRISE, today_raw_forecast_kwh=remembered)
        return data

    def test_publishes_the_remembered_forecast_not_the_tomorrow_sensor(self):
        data = self._data(TODAY_KWH)
        assert data.solar_forecast_raw_kwh_today == pytest.approx(TODAY_KWH)

    def test_is_none_when_nothing_was_remembered(self):
        assert self._data(None).solar_forecast_raw_kwh_today is None
