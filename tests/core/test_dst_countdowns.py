"""
test_dst_countdowns.py — rate-period countdowns across a clock change.

Python subtracts two aware datetimes that share a tzinfo as plain wall-clock
time and ignores the UTC offset. These tests use Europe/Dublin around the
2026 clock changes, where the wall-clock answer is an hour out:

  Spring forward: 2026-03-29 01:00 GMT -> 02:00 IST (01:00 UTC). 01:00-01:59 does not exist.
  Fall back:      2026-10-25 02:00 IST -> 01:00 GMT (01:00 UTC). 01:00-01:59 happens twice.

The user's tariff is Night 23:00-08:00 and Nightboost 02:00-04:00 over a Day base rate.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.core.engine import _minutes_remaining_in_period
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator, build_tariff
from custom_components.givenergy_inverter_manager.core.timeutil import (
    elapsed_seconds,
    real_time_after,
)
from tests.conftest import _nightboost_cfg, _raw
from tests.core.flat_engine import accumulate_energy

DUBLIN = ZoneInfo("Europe/Dublin")


def _local(y, mo, d, h, mi=0, fold=0):
    return datetime(y, mo, d, h, mi, tzinfo=DUBLIN, fold=fold)


def _tariff(periods=None):
    cfg = _nightboost_cfg()
    if periods is not None:
        cfg["rate_periods"] = periods
    return build_tariff(cfg)


def _minutes_left(tariff, now):
    return _minutes_remaining_in_period(tariff, tariff.get_current_rate(now), now)


# ── elapsed_seconds ───────────────────────────────────────────────────────────


class TestElapsedSeconds:
    def test_spring_forward_is_real_elapsed_time(self):
        assert elapsed_seconds(_local(2026, 3, 29, 0, 30), _local(2026, 3, 29, 5, 30)) == 4 * 3600

    def test_fall_back_is_real_elapsed_time(self):
        assert elapsed_seconds(_local(2026, 10, 25, 0, 30), _local(2026, 10, 25, 5, 30)) == 6 * 3600

    def test_repeated_hour_uses_fold(self):
        first = _local(2026, 10, 25, 1, 30, fold=0)
        second = _local(2026, 10, 25, 1, 30, fold=1)
        assert elapsed_seconds(first, second) == 3600

    def test_mixed_zones_use_utc(self):
        a = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        b = _local(2026, 6, 15, 14, 0)  # 13:00 UTC in summer
        assert elapsed_seconds(a, b) == 3600

    def test_naive_datetimes_subtract_directly(self):
        assert elapsed_seconds(datetime(2024, 6, 15, 14, 0), datetime(2024, 6, 15, 15, 0)) == 3600

    def test_negative_when_end_is_earlier(self):
        a = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        assert elapsed_seconds(a, a.replace(hour=11)) == -3600


# ── _minutes_remaining_in_period ──────────────────────────────────────────────


class TestMinutesRemainingAcrossClockChange:
    def test_reviewer_example_spring_forward(self):
        # 00:30 to 05:30 local on 29 March is 4.0 h real, not 5.0 h.
        tariff = _tariff([{"name": "Early", "rate": 0.10, "start": "22:00", "end": "05:30"}])
        assert _minutes_left(tariff, _local(2026, 3, 29, 0, 30)) == 240.0

    def test_night_spring_forward_from_before_midnight(self):
        # 23:30 on 28 March to 08:00 on 29 March: 7.5 h real.
        assert _minutes_left(_tariff(), _local(2026, 3, 28, 23, 30)) == 450.0

    def test_night_spring_forward_after_midnight(self):
        assert _minutes_left(_tariff(), _local(2026, 3, 29, 0, 30)) == 390.0

    def test_nightboost_after_spring_forward_is_unaffected(self):
        assert _minutes_left(_tariff(), _local(2026, 3, 29, 2, 30)) == 90.0

    def test_night_fall_back_from_before_midnight(self):
        # 23:30 on 24 October to 08:00 on 25 October: 9.5 h real.
        assert _minutes_left(_tariff(), _local(2026, 10, 24, 23, 30)) == 570.0

    def test_night_fall_back_after_midnight(self):
        assert _minutes_left(_tariff(), _local(2026, 10, 25, 0, 30)) == 510.0

    def test_night_in_first_pass_of_repeated_hour(self):
        # 01:30 IST is 00:30 UTC. Night ends 08:00 GMT = 08:00 UTC.
        assert _minutes_left(_tariff(), _local(2026, 10, 25, 1, 30, fold=0)) == 450.0

    def test_night_in_second_pass_of_repeated_hour(self):
        # 01:30 GMT is 01:30 UTC.
        assert _minutes_left(_tariff(), _local(2026, 10, 25, 1, 30, fold=1)) == 390.0

    def test_nightboost_on_fall_back_night_is_two_real_hours(self):
        # 02:00 exists once (as GMT), so the 02:00-04:00 window is not stretched.
        tariff = _tariff()
        assert tariff.get_current_rate(_local(2026, 10, 25, 2, 0)).name == "Nightboost"
        assert _minutes_left(tariff, _local(2026, 10, 25, 2, 0)) == 120.0
        assert _minutes_left(tariff, _local(2026, 10, 25, 3, 0)) == 60.0

    def test_period_end_in_repeated_hour_follows_the_current_pass(self):
        tariff = _tariff([{"name": "Late", "rate": 0.10, "start": "22:00", "end": "01:30"}])
        # First pass: 00:30 IST to 01:30 IST.
        assert _minutes_left(tariff, _local(2026, 10, 25, 0, 30)) == 60.0
        # Second pass: 01:20 GMT to 01:30 GMT, not rolled to tomorrow.
        assert _minutes_left(tariff, _local(2026, 10, 25, 1, 20, fold=1)) == 10.0

    def test_period_end_in_skipped_hour_does_not_crash(self):
        # 01:30 does not exist on 29 March. fold=0 reads it with the offset in force
        # before the change (GMT), so it is the instant 01:30 UTC (02:30 IST).
        tariff = _tariff([{"name": "Late", "rate": 0.10, "start": "22:00", "end": "01:30"}])
        assert _minutes_left(tariff, _local(2026, 3, 29, 0, 30)) == 60.0


class TestMinutesRemainingRegression:
    def test_ordinary_day_matches_wall_clock(self):
        tariff = _tariff()
        assert _minutes_left(tariff, _local(2026, 6, 15, 1, 0)) == 420.0
        assert _minutes_left(tariff, _local(2026, 6, 15, 3, 0)) == 60.0

    def test_window_crossing_midnight(self):
        assert _minutes_left(_tariff(), _local(2026, 6, 15, 23, 30)) == 510.0

    def test_base_rate_has_no_countdown(self):
        assert _minutes_left(_tariff(), _local(2026, 6, 15, 14, 0)) is None


# ── next_cheap_rate ───────────────────────────────────────────────────────────

_EARLY = [{"name": "Early", "rate": 0.10, "start": "05:00", "end": "07:00"}]


class TestNextCheapRateAcrossClockChange:
    def test_spring_forward(self):
        # 00:30 GMT to 05:00 IST (04:00 UTC) is 3.5 h real.
        assert _tariff(_EARLY).next_cheap_rate(_local(2026, 3, 29, 0, 30)) == (3.5, "05:00")

    def test_fall_back(self):
        # 00:30 IST (23:30 UTC) to 05:00 GMT (05:00 UTC) is 5.5 h real.
        assert _tariff(_EARLY).next_cheap_rate(_local(2026, 10, 25, 0, 30)) == (5.5, "05:00")

    def test_first_pass_of_repeated_hour(self):
        # 01:30 IST is 00:30 UTC.
        assert _tariff(_EARLY).next_cheap_rate(_local(2026, 10, 25, 1, 30, fold=0)) == (
            4.5,
            "05:00",
        )

    def test_second_pass_of_repeated_hour(self):
        assert _tariff(_EARLY).next_cheap_rate(_local(2026, 10, 25, 1, 30, fold=1)) == (
            3.5,
            "05:00",
        )

    def test_start_in_skipped_hour_does_not_crash(self):
        skipped = [{"name": "Odd", "rate": 0.10, "start": "01:30", "end": "03:00"}]
        # 01:30 on 29 March is read as 01:30 UTC, one hour after 00:30 GMT.
        assert _tariff(skipped).next_cheap_rate(_local(2026, 3, 29, 0, 30)) == (1.0, "01:30")

    def test_user_tariff_is_cheap_all_night(self):
        # Night covers 23:00-08:00, so the clock changes never fall in a countdown.
        tariff = _tariff()
        assert tariff.next_cheap_rate(_local(2026, 3, 29, 0, 30)) == (0.0, None)
        assert tariff.next_cheap_rate(_local(2026, 10, 25, 1, 30, fold=1)) == (0.0, None)
        assert tariff.next_cheap_rate(_local(2026, 3, 29, 12, 0)) == (11.0, "23:00")
        assert tariff.next_cheap_rate(_local(2026, 10, 25, 12, 0)) == (11.0, "23:00")


class TestNextCheapRateRegression:
    def test_ordinary_day_matches_wall_clock(self):
        tariff = _tariff()
        assert tariff.next_cheap_rate(_local(2026, 6, 15, 14, 0)) == (9.0, "23:00")
        assert tariff.next_cheap_rate(_local(2026, 6, 15, 22, 30)) == (0.5, "23:00")

    def test_window_crossing_midnight(self):
        after_midnight = [{"name": "Late", "rate": 0.10, "start": "00:30", "end": "02:00"}]
        assert _tariff(after_midnight).next_cheap_rate(_local(2026, 6, 15, 22, 0)) == (
            2.5,
            "00:30",
        )

    def test_ignores_seconds_like_before(self):
        now = datetime(2026, 6, 15, 22, 29, 40, tzinfo=DUBLIN)
        assert _tariff().next_cheap_rate(now) == (0.52, "23:00")


# ── accumulate_energy ─────────────────────────────────────────────────────────


class TestAccumulationAcrossClockChange:
    @staticmethod
    def _solar_kwh(last, now):
        acc = EnergyAccumulator()
        raw = _raw(solar_power_w=3600.0, grid_power_w=0.0)
        accumulate_energy(acc, raw, _tariff(), "Day", now, last)
        return acc.solar_kwh

    def test_ten_seconds_across_spring_forward_is_counted(self):
        last = datetime(2026, 3, 29, 0, 59, 55, tzinfo=DUBLIN)
        now = datetime(2026, 3, 29, 2, 0, 5, tzinfo=DUBLIN)
        assert self._solar_kwh(last, now) == pytest.approx(3.6 * 10 / 3600)

    def test_ten_seconds_across_fall_back_is_counted(self):
        last = datetime(2026, 10, 25, 1, 59, 55, tzinfo=DUBLIN, fold=0)
        now = datetime(2026, 10, 25, 1, 0, 5, tzinfo=DUBLIN, fold=1)
        assert self._solar_kwh(last, now) == pytest.approx(3.6 * 10 / 3600)



# ── real_time_after (switch cooldown) ─────────────────────────────────────────


class TestRealTimeAfter:
    TEN = timedelta(minutes=10)

    def test_cooldown_set_before_spring_forward_still_runs_after_it(self):
        # 00:58 GMT + 10 min lasts until 01:08 UTC, which the clock shows as 02:08.
        until = real_time_after(_local(2026, 3, 29, 0, 58), self.TEN)
        assert _local(2026, 3, 29, 2, 0) < until
        assert not _local(2026, 3, 29, 2, 10) < until

    def test_cooldown_set_before_fall_back_ends_on_time(self):
        # 01:58 IST + 10 min is 01:08 UTC. At 01:30 GMT it has already expired.
        until = real_time_after(_local(2026, 10, 25, 1, 58, fold=0), self.TEN)
        assert _local(2026, 10, 25, 1, 0, fold=1) < until
        assert not _local(2026, 10, 25, 1, 30, fold=1) < until

    def test_ordinary_day(self):
        now = _local(2026, 6, 15, 12, 0)
        assert real_time_after(now, self.TEN) == now + self.TEN
