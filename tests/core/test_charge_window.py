"""Unit tests for core/charge_window.py: the charge window sized to the plan."""

from __future__ import annotations

from datetime import time

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CHARGE_WINDOW_MARGIN,
    CHARGE_WINDOW_ROUND_MINUTES,
)
from custom_components.givenergy_inverter_manager.core.charge_window import (
    ChargeNeed,
    cheap_run_minutes,
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
