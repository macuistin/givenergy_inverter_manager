# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""A bill period priced from the slot history agrees with the existing bill to the cent."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import (
    Locale,
    PeriodRules,
    SlotHistory,
    bill_period_bounds,
    definition_from_config,
    months_of,
    parse_definition,
    price_period,
    start_day_of,
    start_month_of,
)
from tests.lib.tariff.example_definition import example_document
from tests.lib.tariff.test_reprice import _october_bill_days, _tariff

DUBLIN = ZoneInfo("Europe/Dublin")
LOCALE = Locale("EUR", "IE", "Europe/Dublin", date(2026, 1, 1))


def _history(days) -> SlotHistory:
    # Stored days round to whole watt-hours, which would move the meter's kWh by a few tenths.
    history = SlotHistory(DUBLIN)
    history._days = {day.day: day for day in days}
    return history


def test_the_october_bill_is_reproduced_to_the_cent() -> None:
    definition = definition_from_config(_tariff(), LOCALE)
    bill = price_period(_history(_october_bill_days()), definition, date(2026, 10, 15))
    assert (bill.first_day, bill.next_first_day) == (date(2026, 9, 16), date(2026, 10, 16))
    assert (bill.days, bill.period_days) == (30, 30)
    assert bill.data_from == date(2026, 9, 16)
    assert bill.coverage == 1.0
    assert bill.priced.total == Decimal("187.35")


def test_the_active_tariff_agrees_with_the_existing_bill_for_part_of_a_period() -> None:
    tariff = _tariff()
    days = _october_bill_days()[:10]
    through = days[-1].day
    bill = price_period(_history(days), definition_from_config(tariff, LOCALE), through)
    kwh = {"Boost": 257 / 3, "Night": 619 / 3, "Day": 67 / 3}
    rates = {p.name: p.rate for p in tariff.rate_periods} | {"Day": tariff.base_rate}
    from custom_components.givenergy_inverter_manager.lib.tariff.billing import money

    cost = sum(money(v * rates[k]) for k, v in kwh.items())
    old = tariff.calculate_bill(cost, 10, 30, tariff.calculate_export_earnings(47 / 3))
    assert (bill.days, bill.period_days) == (10, 30)
    assert float(bill.priced.total) == pytest.approx(old.total, abs=0.01)


def test_another_tariff_is_priced_over_the_same_days() -> None:
    flat = definition_from_config(_tariff(rate_periods=[], base_rate=0.25), LOCALE)
    active = definition_from_config(_tariff(), LOCALE)
    history = _history(_october_bill_days())
    through = date(2026, 10, 15)
    assert price_period(history, flat, through).priced.total != price_period(
        history, active, through
    ).priced.total


def test_the_start_day_can_follow_another_tariff() -> None:
    definition = definition_from_config(_tariff(bill_start_day=1), LOCALE)
    assert start_day_of(definition) == 1
    bill = price_period(_history(_october_bill_days()), definition, date(2026, 10, 15), PeriodRules(start_day=16))
    assert bill.first_day == date(2026, 9, 16)


def test_days_without_history_are_in_the_bill_but_lower_the_coverage() -> None:
    definition = definition_from_config(_tariff(), LOCALE)
    days = _october_bill_days()[10:]
    bill = price_period(_history(days), definition, date(2026, 10, 15))
    assert bill.days == 30
    assert bill.data_from == date(2026, 9, 26)
    assert bill.coverage == pytest.approx(20 / 30)


def test_no_history_is_a_bill_with_standing_charges_only() -> None:
    definition = definition_from_config(_tariff(), LOCALE)
    bill = price_period(SlotHistory(DUBLIN), definition, date(2026, 10, 15))
    assert bill.data_from is None
    assert bill.coverage == 0.0
    assert bill.priced.total > 0


@pytest.mark.parametrize(
    ("start_day", "on", "expected"),
    [
        (16, date(2026, 10, 15), (date(2026, 9, 16), date(2026, 10, 16))),
        (16, date(2026, 10, 16), (date(2026, 10, 16), date(2026, 11, 16))),
        (16, date(2026, 1, 3), (date(2025, 12, 16), date(2026, 1, 16))),
        (16, date(2026, 12, 20), (date(2026, 12, 16), date(2027, 1, 16))),
        (1, date(2026, 2, 28), (date(2026, 2, 1), date(2026, 3, 1))),
    ],
)
def test_bill_period_bounds(start_day: int, on: date, expected: tuple[date, date]) -> None:
    assert bill_period_bounds(start_day, on) == expected
    assert expected[0] <= on < expected[1]
    assert (expected[1] - expected[0]) > timedelta(days=27)


@pytest.mark.parametrize(
    ("cycle", "on", "expected"),
    [
        # Two months, starting in odd months.
        ((1, 2, 1), date(2026, 2, 28), (date(2026, 1, 1), date(2026, 3, 1))),
        ((1, 2, 1), date(2026, 3, 1), (date(2026, 3, 1), date(2026, 5, 1))),
        # Two months, starting in even months, across the new year.
        ((16, 2, 2), date(2026, 1, 3), (date(2025, 12, 16), date(2026, 2, 16))),
        ((16, 2, 2), date(2026, 12, 15), (date(2026, 10, 16), date(2026, 12, 16))),
        ((16, 2, 12), date(2026, 12, 16), (date(2026, 12, 16), date(2027, 2, 16))),
        # A quarter that starts in February, May, August and November.
        ((10, 3, 2), date(2026, 5, 9), (date(2026, 2, 10), date(2026, 5, 10))),
        ((10, 3, 11), date(2026, 5, 10), (date(2026, 5, 10), date(2026, 8, 10))),
        # A year from April.
        ((6, 12, 4), date(2026, 4, 5), (date(2025, 4, 6), date(2026, 4, 6))),
        ((6, 12, 4), date(2026, 4, 6), (date(2026, 4, 6), date(2027, 4, 6))),
    ],
)
def test_bill_period_bounds_for_longer_periods(
    cycle: tuple[int, int, int], on: date, expected: tuple[date, date]
) -> None:
    start_day, months, start_month = cycle
    assert bill_period_bounds(start_day, on, months, start_month) == expected
    assert expected[0] <= on < expected[1]


@pytest.mark.parametrize("months", [0, 5, 24])
def test_a_period_length_that_does_not_divide_a_year_is_refused(months: int) -> None:
    with pytest.raises(ValueError, match="divide a year"):
        bill_period_bounds(1, date(2026, 1, 1), months)


def _two_monthly() -> dict:
    doc = example_document()
    del doc["checks"]
    doc["completeness"] = "partial"
    doc["bill"]["period"].update(start_day=16, months=2, start_month=8)
    doc["bill"]["total"]["of"]["charges"]["of"]["of"]["levy"]["per"] = "month"
    return doc


def test_a_two_monthly_bill_is_priced_from_the_history() -> None:
    definition = parse_definition(_two_monthly())
    assert (start_day_of(definition), months_of(definition), start_month_of(definition)) == (16, 2, 8)
    bill = price_period(_history(_october_bill_days()), definition, date(2026, 10, 15))
    assert (bill.first_day, bill.next_first_day) == (date(2026, 8, 16), date(2026, 10, 16))
    assert (bill.days, bill.period_days) == (61, 61)
    assert bill.data_from == date(2026, 9, 16)
    levy = bill.priced.root.children["charges"].children["of"].children["levy"]
    assert levy.amount == Decimal("2.92")  # 1.46 for each of the two months


def test_the_period_length_can_follow_another_tariff() -> None:
    definition = parse_definition(_two_monthly())
    rules = PeriodRules(start_day=1, months=3, start_month=10)
    bill = price_period(SlotHistory(DUBLIN), definition, date(2026, 10, 15), rules)
    assert (bill.first_day, bill.next_first_day) == (date(2026, 10, 1), date(2027, 1, 1))
    levy = bill.priced.root.children["charges"].children["of"].children["levy"]
    assert levy.amount == Decimal("0.71")  # 1.46 * 3 months * 15 days / 92 days
