# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""Demand charges: a price on the highest half-hour kW in a window."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from typing import Any

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import (
    BillInputs,
    DefinitionError,
    MissingPeak,
    SlotDay,
    parse_definition,
    peak_kw_by_window,
    price_bill,
    verify_checks,
)
from custom_components.givenergy_inverter_manager.lib.tariff.definition import Demand
from tests.lib.tariff.example_definition import example_document
from tests.lib.tariff.test_bands import DUBLIN

D = Decimal


def peak_node(**changes: Any) -> dict[str, Any]:
    node = {"kind": "demand", "window": "peak", "price": "10.00", "per": "month",
            "hours": "16:00-20:00", "days": ["mon", "tue", "wed", "thu", "fri"]}
    node.update(changes)
    return node


def doc_with(*nodes: dict[str, Any]) -> dict[str, Any]:
    doc = example_document()
    doc["bill"]["total"] = {"kind": "sum", "of": {f"d{i}": n for i, n in enumerate(nodes)}}
    doc.pop("checks")
    doc["completeness"] = "partial"
    return doc


def total(doc: dict[str, Any], peak: dict[str, str], period: dict | None = None) -> Any:
    if period:
        doc["bill"]["period"] = period
    inputs = BillInputs(30, 30, {}, D(0), peak_kw={k: D(v) for k, v in peak.items()})
    return price_bill(parse_definition(doc), inputs)


def test_the_charge_is_the_price_times_the_peak() -> None:
    assert total(doc_with(peak_node()), {"peak": "4.5"}).total == D("45.00")


def test_a_monthly_price_is_charged_for_each_month_of_the_period() -> None:
    period = {"rule": "monthly", "start_day": 1, "months": 2}
    assert total(doc_with(peak_node()), {"peak": "4"}, period).total == D("80.00")
    flat = peak_node(per="period")
    assert total(doc_with(flat), {"peak": "4"}, period).total == D("40.00")


def test_a_peak_that_is_not_given_is_refused() -> None:
    with pytest.raises(MissingPeak, match="peak"):
        total(doc_with(peak_node()), {"other": "1"})


def test_two_windows_each_use_their_own_peak() -> None:
    whole_day = {"kind": "demand", "window": "any_time", "price": "2"}
    priced = total(doc_with(peak_node(), whole_day), {"peak": "3", "any_time": "5"})
    assert priced.total == D("40.00")  # 3 x 10 + 5 x 2


def test_a_check_can_carry_the_peak() -> None:
    doc = doc_with(peak_node())
    doc["completeness"] = "complete"
    doc["checks"] = {"month": {"period_days": 30, "import_kwh_by_band": {}, "export_kwh": "0",
                               "peak_kw": {"peak": "4.5"}, "expected_total": "45.00"}}
    verify_checks(parse_definition(doc))


def test_a_check_cannot_name_a_window_the_tree_lacks() -> None:
    doc = doc_with(peak_node())
    doc["completeness"] = "complete"
    doc["checks"] = {"month": {"period_days": 30, "import_kwh_by_band": {}, "export_kwh": "0",
                               "peak_kw": {"nowhere": "4.5"}, "expected_total": "0"}}
    with pytest.raises(DefinitionError, match="not a demand window"):
        parse_definition(doc)


def test_a_window_without_hours_is_the_whole_day() -> None:
    node = parse_definition(doc_with({"kind": "demand", "window": "all", "price": "1"})).total
    demand = node.children["d0"]
    assert isinstance(demand, Demand) and demand.when.start == demand.when.end == time(0, 0)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"window": "Peak"}, "not a valid name"),
        ({"price": "-1"}, "0 or more"),
        ({"per": "day"}, "must be one of"),
        ({"hours": "16:00-16:00"}, "same time"),
        ({"hours": "4pm"}, "HH:MM-HH:MM"),
        ({"days": ["funday"]}, "distinct values"),
        ({"extra": "1"}, "not a known field"),
    ],
)
def test_a_bad_demand_node_is_refused(change: dict[str, Any], message: str) -> None:
    with pytest.raises(DefinitionError, match=message):
        parse_definition(doc_with(peak_node(**change)))


def test_one_window_name_cannot_mean_two_windows() -> None:
    other = peak_node(hours="17:00-21:00")
    with pytest.raises(DefinitionError, match="two different windows"):
        parse_definition(doc_with(peak_node(), other))


def test_the_same_window_may_be_used_twice() -> None:
    parse_definition(doc_with(peak_node(), peak_node(price="1")))


def slot_day(day: date, loads: dict[int, float]) -> SlotDay:
    slots = SlotDay(day, DUBLIN)
    for index, kwh in loads.items():
        slots.flows["import"][index] = kwh
    return slots


def test_the_peak_is_the_highest_half_hour_in_the_window() -> None:
    definition = parse_definition(doc_with(peak_node(), {"kind": "demand", "window": "any",
                                                         "price": "1"}))
    # Monday 2 November 2026. Slot 34 is 17:00. 1.2 kWh in half an hour is 2.4 kW.
    monday = slot_day(date(2026, 11, 2), {34: 1.2, 35: 0.8, 6: 3.0})  # 06:00 is outside
    peaks = peak_kw_by_window([monday], definition)
    assert peaks == {"peak": D("2.4"), "any": D("6.0")}


def test_a_slot_outside_the_days_does_not_count() -> None:
    definition = parse_definition(doc_with(peak_node()))
    saturday = slot_day(date(2026, 11, 7), {34: 2.0})
    assert peak_kw_by_window([saturday], definition) == {"peak": D("0")}


def test_a_peak_is_found_over_several_days() -> None:
    definition = parse_definition(doc_with(peak_node()))
    days = [slot_day(date(2026, 11, 2), {34: 0.5}), slot_day(date(2026, 11, 3), {33: 1.5})]
    assert peak_kw_by_window(days, definition) == {"peak": D("3.0")}


def test_a_window_that_runs_past_midnight_belongs_to_the_day_it_starts() -> None:
    node = peak_node(hours="22:00-02:00", days=["fri"])
    definition = parse_definition(doc_with(node))
    friday_night = slot_day(date(2026, 11, 6), {46: 1.0})  # 23:00
    saturday_early = slot_day(date(2026, 11, 7), {2: 1.5})  # 01:00, still Friday's window
    assert peak_kw_by_window([friday_night, saturday_early], definition) == {"peak": D("3.0")}
