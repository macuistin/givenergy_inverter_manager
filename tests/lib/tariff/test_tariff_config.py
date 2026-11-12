# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The tariff from typed fields: the rate in force, the next cheap period, costs and the bill
period. Round figures chosen by the test, no supplier's. Each expected value is worked beside it."""

from __future__ import annotations

from datetime import datetime, time, timezone

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import (
    RatePeriod,
    TariffConfig,
)
from custom_components.givenergy_inverter_manager.lib.tariff.config import cheapest_period

UTC = timezone.utc


def _tariff(**changes) -> TariffConfig:
    fields = {
        "rate_periods": [
            RatePeriod("Night", 0.16, time(23, 0), time(8, 0)),
            RatePeriod("Boost", 0.09, time(2, 0), time(4, 0)),
        ],
        "base_rate": 0.33,
        "base_rate_name": "Day",
        "export_rate": 0.19,
        "standing_charge": 0.80,
        "pso_levy": 1.50,
        "vat_rate": 10.0,
        "discount_rate": 5.0,
        "bill_start_day": 16,
    }
    return TariffConfig(**{**fields, **changes})


def _at(hour: int, day: int = 15, month: int = 6, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=UTC)


def test_the_cheapest_rate_is_the_lowest_of_the_timed_periods_and_the_base_rate():
    assert _tariff().get_cheapest_rate().name == "Boost"
    assert cheapest_period(_tariff()).name == "Boost"
    assert _tariff(rate_periods=[]).get_cheapest_rate().name == "Day"


def test_the_cheapest_timed_period_gives_the_start_of_cheap_energy():
    assert _tariff().get_cheapest_rate_start() == time(2, 0)


def test_a_flat_tariff_has_no_cheap_start():
    with pytest.raises(ValueError, match="flat-rate"):
        _tariff(rate_periods=[]).get_cheapest_rate_start()


def test_the_next_cheap_period_is_the_soonest_start_today_or_tomorrow():
    # At 12:00 Night starts in 11 hours. Boost began at 02:00 today, so its next start is 14
    # hours away, tomorrow.
    assert _tariff().next_cheap_rate(_at(12)) == (11.0, "23:00")


def test_inside_a_cheap_period_nothing_is_left_to_wait():
    assert _tariff().next_cheap_rate(_at(3)) == (0.0, None)


def test_a_tariff_with_no_period_under_the_base_rate_has_no_next_cheap_period():
    assert _tariff(rate_periods=[]).next_cheap_rate(_at(12)) is None
    peak = [RatePeriod("Peak", 0.50, time(17, 0), time(19, 0))]
    assert _tariff(rate_periods=peak).next_cheap_rate(_at(12)) is None


def test_import_cost_takes_the_discount_then_adds_vat():
    tariff = _tariff()
    # 10 kWh at the 0.33 day rate, less 5%, plus 10% VAT: 10 x 0.33 x 0.95 x 1.10.
    assert tariff.calculate_import_cost(10.0, _at(12)) == pytest.approx(3.4485)
    assert tariff.effective_import_rate(0.20) == pytest.approx(0.209)  # 0.20 x 0.95 x 1.10
    assert tariff.energy_cost_from_import_cost(3.4485) == pytest.approx(3.30)


def test_a_full_discount_leaves_no_energy_cost_to_recover():
    assert _tariff(discount_rate=100.0).energy_cost_from_import_cost(5.0) == 0.0


def test_export_earns_the_export_rate_with_no_vat():
    assert _tariff().calculate_export_earnings(10.0) == pytest.approx(1.90)


def test_a_bill_for_a_whole_period_is_added_up_line_by_line():
    bill = _tariff().calculate_bill(100.0, 30, period_days=30, export_credit=5.0)

    assert bill.energy == 100.00
    assert bill.supplier_saving == 5.00  # 5% of the energy
    assert bill.standing_charge == 24.00  # 30 days at 0.80
    assert bill.pso_levy == 1.50  # the whole month's levy
    assert bill.vat == 12.05  # 10% of 100 - 5 + 24 + 1.50 = 120.50
    assert bill.export_credit == 5.00
    assert bill.total == 127.55  # 120.50 + 12.05 - 5.00


def test_part_of_a_period_carries_its_share_of_the_monthly_levy():
    assert _tariff().calculate_bill(0.0, 15, period_days=30).pso_levy == 0.75
    # More days than the period never carries more than one levy.
    assert _tariff().calculate_bill(0.0, 40, period_days=30).pso_levy == 1.50


def test_with_no_period_length_the_levy_is_shared_over_an_average_month():
    # 30 days of a 30.44 day average month: 1.50 x 30 / 30.44 = 1.478, which rounds to 1.48.
    assert _tariff().calculate_bill(0.0, 30).pso_levy == 1.48


def test_the_bill_period_runs_from_the_start_day_to_the_next_one():
    tariff = _tariff()
    after_start = _at(12, day=20, month=11)  # 16 November to 16 December
    assert tariff.days_in_bill_period(after_start) == 30
    assert tariff.days_in_current_bill_period(after_start) == 5
    assert tariff.days_remaining_in_bill_period(after_start) == 25

    before_start = _at(12, day=10, month=11)  # 16 October to 16 November
    assert tariff.days_in_bill_period(before_start) == 31
    assert tariff.days_in_current_bill_period(before_start) == 26
    assert tariff.days_remaining_in_bill_period(before_start) == 5


def test_the_bill_period_crosses_the_year_end_in_both_directions():
    tariff = _tariff()
    assert tariff.days_in_bill_period(_at(12, day=20, month=12)) == 31  # 16 Dec to 16 Jan
    january = _at(12, day=10, month=1, year=2027)
    assert tariff.days_in_bill_period(january) == 31
    assert tariff.days_in_current_bill_period(january) == 26


def test_a_start_day_past_the_end_of_a_month_uses_its_last_day():
    tariff = _tariff(bill_start_day=31)
    february = _at(12, day=10, month=2)  # 31 January to 28 February 2026

    assert tariff.days_in_bill_period(february) == 28
    assert tariff.days_in_current_bill_period(february) == 11


def test_prices_that_include_vat_add_none_to_the_import_cost():
    tariff = _tariff(vat_included=True)
    # 10 kWh at 0.33 less 5%: the 10% VAT is already inside the price, so nothing is added.
    assert tariff.calculate_import_cost(10.0, _at(12)) == pytest.approx(3.135)
    assert tariff.effective_import_rate(0.20) == pytest.approx(0.19)
    assert tariff.energy_cost_from_import_cost(3.135) == pytest.approx(3.30)


def test_a_bill_with_vat_included_reports_the_vat_inside_the_total():
    bill = _tariff(vat_included=True).calculate_bill(100.0, 30, period_days=30, export_credit=5.0)

    # 100 - 5 + 24 + 1.50 = 120.50 is the whole charge. The VAT inside it is 120.50 x 10 / 110.
    assert bill.vat == 10.95
    assert bill.total == 115.5  # 120.50 - 5.00 export credit, with nothing added
