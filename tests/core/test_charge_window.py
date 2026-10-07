"""Unit tests for core/charge_window.py: the charge window sized to the plan."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CHARGE_WINDOW_MARGIN,
    CHARGE_WINDOW_ROUND_MINUTES,
)
from custom_components.givenergy_inverter_manager.core.charge_window import (
    ChargeNeed,
    cheap_run_minutes,
    cheap_run_remaining_minutes,
    plan_charge_window,
)
from custom_components.givenergy_inverter_manager.core.tariff import build_tariff

BASE_RATE = 0.3334
CAPACITY_KWH = 19.0
POWER_W = 3600.0


def _period(name: str, rate: float, start: str, end: str) -> dict:
    return {"name": name, "rate": rate, "start": start, "end": end}


def _tariff(*periods: dict):
    return build_tariff({"base_rate": BASE_RATE, "rate_periods": list(periods)})


def _night_and_boost():
    """Night 23:00 to 08:00 with a cheaper Nightboost 02:00 to 04:00 inside it."""
    return _tariff(
        _period("Night", 0.1644, "23:00", "08:00"),
        _period("Nightboost", 0.0965, "02:00", "04:00"),
    )


def _need(soc: float, target: float, power_w: float | None = POWER_W) -> ChargeNeed:
    return ChargeNeed(soc=soc, target_soc=target, capacity_kwh=CAPACITY_KWH, charge_power_w=power_w)


class TestPlanFitsTheCheapestPeriod:
    def test_a_shallow_deficit_leaves_the_window_as_the_cheapest_period(self):
        window = plan_charge_window(_night_and_boost(), _need(soc=60, target=80))

        assert (window.start, window.end) == (time(2, 0), time(4, 0))
        assert window.extended is False

    def test_expected_energy_and_finish_time_come_from_the_deficit(self):
        window = plan_charge_window(_night_and_boost(), _need(soc=60, target=80))

        assert window.expected_kwh == pytest.approx(3.8)
        # 3.8 kWh at 3.6 kW is 63.3 minutes, rounded up to 64.
        assert window.finish_time == time(3, 4)

    def test_a_battery_already_at_the_target_expects_nothing(self):
        window = plan_charge_window(_night_and_boost(), _need(soc=90, target=88))

        assert window.extended is False
        assert window.expected_kwh == 0.0
        assert window.finish_time is None

    def test_the_margin_can_tip_a_plan_that_just_fits_into_an_extension(self):
        # 7.2 kWh at 3.6 kW is exactly the 120 minutes of the period. The margin needs more.
        soc = 50.0
        target = soc + 7.2 / CAPACITY_KWH * 100

        window = plan_charge_window(_night_and_boost(), _need(soc, target))

        assert window.extended is True


class TestPlanExtendsTheEnd:
    def test_a_deep_deficit_moves_the_end_into_the_night_band(self):
        window = plan_charge_window(_night_and_boost(), _need(soc=20, target=88))

        # 12.92 kWh at 3.6 kW is 215.3 minutes. With the margin, 247.6, rounded up to 250.
        assert window.start == time(2, 0)
        assert window.end == time(6, 10)
        assert window.extended is True

    def test_the_end_follows_the_margin_and_rounding_constants(self):
        need = _need(soc=20, target=88)
        minutes = need.deficit_kwh / need.charge_power_kw * 60 * (1 + CHARGE_WINDOW_MARGIN)
        step = CHARGE_WINDOW_ROUND_MINUTES

        window = plan_charge_window(_night_and_boost(), need)

        expected_minutes = -(-minutes // step) * step
        assert window.end == time(2 + int(expected_minutes) // 60, int(expected_minutes) % 60)

    def test_expected_energy_covers_the_whole_deficit_when_the_window_reaches_it(self):
        window = plan_charge_window(_night_and_boost(), _need(soc=20, target=88))

        assert window.expected_kwh == pytest.approx(12.92)
        # 12.92 kWh at 3.6 kW is 215.3 minutes after 02:00, rounded up to 216.
        assert window.finish_time == time(5, 36)

    def test_the_end_stops_where_the_cheaper_than_base_run_ends(self):
        # At 2 kW the plan needs far more than the 360 minutes from 02:00 to 08:00.
        window = plan_charge_window(_night_and_boost(), _need(soc=10, target=100, power_w=2000))

        assert window.end == time(8, 0)
        assert window.expected_kwh == pytest.approx(12.0)  # 2 kW for the 6 hours
        assert window.finish_time is None

    def test_a_deficit_the_period_just_misses_extends_by_a_small_step(self):
        window = plan_charge_window(_night_and_boost(), _need(soc=40, target=88))

        # 9.12 kWh at 3.6 kW is 152 minutes. With the margin, 174.8, rounded up to 175.
        assert window.end == time(4, 55)


class TestRunOfCheaperPeriods:
    def test_a_following_period_at_the_base_rate_is_not_part_of_the_run(self):
        tariff = _tariff(
            _period("Night", BASE_RATE, "23:00", "08:00"),
            _period("Nightboost", 0.0965, "02:00", "04:00"),
        )

        window = plan_charge_window(tariff, _need(soc=10, target=100))

        assert cheap_run_minutes(tariff) == 120
        assert (window.end, window.extended) == (time(4, 0), False)

    def test_a_following_period_dearer_than_the_base_rate_is_not_part_of_the_run(self):
        tariff = _tariff(
            _period("Peak", BASE_RATE + 0.05, "04:00", "08:00"),
            _period("Nightboost", 0.0965, "02:00", "04:00"),
        )

        assert cheap_run_minutes(tariff) == 120

    def test_no_period_after_the_cheapest_leaves_the_window_alone(self):
        tariff = _tariff(_period("Nightboost", 0.0965, "02:00", "04:00"))

        window = plan_charge_window(tariff, _need(soc=10, target=100))

        assert (window.start, window.end, window.extended) == (time(2, 0), time(4, 0), False)
        assert window.expected_kwh == pytest.approx(7.2)

    def test_a_gap_before_the_next_cheaper_period_ends_the_run(self):
        tariff = _tariff(
            _period("Nightboost", 0.0965, "02:00", "04:00"),
            _period("Morning", 0.2, "05:00", "07:00"),
        )

        assert cheap_run_minutes(tariff) == 120

    def test_overlapping_periods_chain_to_the_furthest_end(self):
        tariff = _tariff(
            _period("A", 0.08, "02:00", "04:00"),
            _period("B", 0.12, "03:00", "06:00"),
            _period("C", 0.15, "05:30", "08:00"),
        )

        assert cheap_run_minutes(tariff) == 6 * 60

    def test_the_run_never_ends_where_it_starts(self):
        tariff = _tariff(
            _period("Nightboost", 0.0965, "02:00", "03:00"),
            _period("Rest", 0.2, "03:00", "02:00"),
        )

        window = plan_charge_window(tariff, _need(soc=5, target=100, power_w=500))

        assert cheap_run_minutes(tariff) == 24 * 60 - 1
        assert window.end == time(1, 59)


class TestWrapPastMidnight:
    @staticmethod
    def _late_night():
        return _tariff(
            _period("Late", 0.15, "21:00", "07:00"),
            _period("Boost", 0.08, "23:00", "01:00"),
        )

    def test_the_end_wraps_past_midnight(self):
        window = plan_charge_window(self._late_night(), _need(soc=20, target=90))

        # 13.3 kWh at 3.6 kW is 221.7 minutes. With the margin, 255.
        assert window.start == time(23, 0)
        assert window.end == time(3, 15)
        assert window.extended is True

    def test_the_run_wraps_past_midnight_to_the_end_of_the_wider_period(self):
        tariff = self._late_night()

        assert cheap_run_minutes(tariff) == 8 * 60
        window = plan_charge_window(tariff, _need(soc=5, target=100, power_w=1500))
        assert window.end == time(7, 0)

    def test_the_finish_time_wraps_past_midnight(self):
        window = plan_charge_window(self._late_night(), _need(soc=20, target=90))

        # 221.7 minutes after 23:00, rounded up to 222, is 02:42.
        assert window.finish_time == time(2, 42)


class TestChargePowerUnknown:
    @pytest.mark.parametrize("power_w", [None, 0.0, -100.0])
    def test_no_extension_without_a_usable_charge_rate(self, power_w):
        window = plan_charge_window(_night_and_boost(), _need(soc=10, target=100, power_w=power_w))

        assert (window.start, window.end, window.extended) == (time(2, 0), time(4, 0), False)
        assert window.expected_kwh is None
        assert window.finish_time is None


DUBLIN = ZoneInfo("Europe/Dublin")


def _at(hour: int, minute: int = 0, second: int = 0, *, day: int = 15, month: int = 12, year: int = 2026):
    return datetime(year, month, day, hour, minute, second, tzinfo=DUBLIN)


class TestCheapRunRemaining:
    """Minutes from now to the end of the cheaper-than-base run now sits in."""

    def test_inside_the_inner_cheapest_period_the_run_ends_with_the_outer_one(self):
        assert cheap_run_remaining_minutes(_night_and_boost(), _at(2, 30)) == 5 * 60 + 30

    def test_inside_the_outer_period_only(self):
        tariff = _night_and_boost()
        assert cheap_run_remaining_minutes(tariff, _at(23, 30)) == 8 * 60 + 30
        assert cheap_run_remaining_minutes(tariff, _at(5, 0)) == 3 * 60

    def test_after_midnight_it_counts_to_the_morning(self):
        assert cheap_run_remaining_minutes(_night_and_boost(), _at(0, 10)) == 7 * 60 + 50

    def test_before_midnight_it_counts_past_midnight(self):
        tariff = _tariff(_period("Night", 0.1644, "23:00", "08:00"))
        assert cheap_run_remaining_minutes(tariff, _at(23, 15)) == 8 * 60 + 45

    def test_two_cheap_periods_with_a_base_rate_gap_end_at_the_first_gap(self):
        tariff = _tariff(
            _period("Night", 0.1644, "23:00", "08:00"),
            _period("Afternoon", 0.2, "13:00", "15:00"),
        )
        assert cheap_run_remaining_minutes(tariff, _at(13, 30)) == 90
        assert cheap_run_remaining_minutes(tariff, _at(23, 30)) == 8 * 60 + 30

    def test_cheap_periods_that_meet_make_one_run(self):
        tariff = _tariff(
            _period("Night", 0.1644, "23:00", "05:00"),
            _period("Early", 0.2, "05:00", "08:00"),
        )
        assert cheap_run_remaining_minutes(tariff, _at(23, 30)) == 8 * 60 + 30

    def test_a_single_cheap_period(self):
        tariff = _tariff(_period("Night", 0.1644, "01:00", "05:00"))
        assert cheap_run_remaining_minutes(tariff, _at(2, 0)) == 3 * 60

    def test_a_period_dearer_than_the_base_rate_does_not_extend_the_run(self):
        tariff = _tariff(
            _period("Night", 0.1644, "23:00", "08:00"),
            _period("Peak", 0.4, "08:00", "10:00"),
        )
        assert cheap_run_remaining_minutes(tariff, _at(7, 0)) == 60

    def test_the_seconds_into_the_minute_are_taken_off(self):
        assert cheap_run_remaining_minutes(_night_and_boost(), _at(2, 30, 30)) == 5 * 60 + 29.5

    def test_the_last_minute_of_the_run(self):
        assert cheap_run_remaining_minutes(_night_and_boost(), _at(7, 59)) == 1

    @pytest.mark.parametrize("now", [_at(8, 0), _at(12, 0), _at(22, 59)])
    def test_none_outside_a_cheap_run(self, now):
        assert cheap_run_remaining_minutes(_night_and_boost(), now) is None

    def test_none_on_a_tariff_with_no_timed_period(self):
        assert cheap_run_remaining_minutes(_tariff(), _at(2, 30)) is None

    def test_a_clock_change_inside_the_run_counts_real_time(self):
        """The clocks go forward at 01:00 on 28 March 2027, so the night has one hour fewer."""
        now = _at(23, 30, day=27, month=3, year=2027)
        assert cheap_run_remaining_minutes(_night_and_boost(), now) == 7 * 60 + 30
