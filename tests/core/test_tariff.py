"""
test_tariff.py — Unit tests for tariff.py.

Covers RatePeriod, TariffConfig (rate precedence, billing calculations,
cheapest rate), EnergyAccumulator, and _parse_rate_periods / _rate_periods_to_text
from config_flow.

Helpers (_nightboost_cfg, _raw, _run) are in conftest.py.
"""

from datetime import datetime, time, timedelta

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


# ── TariffConfig — additional coverage ───────────────────────────────────────


# ── EnergyAccumulator — total_cost and net_position ─────────────────────────


class TestEnergyAccumulatorFinancials:
    def _acc(self):
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        acc = EnergyAccumulator()
        acc.import_cost_by_period["Day"] = 1.50
        acc.import_cost_by_period["Night"] = 0.80
        acc.export_earnings = 0.45
        return acc

    def test_total_cost_sums_all_periods(self):
        acc = self._acc()
        assert acc.total_cost == pytest.approx(2.30)

    def test_net_position_negative_when_cost_exceeds_earnings(self):
        acc = self._acc()
        assert acc.net_position == pytest.approx(0.45 - 2.30)

    def test_net_position_positive_when_earnings_exceed_cost(self):
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        acc = EnergyAccumulator()
        acc.export_earnings = 5.00
        acc.import_cost_by_period["Day"] = 1.00
        assert acc.net_position == pytest.approx(4.00)


# ── Billing period calendar ───────────────────────────────────────────────────


def _bill_tariff(start_day=16, pso=1.46):
    return TariffConfig(
        rate_periods=[
            RatePeriod("Night", 0.18, time(23, 0), time(8, 0)),
            RatePeriod("Nightboost", 0.1056, time(2, 0), time(4, 0)),
        ],
        base_rate=0.365,
        base_rate_name="Day",
        export_rate=0.195,
        standing_charge=0.8259,
        pso_levy=pso,
        vat_rate=9.0,
        discount_rate=5.5,
        bill_start_day=start_day,
    )


class TestBillPeriodCalendar:
    @pytest.mark.parametrize(
        ("start_day", "day", "elapsed", "remaining"),
        [
            (1, datetime(2026, 10, 1, 9), 1, 30),
            (1, datetime(2026, 10, 15, 9), 15, 16),
            (1, datetime(2026, 10, 31, 23, 59), 31, 0),
            (1, datetime(2026, 11, 1, 0, 0), 1, 29),
            (1, datetime(2026, 2, 1, 9), 1, 27),
            (1, datetime(2026, 2, 28, 9), 28, 0),
            (1, datetime(2028, 2, 29, 9), 29, 0),
            (16, datetime(2026, 8, 16, 0, 0), 1, 30),
            (16, datetime(2026, 9, 15, 23, 59), 31, 0),
            (16, datetime(2026, 9, 16, 9), 1, 29),
            (16, datetime(2026, 10, 15, 9), 30, 0),
            (16, datetime(2026, 2, 10, 9), 26, 5),
            (16, datetime(2026, 2, 16, 9), 1, 27),
            (16, datetime(2026, 3, 15, 9), 28, 0),
            (16, datetime(2026, 12, 31, 9), 16, 15),
            (16, datetime(2027, 1, 5, 9), 21, 10),
            (16, datetime(2027, 1, 15, 9), 31, 0),
            (16, datetime(2027, 1, 16, 9), 1, 30),
            (28, datetime(2026, 3, 1, 9), 2, 26),
            (28, datetime(2026, 2, 28, 9), 1, 27),
            (28, datetime(2028, 3, 1, 9), 3, 26),
        ],
    )
    def test_day_of_period_and_remaining(self, start_day, day, elapsed, remaining):
        t = _bill_tariff(start_day)
        assert t.days_in_current_bill_period(day) == elapsed
        assert t.days_remaining_in_bill_period(day) == remaining

    @pytest.mark.parametrize("start_day", [1, 2, 15, 16, 27, 28])
    def test_elapsed_plus_remaining_is_the_period_length_every_day(self, start_day):
        t = _bill_tariff(start_day)
        day = datetime(2026, 1, 1, 12)
        previous = None
        for offset in range(3 * 366):
            now = day + timedelta(days=offset)
            elapsed = t.days_in_current_bill_period(now)
            remaining = t.days_remaining_in_bill_period(now)
            length = t.days_in_bill_period(now)
            assert elapsed >= 1
            assert remaining >= 0
            assert elapsed + remaining == length
            assert 28 <= length <= 31
            if previous is not None:
                assert elapsed in (previous + 1, 1)
                assert (elapsed == 1) == (now.day == start_day)
            previous = elapsed

    def test_start_day_is_day_one(self):
        t = _bill_tariff(16)
        assert t.days_in_current_bill_period(datetime(2026, 8, 16, 0, 0)) == 1
        assert t.days_in_bill_period(datetime(2026, 8, 16, 0, 0)) == 31


# ── Standing charge and PSO levy ──────────────────────────────────────────────


class TestPsoLevyShare:
    """The PSO levy is a flat monthly figure, charged pro rata for a part period."""

    @pytest.mark.parametrize("period_days", [28, 29, 30, 31])
    def test_full_period_charges_exactly_the_monthly_pso(self, period_days):
        t = _bill_tariff()
        bill = t.calculate_bill(0.0, period_days, period_days)
        assert bill.pso_levy == 1.46
        assert bill.standing_charge == pytest.approx(round(0.8259 * period_days, 2))

    def test_part_period_charges_pro_rata_share_of_actual_period_length(self):
        t = _bill_tariff()
        assert t.calculate_bill(0.0, 10, 31).pso_levy == round(1.46 * 10 / 31, 2)
        assert t.calculate_bill(0.0, 10, 28).pso_levy == round(1.46 * 10 / 28, 2)

    def test_without_period_length_pso_never_exceeds_one_levy(self):
        t = _bill_tariff(pso=1.46)
        assert t.calculate_bill(0.0, 31).pso_levy == 1.46
        assert t.calculate_bill(0.0, 45).pso_levy == 1.46


# ── Bill breakdown: owner's real bill ─────────────────────────────────────────


class TestGoldenBill:
    """16 Aug to 15 Sep 2026, 31 days, the owner's real bill."""

    def _energy(self):
        return 154 * 0.1056 + 33 * 0.365 + 517 * 0.18

    def test_lines_match_the_bill(self):
        t = _bill_tariff(16)
        now = datetime(2026, 9, 15, 20, 0)
        bill = t.calculate_bill(
            self._energy(),
            t.days_in_current_bill_period(now),
            t.days_in_bill_period(now),
            179 * 0.195,
        )
        assert bill.energy == 121.37
        assert bill.supplier_saving == 6.68
        assert bill.standing_charge == 25.60
        assert bill.pso_levy == 1.46
        assert bill.before_vat == 141.75
        assert bill.vat == 12.76
        assert bill.export_credit == 34.91
        assert bill.total == 119.60

    def test_energy_cost_round_trips_through_accumulated_import_cost(self):
        t = _bill_tariff(16)
        import_cost = self._energy() * (1 - 0.055) * 1.09
        assert t.energy_cost_from_import_cost(import_cost) == pytest.approx(self._energy())

    def test_export_credit_has_no_vat_and_comes_off_after_vat(self):
        t = _bill_tariff(16)
        no_export = t.calculate_bill(100.0, 31, 31, 0.0)
        with_export = t.calculate_bill(100.0, 31, 31, 10.0)
        assert with_export.vat == no_export.vat
        assert with_export.total == pytest.approx(no_export.total - 10.0)

    def test_zero_discount_gives_no_saving(self):
        t = TariffConfig(**{**_bill_tariff().__dict__, "discount_rate": 0.0})
        assert t.calculate_bill(100.0, 31, 31).supplier_saving == 0.0


# ── Zero-length and malformed rate periods ────────────────────────────────────


class TestBuildTariffSkipsInvalidPeriods:
    def _cfg(self, periods):
        return {"rate_periods": periods, "base_rate": 0.365}

    def test_zero_length_period_is_skipped_with_warning(self, caplog):
        cfg = self._cfg(
            [
                {"name": "Night", "rate": 0.18, "start": "23:00", "end": "08:00"},
                {"name": "Empty", "rate": 0.01, "start": "00:00", "end": "00:00"},
            ]
        )
        with caplog.at_level("WARNING"):
            t = build_tariff(cfg)
        assert [p.name for p in t.rate_periods] == ["Night"]
        assert any("Empty" in r.message for r in caplog.records)

    def test_zero_length_period_is_not_the_cheapest_rate(self):
        cfg = self._cfg(
            [
                {"name": "Night", "rate": 0.18, "start": "23:00", "end": "08:00"},
                {"name": "Empty", "rate": 0.01, "start": "12:00", "end": "12:00"},
            ]
        )
        t = build_tariff(cfg)
        assert t.get_cheapest_rate().name == "Night"
        assert t.get_cheapest_rate_start() == time(23, 0)

    def test_only_zero_length_periods_leaves_a_flat_tariff(self):
        t = build_tariff(
            self._cfg([{"name": "Empty", "rate": 0.01, "start": "00:00", "end": "00:00"}])
        )
        assert t.rate_periods == []
        assert t.get_cheapest_rate().rate == pytest.approx(0.365)

    def test_malformed_period_is_still_skipped(self):
        t = build_tariff(self._cfg([{"name": "Bad", "rate": "x", "start": "1", "end": "2"}]))
        assert t.rate_periods == []
