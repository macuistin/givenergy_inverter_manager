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
    price_period,
    start_day_of,
)
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
