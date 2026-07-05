"""
test_tariff.py — Unit tests for tariff.py.

Covers RatePeriod, TariffConfig (rate precedence, billing calculations,
cheapest rate), EnergyAccumulator, and _parse_rate_periods / _rate_periods_to_text
from config_flow.

Helpers (_nightboost_cfg, _raw, _run) are in conftest.py.
"""

from datetime import datetime, time

import pytest

from custom_components.givenergy_inverter_manager.core.tariff import (
    RatePeriod,
    TariffConfig,
    build_tariff,
)

# ── TariffConfig.get_cheapest_rate_start ──────────────────────────────────────


class TestGetCheapestRateStart:
    def test_returns_cheapest_timed_period_start(self):
        """get_cheapest_rate_start returns the start of the cheapest timed period."""
        tariff = build_tariff({})
        # Default config: Nightboost is cheapest (€0.0965), starts 02:00
        assert tariff.get_cheapest_rate_start() == time(2, 0)

    def test_raises_on_flat_rate_tariff(self):
        """Must raise ValueError when there are no timed periods."""
        tariff = TariffConfig(
            rate_periods=[],
            base_rate=0.3334,
            base_rate_name="Standard",
            export_rate=0.195,
            standing_charge=0.82,
            pso_levy=1.46,
            vat_rate=9.0,
            discount_rate=5.5,
            bill_start_day=16,
        )
        with pytest.raises(ValueError, match="flat-rate"):
            tariff.get_cheapest_rate_start()

    def test_base_rate_not_considered_for_start(self):
        """Base rate is excluded even when its rate value is lower than timed periods."""
        from custom_components.givenergy_inverter_manager.core.tariff import RatePeriod

        tariff = TariffConfig(
            rate_periods=[RatePeriod("Night", 0.1644, time(23, 0), time(8, 0))],
            base_rate=0.05,  # cheaper than Night — but has no real time window
            base_rate_name="FakeCheap",
            export_rate=0.195,
            standing_charge=0.82,
            pso_levy=1.46,
            vat_rate=9.0,
            discount_rate=5.5,
            bill_start_day=16,
        )
        # Must return Night's 23:00, not time(0,0) from the base rate
        assert tariff.get_cheapest_rate_start() == time(23, 0)


# ── Rate period precedence ────────────────────────────────────────────────────


class TestRatePeriodIsActive:
    def _dt(self, h, m=0):
        return datetime(2024, 6, 15, h, m)

    def test_normal_period_active_inside_window(self):
        p = RatePeriod("Day", 0.33, time(8, 0), time(23, 0))
        assert p.is_active(self._dt(12)) is True
        assert p.is_active(self._dt(8)) is True  # inclusive start
        assert p.is_active(self._dt(22, 59)) is True

    def test_normal_period_inactive_outside_window(self):
        p = RatePeriod("Day", 0.33, time(8, 0), time(23, 0))
        assert p.is_active(self._dt(7, 59)) is False
        assert p.is_active(self._dt(23)) is False  # exclusive end

    def test_overnight_period_active_after_start(self):
        p = RatePeriod("Night", 0.16, time(23, 0), time(8, 0))
        assert p.is_active(self._dt(23)) is True
        assert p.is_active(self._dt(23, 30)) is True
        assert p.is_active(self._dt(0)) is True
        assert p.is_active(self._dt(3)) is True
        assert p.is_active(self._dt(7, 59)) is True

    def test_overnight_period_inactive_during_day(self):
        p = RatePeriod("Night", 0.16, time(23, 0), time(8, 0))
        assert p.is_active(self._dt(8)) is False
        assert p.is_active(self._dt(12)) is False
        assert p.is_active(self._dt(22, 59)) is False

    def test_period_with_identical_start_end_never_active(self):
        """A period where start == end (00:00–00:00) never matches any time."""
        p = RatePeriod("Placeholder", 0.33, time(0, 0), time(0, 0))
        for h in range(24):
            assert p.is_active(datetime(2024, 6, 15, h, 0)) is False


class TestGetCurrentRatePrecedence:
    """
    The core test suite for rate period precedence.

    Tariff under test: Electric Ireland Home Electric + Nightboost
      Day        €0.3334  base rate (no times — covers all unscheduled hours)
      Night      €0.1644  23:00 – 08:00
      Nightboost €0.0965  02:00 – 04:00
    """

    def _nightboost_tariff(self):
        return TariffConfig(
            rate_periods=[
                RatePeriod("Night", 0.1644, time(23, 0), time(8, 0)),
                RatePeriod("Nightboost", 0.0965, time(2, 0), time(4, 0)),
            ],
            base_rate=0.3334,
            base_rate_name="Day",
            export_rate=0.195,
            standing_charge=0.8259,
            pso_levy=1.46,
            vat_rate=9.0,
            discount_rate=5.5,
            bill_start_day=16,
        )

    def _dt(self, h, m=0):
        return datetime(2024, 6, 15, h, m)

    # ── Day (base rate) ───────────────────────────────────────────────────────

    def test_day_rate_at_midday(self):
        t = self._nightboost_tariff()
        r = t.get_current_rate(self._dt(12))
        assert r.name == "Day"
        assert r.rate == pytest.approx(0.3334)

    def test_day_rate_at_8am_sharp(self):
        """Night ends at 08:00; base rate should take over from exactly 08:00."""
        t = self._nightboost_tariff()
        r = t.get_current_rate(self._dt(8))
        assert r.name == "Day"

    def test_day_rate_at_2259(self):
        """Last minute before Night starts — still Day."""
        t = self._nightboost_tariff()
        r = t.get_current_rate(self._dt(22, 59))
        assert r.name == "Day"

    # ── Night ─────────────────────────────────────────────────────────────────

    def test_night_rate_at_23(self):
        t = self._nightboost_tariff()
        r = t.get_current_rate(self._dt(23))
        assert r.name == "Night"

    def test_night_rate_at_midnight(self):
        t = self._nightboost_tariff()
        r = t.get_current_rate(self._dt(0))
        assert r.name == "Night"

    def test_night_rate_at_1am(self):
        t = self._nightboost_tariff()
        r = t.get_current_rate(self._dt(1))
        assert r.name == "Night"

    def test_night_rate_at_459(self):
        """After Nightboost ends, Night should resume."""
        t = self._nightboost_tariff()
        r = t.get_current_rate(self._dt(4))
        assert r.name == "Night"

    def test_night_rate_at_759(self):
        """Last minute of Night before 08:00."""
        t = self._nightboost_tariff()
        r = t.get_current_rate(self._dt(7, 59))
        assert r.name == "Night"

    # ── Nightboost ────────────────────────────────────────────────────────────

    def test_nightboost_overrides_night_at_2am(self):
        """Both Night and Nightboost are active at 02:00 — cheapest must win."""
        t = self._nightboost_tariff()
        r = t.get_current_rate(self._dt(2))
        assert r.name == "Nightboost"
        assert r.rate == pytest.approx(0.0965)

    def test_nightboost_at_3am(self):
        t = self._nightboost_tariff()
        r = t.get_current_rate(self._dt(3))
        assert r.name == "Nightboost"

    def test_nightboost_at_359(self):
        """Last minute of Nightboost."""
        t = self._nightboost_tariff()
        r = t.get_current_rate(self._dt(3, 59))
        assert r.name == "Nightboost"

    def test_nightboost_ends_at_4am(self):
        """04:00 is exclusive end of Nightboost — Night takes over again."""
        t = self._nightboost_tariff()
        r = t.get_current_rate(self._dt(4))
        assert r.name == "Night"

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_no_overlap_at_transition_23_to_00(self):
        """23:00 boundary — Night starts, Day (base) no longer applies."""
        t = self._nightboost_tariff()
        r = t.get_current_rate(self._dt(23))
        assert r.name == "Night"
        assert r.rate < 0.3334  # cheaper than day

    def test_base_rate_wins_over_empty_on_no_active_timed(self):
        """When no timed period is active, base rate is returned."""
        tariff = TariffConfig(
            rate_periods=[RatePeriod("Night", 0.15, time(23, 0), time(6, 0))],
            base_rate=0.30,
            base_rate_name="Standard",
            export_rate=0.195,
            standing_charge=0.82,
            pso_levy=1.46,
            vat_rate=9.0,
            discount_rate=0.0,
            bill_start_day=1,
        )
        r = tariff.get_current_rate(datetime(2024, 6, 15, 12, 0))
        assert r.name == "Standard"

    def test_base_rate_is_single_scalar(self):
        """Base rate is a single scalar — always returned when no timed period matches."""
        tariff = TariffConfig(
            rate_periods=[RatePeriod("Night", 0.15, time(23, 0), time(6, 0))],
            base_rate=0.30,
            base_rate_name="Standard",
            export_rate=0.195,
            standing_charge=0.82,
            pso_levy=1.46,
            vat_rate=9.0,
            discount_rate=0.0,
            bill_start_day=1,
        )
        r = tariff.get_current_rate(datetime(2024, 6, 15, 12, 0))
        assert r.name == "Standard"
        assert r.rate == pytest.approx(0.30)

    def test_gap_in_timed_periods_falls_back_to_base_rate(self):
        """When there is a gap between timed periods, the base rate fills it."""
        tariff = TariffConfig(
            rate_periods=[
                RatePeriod("Evening", 0.40, time(17, 0), time(21, 0)),
                RatePeriod("Night", 0.15, time(23, 0), time(6, 0)),
            ],
            base_rate=0.30,
            base_rate_name="Standard",
            export_rate=0.195,
            standing_charge=0.82,
            pso_levy=1.46,
            vat_rate=9.0,
            discount_rate=0.0,
            bill_start_day=1,
        )
        # 22:00 is a gap: neither Evening nor Night is active
        r = tariff.get_current_rate(datetime(2024, 6, 15, 22, 0))
        assert r.name == "Standard"
        assert r.rate == pytest.approx(0.30)

    def test_full_24h_coverage_with_nightboost(self):
        """Every hour should return exactly one rate — no hour is uncovered."""
        t = self._nightboost_tariff()
        for h in range(24):
            r = t.get_current_rate(datetime(2024, 6, 15, h, 0))
            assert r.name in ("Day", "Night", "Nightboost"), (
                f"Unexpected rate at {h:02d}:00 — got {r.name!r}"
            )

    def test_rate_ordering_across_24_hours(self):
        """Verify the correct rate is returned for every hour of the day."""
        t = self._nightboost_tariff()
        expected = {
            # (hour, expected_name)
            **dict.fromkeys(range(8, 23), "Day"),
            **dict.fromkeys([23, 0, 1, 4, 5, 6, 7], "Night"),
            **dict.fromkeys([2, 3], "Nightboost"),
        }
        for h, name in expected.items():
            r = t.get_current_rate(datetime(2024, 6, 15, h, 0))
            assert r.name == name, f"At {h:02d}:00: expected {name!r}, got {r.name!r}"
