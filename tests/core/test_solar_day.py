"""Whether the solar day has started is settled over a few minutes, not read from one sample.

The night window flips between 8 and 24 hours when the solar reading crosses the noise floor.
At dawn and dusk the reading wanders across it every few cycles, which flipped the Battery
Night Survival Status between "Estimated shortfall" and "should last". These tests replay that
through the engine with the held state carried over, as the coordinator does.
"""

from datetime import datetime, timedelta

import pytest

from custom_components.givenergy_inverter_manager.const import (
    SOLAR_DAY_DEBOUNCE_MINUTES,
    SOLAR_NOISE_FLOOR_W,
)
from custom_components.givenergy_inverter_manager.core.battery import hours_until_solar
from custom_components.givenergy_inverter_manager.core.solar_day import (
    HeldSolarDay,
    SolarReading,
    settled_solar_w,
)
from custom_components.givenergy_inverter_manager.core.sunrise_hold import HeldSunrise
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from custom_components.givenergy_inverter_manager.sensor_values import night_survival_confidence
from tests.conftest import _nightboost_cfg, _raw, _run

CYCLE = timedelta(seconds=30)
DEBOUNCE = timedelta(minutes=SOLAR_DAY_DEBOUNCE_MINUTES)
BELOW_W = SOLAR_NOISE_FLOOR_W - 1.0
ABOVE_W = SOLAR_NOISE_FLOOR_W + 2.0
DAWN = datetime(2026, 10, 9, 8, 0)
CAPACITY_KWH = 19.0
HOUSE_LOAD_KW = 1.07


def _settle(held: HeldSolarDay, power_w: float, now: datetime) -> float:
    return settled_solar_w(held, SolarReading(power_w, now))


def _started(held: HeldSolarDay, power_w: float, now: datetime) -> bool:
    return _settle(held, power_w, now) >= SOLAR_NOISE_FLOOR_W


# ── The debounce on its own ───────────────────────────────────────────────────


class TestSettledSolar:
    def test_the_first_reading_is_taken_as_it_is(self):
        assert _settle(HeldSolarDay(), 0.0, DAWN) == 0.0
        assert _settle(HeldSolarDay(), 500.0, DAWN) == 500.0

    def test_a_reading_at_the_noise_floor_counts_as_generating(self):
        assert _started(HeldSolarDay(), SOLAR_NOISE_FLOOR_W, DAWN)
        assert not _started(HeldSolarDay(), SOLAR_NOISE_FLOOR_W - 0.1, DAWN)

    def test_the_day_starts_once_solar_has_stayed_above_the_floor_for_the_debounce(self):
        held = HeldSolarDay()
        _settle(held, 0.0, DAWN)
        assert not _started(held, ABOVE_W, DAWN + CYCLE)
        assert not _started(held, ABOVE_W, DAWN + CYCLE + DEBOUNCE - CYCLE)
        assert _started(held, ABOVE_W, DAWN + CYCLE + DEBOUNCE)

    def test_the_day_ends_once_solar_has_stayed_below_the_floor_for_the_debounce(self):
        held = HeldSolarDay()
        _settle(held, 300.0, DAWN)
        assert _started(held, BELOW_W, DAWN + CYCLE)
        assert _started(held, BELOW_W, DAWN + CYCLE + DEBOUNCE - CYCLE)
        assert not _started(held, BELOW_W, DAWN + CYCLE + DEBOUNCE)

    def test_a_dip_back_restarts_the_count(self):
        held = HeldSolarDay()
        _settle(held, 0.0, DAWN)
        _settle(held, ABOVE_W, DAWN + CYCLE)
        _settle(held, BELOW_W, DAWN + DEBOUNCE - CYCLE)
        assert not _started(held, ABOVE_W, DAWN + DEBOUNCE)
        assert not _started(held, ABOVE_W, DAWN + DEBOUNCE + DEBOUNCE - CYCLE)
        assert _started(held, ABOVE_W, DAWN + DEBOUNCE + DEBOUNCE)

    def test_a_started_day_reports_at_least_the_floor_through_a_dip(self):
        held = HeldSolarDay()
        _settle(held, 300.0, DAWN)
        assert _settle(held, 2.0, DAWN + CYCLE) == SOLAR_NOISE_FLOOR_W
        assert _settle(held, 300.0, DAWN + CYCLE * 2) == 300.0

    def test_a_gap_over_an_hour_takes_the_reading_as_it_is(self):
        held = HeldSolarDay()
        _settle(held, 300.0, DAWN)
        assert _settle(held, 0.0, DAWN + timedelta(minutes=61)) == 0.0

    def test_the_same_timestamp_takes_the_reading_as_it_is(self):
        held = HeldSolarDay()
        _settle(held, 300.0, DAWN)
        assert _settle(held, 0.0, DAWN) == 0.0

    def test_elapsed_time_is_real_time_across_a_clock_change(self):
        from datetime import timezone

        utc = timezone.utc
        start = datetime(2026, 10, 25, 0, 30, tzinfo=utc)
        held = HeldSolarDay()
        _settle(held, 0.0, start)
        _settle(held, ABOVE_W, start + CYCLE)
        assert _started(held, ABOVE_W, start + CYCLE + DEBOUNCE)


# ── A day through the engine ──────────────────────────────────────────────────


def _cycle(now: datetime, solar_w: float, soc: float, held_solar, held_sunrise):
    """One cycle, the house drawing a steady load since midnight."""
    midnight = datetime(now.year, now.month, now.day)
    minute = (now - midnight).total_seconds() / 60
    acc = EnergyAccumulator()
    acc.house_kwh = HOUSE_LOAD_KW * minute / 60
    raw = _raw(
        battery_soc=soc,
        battery_capacity_kwh=CAPACITY_KWH,
        house_load_w=HOUSE_LOAD_KW * 1000,
        solar_power_w=solar_w,
        battery_power_w=0.0,
        forecast_kwh_tomorrow=21.7,
    )
    data, _ = _run(
        raw=raw,
        cfg=_nightboost_cfg(),
        now=now,
        acc=acc,
        today_raw_forecast_kwh=22.0,
        held_solar=held_solar,
        held_sunrise=held_sunrise,
    )
    return data


def _replay(start: datetime, readings: list[tuple[float, float]], *, memory: bool = True):
    """Run one cycle per (solar_w, soc) pair. Without memory each cycle starts from nothing."""
    held_solar, held_sunrise = HeldSolarDay(), HeldSunrise()
    cycles = []
    for i, (solar_w, soc) in enumerate(readings):
        if not memory:
            held_solar, held_sunrise = HeldSolarDay(), HeldSunrise()
        cycles.append(_cycle(start + CYCLE * i, solar_w, soc, held_solar, held_sunrise))
    return cycles


def _changes(values: list) -> int:
    return sum(1 for before, after in zip(values, values[1:], strict=False) if before != after)


def _verdict(data) -> str:
    """The message a reader sees, without the kWh figure, which drifts with the load estimate."""
    return "shortfall" if "shortfall" in data.survival_reason else "should last"


def _shown(cycles: list) -> list:
    return [(_verdict(d), d.will_survive_night, night_survival_confidence(d)) for d in cycles]


FLICKER = [(BELOW_W if i % 2 == 0 else ABOVE_W, 87.0) for i in range(20)]


class TestSolarFlickeringAtDawn:
    """08:00 to 08:10, 9 W then 12 W, with a house that lasts 8 hours but not 24."""

    def test_premise_the_raw_window_flips_between_8_and_24_hours(self):
        assert hours_until_solar(8, BELOW_W) == 24.0
        assert hours_until_solar(8, ABOVE_W) == 8.0

    def test_premise_without_memory_the_status_flips_with_each_reading(self):
        cycles = _replay(DAWN, FLICKER, memory=False)
        assert _changes([_verdict(d) for d in cycles]) >= 10
        assert "shortfall" in cycles[0].survival_reason
        assert "should last" in cycles[1].survival_reason

    def test_the_status_reason_and_confidence_do_not_flip(self):
        assert _changes(_shown(_replay(DAWN, FLICKER))) == 0

    def test_the_window_is_the_same_length_in_every_cycle(self):
        cycles = _replay(DAWN, FLICKER)
        assert all("shortfall" in d.survival_reason for d in cycles)


class TestTheDayStartsAtDawn:
    def test_a_steady_reading_changes_the_status_once_after_the_debounce(self):
        readings = [(0.0, 87.0)] + [(ABOVE_W, 87.0)] * 40
        cycles = _replay(DAWN, readings)
        reasons = [_verdict(d) for d in cycles]
        assert reasons[:2] == ["shortfall", "shortfall"]
        assert _changes(reasons) == 1
        flip = reasons.index("should last")
        assert CYCLE * (flip - 1) == pytest.approx(DEBOUNCE, abs=CYCLE)

    def test_a_restart_in_full_sun_reads_the_sun_at_once(self):
        cycles = _replay(DAWN + timedelta(hours=4), [(2500.0, 87.0)] * 3)
        assert all("should last" in d.survival_reason for d in cycles)


class TestSolarFadingAtDusk:
    """Solar wanders across the floor for a while, then is gone."""

    DUSK = datetime(2026, 10, 8, 18, 40)

    def _readings(self) -> list[tuple[float, float]]:
        day = [(800.0, 80.0)] * 4
        wander = [(BELOW_W if i % 2 == 0 else ABOVE_W, 80.0) for i in range(20)]
        gone = [(1.0, 80.0)] * 40
        return day + wander + gone

    def test_premise_without_memory_the_status_flips_in_the_wander(self):
        cycles = _replay(self.DUSK, self._readings(), memory=False)
        assert _changes([_verdict(d) for d in cycles]) >= 10

    def test_the_status_changes_once_and_not_before_the_debounce_has_passed(self):
        cycles = _replay(self.DUSK, self._readings())
        reasons = [_verdict(d) for d in cycles]
        assert _changes(reasons) == 1
        assert reasons[0] == "should last"
        assert reasons[-1] == "shortfall"
        last_above = 4 + 19  # the last reading of the wander is the one above the floor
        flip = reasons.index("shortfall")
        assert CYCLE * (flip - last_above) == pytest.approx(DEBOUNCE, abs=CYCLE)


class TestARealShortfallShowsAtOnce:
    def test_in_the_small_hours_a_low_battery_is_critical_on_the_first_cycle(self):
        cycles = _replay(datetime(2026, 10, 9, 1, 0), [(0.0, 12.0)])
        assert cycles[0].will_survive_night is False
        assert night_survival_confidence(cycles[0]) == "Critical"

    def test_a_battery_that_falls_below_what_the_night_needs_shows_on_that_cycle(self):
        soc = [40.0] * 6 + [12.0] * 6
        cycles = _replay(datetime(2026, 10, 9, 5, 0), [(0.0, s) for s in soc])
        survives = [d.will_survive_night for d in cycles]
        assert survives == [True] * 6 + [False] * 6

    def test_in_the_afternoon_with_solar_up_a_fall_shows_on_that_cycle(self):
        soc = [60.0] * 6 + [5.0] * 6
        cycles = _replay(datetime(2026, 10, 8, 14, 0), [(1500.0, s) for s in soc])
        assert [d.will_survive_night for d in cycles] == [True] * 6 + [False] * 6

    def test_after_dark_with_no_solar_a_shortfall_shows_on_the_first_cycle(self):
        cycles = _replay(datetime(2026, 10, 8, 21, 0), [(0.0, 30.0)])
        assert cycles[0].will_survive_night is False
