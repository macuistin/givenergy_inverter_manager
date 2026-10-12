"""A forecast's own per-period figures become 48 half-hour weights, or nothing."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.core.solar_shape import (
    SLOTS,
    solar_shape_from_periods,
    valid_shape,
)

DUBLIN = ZoneInfo("Europe/Dublin")
FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "forecast" / "solcast_tomorrow.json").read_text()
)
HALF_HOURLY = FIXTURE["attributes"]["detailedForecast"]
HOURLY = FIXTURE["attributes"]["detailedHourly"]


def periods(day: str, powers: list[float], step: timedelta = timedelta(minutes=30), tz=DUBLIN):
    """Periods from midnight local time on *day*, each *step* long, the way Solcast writes them."""
    start = datetime.fromisoformat(day).replace(tzinfo=tz)
    return [
        {"period_start": (start + step * i).isoformat(), "pv_estimate": p}
        for i, p in enumerate(powers)
    ]


def peak_slot(shape) -> int:
    return max(range(SLOTS), key=lambda i: shape[i])


class TestARealSolcastDay:
    """The sensor attributes read from a live Solcast install."""

    def test_half_hourly_periods_give_a_normalised_shape_peaking_at_midday(self):
        shape = solar_shape_from_periods(HALF_HOURLY, DUBLIN)
        assert shape is not None
        assert len(shape) == SLOTS
        assert sum(shape) == pytest.approx(1.0, abs=1e-4)
        assert 22 <= peak_slot(shape) <= 28  # between 11:00 and 14:00
        assert shape[:15] == (0.0,) * 15  # nothing before 07:30
        assert shape[40:] == (0.0,) * 8  # nothing from 20:00

    def test_the_weights_follow_the_periods(self):
        shape = solar_shape_from_periods(HALF_HOURLY, DUBLIN)
        total = sum(p["pv_estimate"] for p in HALF_HOURLY)
        for slot, period in enumerate(HALF_HOURLY):
            assert shape[slot] == pytest.approx(period["pv_estimate"] / total, abs=1e-5)

    def test_hourly_periods_are_not_read_as_half_hours(self):
        hourly = solar_shape_from_periods(HOURLY, DUBLIN)
        half = solar_shape_from_periods(HALF_HOURLY, DUBLIN)
        assert hourly is not None
        # An hourly period covers two slots, so the two get the same weight.
        assert hourly[24] == pytest.approx(hourly[25])
        assert sum(abs(a - b) for a, b in zip(hourly, half, strict=True)) < 0.12

    def test_a_datetime_start_is_as_good_as_a_string(self):
        parsed = [
            {**p, "period_start": datetime.fromisoformat(p["period_start"])} for p in HALF_HOURLY
        ]
        assert solar_shape_from_periods(parsed, DUBLIN) == solar_shape_from_periods(
            HALF_HOURLY, DUBLIN
        )


class TestTheClockChangeDays:
    def test_a_spring_day_has_no_weight_in_the_missing_hour(self):
        # 2031-03-30: at 01:00 the clocks go forward to 02:00, so local 01:00 to 02:00 never
        # happens and the day has 46 real slots.
        utc = ZoneInfo("UTC")
        start = datetime(2031, 3, 30, 0, 0, tzinfo=utc)  # 00:00 local (UTC+0)
        locals_ = [(start + timedelta(minutes=30 * i)).astimezone(DUBLIN) for i in range(46)]
        assert [loc.hour for loc in locals_[:4]] == [0, 0, 2, 2]
        listed = [
            {"period_start": loc.isoformat(), "pv_estimate": 5.0 if loc.hour in (12, 13) else 0.0}
            for loc in locals_
        ]
        shape = solar_shape_from_periods(listed, DUBLIN)
        assert shape is not None
        assert sum(shape) == pytest.approx(1.0, abs=1e-4)
        assert shape[2] == shape[3] == 0.0  # the missing hour
        assert {i for i in range(SLOTS) if shape[i] > 0} == {24, 25, 26, 27}  # 12:00 to 14:00 local

    def test_an_autumn_day_adds_the_repeated_hour_into_one_slot(self):
        # 2031-10-26: the clocks go back at 02:00 and 01:00 to 02:00 happens twice. 50 slots.
        utc = ZoneInfo("UTC")
        start = datetime(2031, 10, 25, 23, 0, tzinfo=utc)  # 00:00 local (UTC+1)
        listed = []
        for i in range(50):
            local = (start + timedelta(minutes=30 * i)).astimezone(DUBLIN)
            listed.append({"period_start": local.isoformat(), "pv_estimate": 1.0})
        shape = solar_shape_from_periods(listed, DUBLIN)
        assert shape is not None
        assert sum(shape) == pytest.approx(1.0, abs=1e-4)
        # Slots 2 and 3 (01:00 to 02:00) hold both passes of the hour.
        assert shape[2] == pytest.approx(2 * shape[10])
        assert shape[3] == pytest.approx(2 * shape[10])


class TestWhatIsNotAShape:
    @pytest.mark.parametrize(
        "bad",
        [None, "", "abc", 12, {}, [], [{"period_start": "x"}] * 20, [1, 2, 3] * 10],
        ids=["none", "empty str", "str", "int", "dict", "empty list", "no power", "not mappings"],
    )
    def test_anything_that_is_not_a_list_of_periods_gives_none(self, bad):
        assert solar_shape_from_periods(bad, DUBLIN) is None

    def test_too_few_periods_give_none(self):
        assert solar_shape_from_periods(periods("2031-06-15", [1.0] * 8), DUBLIN) is None

    @pytest.mark.parametrize(
        "power", [-1.0, math.nan, math.inf, "text", None, True], ids=lambda p: repr(p)
    )
    def test_one_bad_power_rejects_the_whole_day(self, power):
        powers = [1.0] * 48
        powers[20] = power
        assert solar_shape_from_periods(periods("2031-06-15", powers), DUBLIN) is None

    def test_a_day_of_zeros_gives_none(self):
        assert solar_shape_from_periods(periods("2031-06-15", [0.0] * 48), DUBLIN) is None

    def test_a_start_that_is_not_a_time_gives_none(self):
        listed = periods("2031-06-15", [1.0] * 48)
        listed[3]["period_start"] = "half past one"
        assert solar_shape_from_periods(listed, DUBLIN) is None

    def test_periods_of_some_other_length_give_none(self):
        assert (
            solar_shape_from_periods(
                periods("2031-06-15", [1.0] * 48, step=timedelta(minutes=45)), DUBLIN
            )
            is None
        )

    def test_a_start_with_no_zone_is_read_in_the_given_zone(self):
        listed = [{"period_start": f"2031-06-15T{i // 2:02d}:{30 * (i % 2):02d}:00", "pv_estimate": 1.0} for i in range(48)]
        shape = solar_shape_from_periods(listed, DUBLIN)
        assert shape == (pytest.approx(1 / 48, abs=1e-5),) * 48


class TestValidShape:
    def test_it_normalises_a_good_shape(self):
        shape = valid_shape([2.0] * 48)
        assert shape == (pytest.approx(1 / 48),) * 48

    @pytest.mark.parametrize(
        "bad",
        [None, [1.0] * 47, [1.0] * 49, [-1.0] + [1.0] * 47, [math.nan] * 48, [0.0] * 48, "x" * 48],
        ids=["none", "short", "long", "negative", "nan", "zeros", "text"],
    )
    def test_anything_else_is_none(self, bad):
        assert valid_shape(bad) is None
