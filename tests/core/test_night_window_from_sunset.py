"""In daylight the night window starts when solar is expected to stop, and counts partial hours.

The daytime window was tonight's 00:00 to 08:00. A battery pause from 23:00 to 08:00 covers all of
it, so the estimate equalled the SoC and left out the evening load before the pause. When solar
stopped at dusk the window became now to 08:00 and the estimate fell 13 to 17 points in one
cycle. The window also counted whole hours, so the estimate stepped by an hour's load at each
hour boundary.

Now the daytime window runs from the time solar is expected to stop (the forecast's shape, or
20:00 with none) to 08:00, and hours are counted to the minute. The charge skip check reads the
same window, so the plan never skips a charge the survival sensor calls Critical.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest

from custom_components.givenergy_inverter_manager.const import SOLAR_NOISE_FLOOR_W
from custom_components.givenergy_inverter_manager.core.battery import (
    NightClock,
    hours_until_solar,
    minute_of_day,
    night_window,
)
from custom_components.givenergy_inverter_manager.core.battery_pause import PauseWindow
from custom_components.givenergy_inverter_manager.core.solar_day import HeldSolarDay
from custom_components.givenergy_inverter_manager.core.solar_shape import (
    DEFAULT_SOLAR_END_MINUTE,
    SLOTS,
    solar_end_minute,
)
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run

PAUSE = PauseWindow(time(23, 0), time(8, 0))
CAPACITY_KWH = 19.0
INVERTER_W = 5000.0
DAILY_LOAD_KWH = 15.0
DAY = datetime(2026, 6, 16)
STEP = timedelta(seconds=30)
SWING_PER_CYCLE = INVERTER_W / 1000 / CAPACITY_KWH * 100 * STEP.seconds / 3600


def _shape_ending(hour: int, minute: int = 0) -> tuple[float, ...]:
    """A forecast shape with solar from 08:00 until this time."""
    end_slot = (hour * 60 + minute) // 30
    return tuple(1.0 if 16 <= slot < end_slot else 0.0 for slot in range(SLOTS))


def _cycle(now: datetime, soc: float, solar_w: float, **kwargs):
    raw = _raw(
        battery_soc=soc,
        battery_capacity_kwh=kwargs.pop("capacity_kwh", CAPACITY_KWH),
        solar_power_w=solar_w,
        inverter_max_w=INVERTER_W,
        forecast_kwh_tomorrow=kwargs.pop("forecast_kwh", 10.0),
    )
    raw.battery_pause = kwargs.pop("pause", PAUSE)
    raw.forecast_shape_tomorrow = kwargs.pop("tomorrow_shape", None)
    acc = EnergyAccumulator()
    # The load estimate scales today's energy by the whole minutes since midnight.
    acc.house_kwh = (
        kwargs.pop("daily_load_kwh", DAILY_LOAD_KWH) * (now.hour * 60 + now.minute) / 1440
    )
    data, _ = _run(raw=raw, cfg=kwargs.pop("cfg", _nightboost_cfg()), now=now, acc=acc, **kwargs)
    return data


def _at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return DAY.replace(hour=hour, minute=minute, second=second)


class TestTheWindow:
    @pytest.mark.parametrize(
        ("minute", "solar_w", "end", "expected"),
        [
            (14 * 60, SOLAR_NOISE_FLOOR_W, 18 * 60, (18 * 60, 14.0)),  # from when solar stops
            (14 * 60, SOLAR_NOISE_FLOOR_W, DEFAULT_SOLAR_END_MINUTE, (20 * 60, 12.0)),
            (19 * 60, SOLAR_NOISE_FLOOR_W, 18 * 60, (19 * 60, 13.0)),  # solar on past its end
            (14 * 60, 0.0, 18 * 60, (14 * 60, 18.0)),  # no solar: from now
        ],
    )
    def test_in_daylight_it_starts_when_solar_is_expected_to_stop(
        self, minute, solar_w, end, expected
    ):
        assert night_window(NightClock(minute, solar_w, end)) == expected

    def test_partial_hours_count_after_dusk(self):
        assert night_window(NightClock(20 * 60 + 30, 0.0, 18 * 60)) == (1230, 11.5)

    def test_partial_hours_count_before_sunrise(self):
        assert hours_until_solar(NightClock(7 * 60 + 45, 0.0, 18 * 60)) == 0.25

    def test_seconds_count_too(self):
        assert minute_of_day(_at(18, 59, 30)) == 18 * 60 + 59.5


class TestWhenSolarIsExpectedToStop:
    def test_the_end_of_the_last_half_hour_with_solar(self):
        assert solar_end_minute(_shape_ending(17, 30)) == 17 * 60 + 30

    def test_without_a_usable_shape_the_default_curve_ends_at_20_00(self):
        assert solar_end_minute(None) == DEFAULT_SOLAR_END_MINUTE == 20 * 60
        assert solar_end_minute([1.0] * 47) == DEFAULT_SOLAR_END_MINUTE

    def test_the_engine_reads_today_s_shape_before_tomorrow_s(self):
        both = _cycle(
            _at(14),
            85.0,
            1500.0,
            today_raw_forecast_shape=_shape_ending(17),
            tomorrow_shape=_shape_ending(19),
        )
        dusk = _cycle(_at(17), 85.0, 0.0)
        assert both.estimated_soc_at_sunrise == pytest.approx(dusk.estimated_soc_at_sunrise)

    def test_without_today_s_shape_tomorrow_s_stands_in(self):
        tomorrow = _cycle(_at(14), 85.0, 1500.0, tomorrow_shape=_shape_ending(17))
        dusk = _cycle(_at(17), 85.0, 0.0)
        assert tomorrow.estimated_soc_at_sunrise == pytest.approx(dusk.estimated_soc_at_sunrise)


class TestTheDaytimeEstimateCountsTheEvening:
    def test_a_late_pause_does_not_hide_the_evening_load(self):
        data = _cycle(_at(14), 85.0, 1500.0)

        # 20:00 to 23:00 is served by the battery: 3 hours of a 15 kWh day.
        assert data.estimated_soc_at_sunrise < 85.0
        assert data.estimated_soc_at_sunrise == pytest.approx(
            85.0 - 3 * DAILY_LOAD_KWH / 24 / CAPACITY_KWH * 100
        )

    @pytest.mark.parametrize(("end_hour", "shape"), [(20, None), (17, _shape_ending(17))])
    def test_the_daytime_figure_is_the_one_solar_stopping_on_time_gives(self, end_hour, shape):
        noon = _cycle(_at(12), 85.0, 1500.0, today_raw_forecast_shape=shape)
        dusk = _cycle(_at(end_hour), 85.0, 0.0, today_raw_forecast_shape=shape)
        assert noon.estimated_soc_at_sunrise == pytest.approx(dusk.estimated_soc_at_sunrise)


def _replay(dusk: datetime, shape: tuple[float, ...] | None) -> list[float]:
    """The calculated estimate every 30 s from 12:00 to 22:00. Only the solar state is carried.

    A fresh sunrise hold each cycle publishes the calculated figure as it is, so the replay sees
    the estimate itself, not the pace the sensor holds it to.
    """
    held_solar = HeldSolarDay()
    figures = []
    now = _at(12)
    while now <= _at(22):
        drain_h = max(0.0, (now - dusk).total_seconds() / 3600)
        soc = 85.0 - drain_h * DAILY_LOAD_KWH / 24 / CAPACITY_KWH * 100
        solar_w = 1500.0 if now < dusk else 0.0
        data = _cycle(now, soc, solar_w, held_solar=held_solar, today_raw_forecast_shape=shape)
        figures.append(data.estimated_soc_at_sunrise)
        now += STEP
    return figures


class TestNoStepAtDusk:
    @pytest.mark.parametrize(
        ("dusk", "shape"),
        [
            pytest.param(_at(18), _shape_ending(18), id="forecast-shape-18:00"),
            pytest.param(_at(20), None, id="default-20:00"),
        ],
    )
    def test_the_estimate_moves_no_more_than_the_battery_can_between_cycles(self, dusk, shape):
        figures = _replay(dusk, shape)
        steps = [abs(after - before) for before, after in zip(figures, figures[1:], strict=False)]
        assert max(steps) <= SWING_PER_CYCLE

    def test_no_step_at_an_hour_boundary(self):
        before = _cycle(_at(20, 59, 30), 70.0, 0.0)
        after = _cycle(_at(21), 70.0, 0.0)

        # 30 seconds less of the night to cover, not a whole hour.
        assert after.estimated_soc_at_sunrise - before.estimated_soc_at_sunrise == pytest.approx(
            DAILY_LOAD_KWH / 24 / 120 / CAPACITY_KWH * 100
        )


class TestTheSkipCheckAgrees:
    """A battery that lasts a paused 00:00 to 08:00 but not the evening before the pause."""

    def _cfg(self):
        cfg = _nightboost_cfg()
        cfg["battery_capacity_kwh"] = 5.0
        return cfg

    def _afternoon(self, **kwargs):
        inputs = {
            "forecast_kwh": 30.0,
            "daily_load_kwh": 30.0,
            "capacity_kwh": 5.0,
            "cfg": self._cfg(),
        }
        inputs.update(kwargs)
        return _cycle(_at(14), 80.0, 1500.0, **inputs)

    def test_the_plan_does_not_skip_a_night_the_sensor_calls_critical(self):
        data = self._afternoon()
        assert data.will_survive_night is False
        assert data.charge_decision.skip_charge is False
        assert "Not skipping" in data.charge_decision.reason

    def test_with_the_evening_paused_too_both_skip(self):
        data = self._afternoon(pause=PauseWindow(time(19, 0), time(8, 0)))
        assert data.will_survive_night is True
        assert data.charge_decision.skip_charge is True

    def test_the_skip_check_reads_the_same_forecast_end(self):
        early = self._afternoon(
            pause=PauseWindow(time(19, 0), time(8, 0)), today_raw_forecast_shape=_shape_ending(16)
        )
        assert early.will_survive_night is False
        assert early.charge_decision.skip_charge is False
