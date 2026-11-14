# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The cheapest-plan search: windows, pricing every plan the same way and the current rank."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import (
    Locale,
    RatePeriod,
    SlotHistory,
    TariffConfig,
    definition_from_config,
    parse_definition,
)
from custom_components.givenergy_inverter_manager.lib.tariffranking import (
    Candidate,
    Unit,
    Usage,
    Window,
    needs_export_rate,
    price_ranges,
    ranges,
    rank_sentence,
    search,
    with_export_rate,
)
from tests.lib.tariff.example_definition import example_document
from tests.lib.tariff.test_reprice import _october_bill_days

DUBLIN = ZoneInfo("Europe/Dublin")
THROUGH = date(2026, 10, 15)


def _definition(**changes):  # type: ignore[no-untyped-def]
    fields = {
        "rate_periods": [RatePeriod("Night", 0.18, time(23, 0), time(8, 0))],
        "base_rate": 0.365,
        "base_rate_name": "Day",
        "export_rate": 0.195,
        "standing_charge": 0.8259,
        "pso_levy": 1.46,
        "vat_rate": 9.0,
        "discount_rate": 5.5,
        "bill_start_day": 16,
    }
    names = {"standing_charge_per_day": "standing_charge", "pso_levy_per_month": "pso_levy"}
    fields.update({names.get(key, key): value for key, value in changes.items()})
    return definition_from_config(
        TariffConfig(**fields), Locale("EUR", "IE", "Europe/Dublin", date(2000, 1, 1))
    )


def _candidate(key: str, **changes) -> Candidate:  # type: ignore[no-untyped-def]
    return Candidate(key, key.title(), _definition(**changes))


def _usage(window: Window, through: date = THROUGH) -> Usage:
    history = SlotHistory(DUBLIN)
    history._days = {day.day: day for day in _october_bill_days()}
    return Usage(history, ranges(window, through, 16))


def test_weeks_end_on_the_day_given() -> None:
    (span,) = ranges(Window(Unit.WEEKS, 2), THROUGH, 16)
    assert span.last == THROUGH
    assert (span.last - span.first).days == 13


def test_bills_are_the_whole_bills_before_the_open_one() -> None:
    spans = ranges(Window(Unit.BILLS, 2), date(2026, 10, 20), 16)
    assert [(s.first, s.last) for s in spans] == [
        (date(2026, 8, 16), date(2026, 9, 15)),
        (date(2026, 9, 16), date(2026, 10, 15)),
    ]
    assert spans[1].period_days == 30


def test_a_window_is_limited() -> None:
    with pytest.raises(ValueError, match="1 to"):
        Window(Unit.BILLS, 0)
    with pytest.raises(ValueError, match="1 to"):
        Window(Unit.WEEKS, 500)


def test_the_cheapest_plan_ranks_first_and_the_current_one_is_found() -> None:
    result = search(
        _usage(Window(Unit.WEEKS, 4)),
        _candidate("current"),
        [_candidate("dear", base_rate=0.9), _candidate("cheap", vat_rate=0.0)],
    )
    assert [r.key for r in result.ranked] == ["cheap", "current", "dear"]
    assert result.current_rank == 2
    assert result.ranked[1].difference == 0
    assert result.ranked[0].difference < 0 < result.ranked[2].difference


def test_a_copy_of_the_current_plan_ties_and_the_current_one_wins() -> None:
    result = search(
        _usage(Window(Unit.WEEKS, 4)), _candidate("current"), [_candidate("same")]
    )
    assert result.current_rank == 1


def test_a_plan_with_no_export_price_needs_a_rate_or_is_left_out() -> None:
    bare = _definition(export_rate=0.0)
    assert needs_export_rate(bare)
    usage = _usage(Window(Unit.WEEKS, 4))
    left_out = search(usage, _candidate("current"), [Candidate("bare", "Bare", bare)])
    assert left_out.skipped == 1 and left_out.compared == 1
    typed = search(
        usage, _candidate("current"), [Candidate("bare", "Bare", bare, Decimal("0.195"))]
    )
    assert typed.skipped == 0 and typed.compared == 2
    assert typed.ranked[typed.current_rank - 1].difference == 0 or typed.compared == 2


def test_the_current_plan_is_priced_as_saved_even_with_no_export_rate() -> None:
    bare = _definition(export_rate=0.0)
    result = search(
        _usage(Window(Unit.WEEKS, 4)), Candidate("current", "Current", bare), [_candidate("a")]
    )
    assert result.skipped == 0 and result.compared == 2


def test_a_typed_export_rate_prices_like_the_same_published_rate() -> None:
    bare = _definition(export_rate=0.0)
    assert with_export_rate(bare, Decimal("0.195")).export_prices.base.price == Decimal("0.195")
    paid = _definition()
    assert with_export_rate(paid, Decimal("9")) is paid
    usage = _usage(Window(Unit.WEEKS, 4))
    same = search(
        usage, _candidate("current"), [Candidate("bare", "Bare", bare, Decimal("0.195"))]
    )
    assert same.ranked[0].total == same.ranked[1].total


def test_the_data_the_window_holds_is_reported() -> None:
    usage = _usage(Window(Unit.BILLS, 1), date(2026, 10, 16))
    result = search(usage, _candidate("current"), [])
    assert result.days == 30
    assert result.days_recorded <= result.days
    assert result.data_from is None or result.data_from >= result.first_day
    assert result.last_day == result.first_day + timedelta(days=29)


def test_the_rank_is_said_in_words() -> None:
    base = search(
        _usage(Window(Unit.WEEKS, 4)),
        _candidate("current"),
        [_candidate("a", base_rate=0.05), _candidate("b", base_rate=0.04),
         _candidate("c", base_rate=0.01), _candidate("d", base_rate=0.02),
         _candidate("e", base_rate=0.03)],
    )
    assert base.current_rank == 6
    assert "number 6 of the 6" in rank_sentence(base)
    assert "above the cheapest" in rank_sentence(base)
    top = replace(base, current_rank=1)
    assert rank_sentence(top) == "Your plan is the cheapest of the 6 compared."
    third = replace(base, current_rank=3)
    assert "top 3" in rank_sentence(third)


def test_a_plan_with_banded_export_is_priced_by_band() -> None:
    doc = example_document()
    doc["export"]["zones"] = [
        {"name": "Peak export", "priority": 1, "price": "0.30", "hours": "12:00-14:00"}
    ]
    banded = parse_definition(doc)
    plain = _definition()
    usage = _usage(Window(Unit.WEEKS, 4))
    # The meter exports 47 kWh between 12:00 and 14:00, so the zone pays 0.30 and not 0.195.
    zoned = price_ranges(usage, banded)
    flat = price_ranges(usage, plain)
    assert zoned < flat
