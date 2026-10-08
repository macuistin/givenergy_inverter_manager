"""The estimated SoC at sunrise moves no faster than the battery can.

The calculated estimate steps at midnight (the day's energy total resets), at 08:00 (the window
flips from this morning to tonight) and at dusk (the window grows from the pre-solar hours to
the whole evening). Each step moved the published sensor by 15 points or more in one cycle.
"""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.core.sunrise_hold import (
    HeldSunrise,
    SunriseReading,
    max_battery_swing_pct_per_hour,
    published_sunrise_soc,
)
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run

NOW = datetime(2026, 6, 15, 12, 0)
RATE = 25.0  # SoC points per hour


def _reading(soc: float, minutes: float = 0.5) -> SunriseReading:
    return SunriseReading(soc, NOW + timedelta(minutes=minutes), RATE)


def _held(soc: float) -> HeldSunrise:
    return HeldSunrise(soc, NOW)


class TestPublishedSunriseSoc:
    def test_the_first_reading_is_published_as_it_is(self):
        assert published_sunrise_soc(HeldSunrise(), _reading(42.0)) == 42.0

    def test_a_small_move_is_published_as_it_is(self):
        assert published_sunrise_soc(_held(60.0), _reading(60.1)) == pytest.approx(60.1)

    def test_a_fall_is_limited_to_the_rate(self):
        assert published_sunrise_soc(_held(75.0), _reading(10.0, 30)) == pytest.approx(62.5)

    def test_a_rise_is_limited_to_the_rate(self):
        assert published_sunrise_soc(_held(40.0), _reading(95.0, 30)) == pytest.approx(52.5)

    def test_a_gap_over_an_hour_publishes_the_calculated_value(self):
        assert published_sunrise_soc(_held(75.0), _reading(10.0, 61)) == 10.0

    def test_no_known_battery_rate_publishes_the_calculated_value(self):
        reading = SunriseReading(10.0, NOW + timedelta(minutes=1), 0.0)
        assert published_sunrise_soc(_held(75.0), reading) == 10.0

    def test_the_same_timestamp_publishes_the_calculated_value(self):
        assert published_sunrise_soc(_held(75.0), _reading(10.0, 0)) == 10.0

    def test_elapsed_time_is_real_time_across_a_clock_change(self):
        utc = timezone.utc
        held = HeldSunrise(75.0, datetime(2026, 3, 29, 0, 30, tzinfo=utc))
        reading = SunriseReading(10.0, datetime(2026, 3, 29, 1, 0, tzinfo=utc), RATE)
        assert published_sunrise_soc(held, reading) == pytest.approx(62.5)


class TestMaxBatterySwing:
    def test_inverter_power_over_capacity(self):
        assert max_battery_swing_pct_per_hour(5000.0, 20.0) == pytest.approx(25.0)

    @pytest.mark.parametrize(("inverter_w", "capacity"), [(0.0, 20.0), (5000.0, 0.0)])
    def test_unknown_when_either_is_missing(self, inverter_w, capacity):
        assert max_battery_swing_pct_per_hour(inverter_w, capacity) == 0.0


# ── A whole day through the engine ───────────────────────────────────────────

BASELINE_W = 400.0
EV_W = 7000.0
EV_UNTIL_MINUTE = 7 * 60
CAPACITY_KWH = 19.0
INVERTER_W = 5000.0
SWING_PER_MINUTE = INVERTER_W / 1000 / CAPACITY_KWH * 100 / 60
DAY_START = datetime(2026, 6, 15, 0, 0)


def _soc(minute_of_day: int) -> float:
    """A battery charged on the cheap rate, filled by solar and run down in the evening."""
    hour = minute_of_day / 60
    if hour < 4:
        return 70.0 + (hour / 4) * 19.0
    if hour < 8:
        return 89.0 - (hour - 4) * 2.0
    if hour < 11:
        return min(100.0, 81.0 + (hour - 8) * 8.0)
    if hour < 17:
        return 100.0
    return max(10.0, 100.0 - (hour - 17) * 3.0)


def _solar_w(minute_of_day: int) -> float:
    return 2500.0 if 6.5 * 60 <= minute_of_day < 18.75 * 60 else 0.0


def _cycle(minute: int, held: HeldSunrise):
    """One engine cycle at this minute of a two day run, the second day starting at midnight."""
    minute_of_day = minute % 1440
    ev_minutes = min(minute_of_day, EV_UNTIL_MINUTE)
    ev_on = minute_of_day < EV_UNTIL_MINUTE
    acc = EnergyAccumulator()
    acc.zappi_kwh = EV_W / 1000 * ev_minutes / 60
    acc.house_kwh = BASELINE_W / 1000 * minute_of_day / 60 + acc.zappi_kwh
    raw = _raw(
        battery_soc=_soc(minute_of_day),
        battery_capacity_kwh=CAPACITY_KWH,
        inverter_max_w=INVERTER_W,
        solar_power_w=_solar_w(minute_of_day),
        house_load_w=BASELINE_W + (EV_W if ev_on else 0.0),
        ev_power_w=EV_W if ev_on else 0.0,
        ev_plugged_in=ev_on,
        forecast_kwh_tomorrow=6.0,
    )
    data, _ = _run(
        raw=raw,
        cfg=_nightboost_cfg(),
        now=DAY_START + timedelta(minutes=minute),
        acc=acc,
        today_raw_forecast_kwh=6.0,
        held_sunrise=held,
    )
    return data.estimated_soc_at_sunrise


def _series(*, carry_state: bool) -> list[float]:
    held = HeldSunrise()
    values = []
    for minute in range(0, 2 * 1440, 5):
        values.append(_cycle(minute, held if carry_state else HeldSunrise()))
    return values


def _largest_step(values: list[float]) -> float:
    return max(abs(after - before) for before, after in zip(values, values[1:], strict=False))


class TestAWholeDay:
    def test_the_calculated_estimate_really_steps(self):
        """Premise: without the hold the sensor jumps by 15 points or more in one 5 minute step."""
        assert _largest_step(_series(carry_state=False)) >= 15.0

    def test_the_published_estimate_never_jumps(self):
        values = _series(carry_state=True)
        assert _largest_step(values) <= SWING_PER_MINUTE * 5 + 1e-6

    def test_the_published_estimate_catches_up_after_each_step(self):
        """It lags a step by about half an hour, not for good."""
        calculated = _series(carry_state=False)
        published = _series(carry_state=True)
        lagging = [
            minute
            for minute, (a, b) in enumerate(zip(calculated, published, strict=True))
            if abs(a - b) > 1.0
        ]
        # Five minute samples, two days, six steps of about 45 minutes at most.
        assert len(lagging) * 5 <= 6 * 60 * 2

    def test_the_ev_charge_does_not_pull_the_estimate_to_the_floor(self):
        values = _series(carry_state=True)
        overnight = values[6:84]  # 00:30 to 07:00
        assert min(overnight) > 40.0
