# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""price_series: a series from price day files, the cost of slot kWh, and the series_energy node."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import (
    BillInputs,
    DefinitionError,
    MissingPrice,
    MissingSeries,
    PriceSeries,
    parse_definition,
    price_bill,
    series_cost,
    series_from_days,
)
from tests.lib.tariff.example_definition import example_document

D = Decimal
UTC = timezone.utc


def day(date: str, prices: list[str], zone: str = "Europe/London", minutes: int = 30) -> dict[str, Any]:
    return {"date": date, "timezone": zone, "interval_minutes": minutes, "prices": prices}


def test_a_series_reads_consecutive_days_from_local_midnight() -> None:
    series = series_from_days([day("2026-11-17", ["0.1"] * 48), day("2026-11-16", ["0.2"] * 48)])
    assert series.start == datetime(2026, 11, 16, tzinfo=UTC)
    assert series.end == datetime(2026, 11, 18, tzinfo=UTC)
    assert series.price_at(datetime(2026, 11, 16, 23, 59, tzinfo=UTC)) == D("0.2")
    assert series.price_at(datetime(2026, 11, 17, tzinfo=UTC)) == D("0.1")


def test_a_clock_change_day_has_the_right_number_of_prices_and_the_next_day_follows() -> None:
    spring = day("2026-03-29", ["0.1"] * 46)  # 23 hours
    series = series_from_days([spring, day("2026-03-30", ["0.3"] * 48)])
    assert series.price_at(datetime(2026, 3, 29, 23, 0, tzinfo=UTC)) == D("0.3")  # 00:00 BST is 23:00Z


@pytest.mark.parametrize("days", [
    [],
    [day("2026-11-16", ["0.1"] * 48), day("2026-11-18", ["0.1"] * 48)],        # a gap
    [day("2026-11-16", ["0.1"] * 48), day("2026-11-16", ["0.1"] * 48)],        # an overlap
    [day("2026-11-16", ["0.1"] * 48), day("2026-11-17", ["0.1"] * 24, minutes=60)],  # new interval
    [day("2026-11-16", ["0.1"] * 47), day("2026-11-17", ["0.1"] * 48)],        # a short day
])
def test_days_that_do_not_follow_one_another_are_refused(days: list[dict[str, Any]]) -> None:
    with pytest.raises(ValueError):
        series_from_days(days)


def test_a_moment_outside_the_series_has_no_price() -> None:
    series = PriceSeries(datetime(2026, 11, 16, tzinfo=UTC), timedelta(minutes=30), (D("0.1"),) * 2)
    with pytest.raises(MissingPrice):
        series.price_at(datetime(2026, 11, 16, 1, tzinfo=UTC))
    with pytest.raises(MissingPrice):
        series.price_at(datetime(2026, 11, 15, 23, 59, tzinfo=UTC))


def test_cost_is_kwh_times_the_price_of_each_slot() -> None:
    series = PriceSeries(datetime(2026, 11, 16, tzinfo=UTC), timedelta(minutes=30), (D("0.10"), D("0.30")))
    slots = [(datetime(2026, 11, 16, 0, 0, tzinfo=UTC), D(2)), (datetime(2026, 11, 16, 0, 30, tzinfo=UTC), D(1))]
    assert series_cost(slots, series) == D("0.50")  # 2 x 0.10 + 1 x 0.30


def test_a_slot_longer_than_the_interval_takes_the_time_weighted_average() -> None:
    series = PriceSeries(datetime(2026, 11, 16, tzinfo=UTC), timedelta(minutes=15), (D("0.10"), D("0.30")))
    assert series_cost([(datetime(2026, 11, 16, tzinfo=UTC), D(1))], series) == D("0.20")
    assert series_cost([(datetime(2026, 11, 16, tzinfo=UTC), D(1))], series, slot_seconds=900) == D("0.10")


def test_a_slot_with_no_price_is_refused_not_priced_as_zero() -> None:
    series = PriceSeries(datetime(2026, 11, 16, tzinfo=UTC), timedelta(minutes=30), (D("0.10"),))
    with pytest.raises(MissingPrice):
        series_cost([(datetime(2026, 11, 16, 0, 30, tzinfo=UTC), D(1))], series)
    assert series_cost([], series) == D(0)


def dynamic_document(node: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = example_document()
    doc["bill"]["total"] = {"kind": "tax", "name": "VAT", "mode": "added", "percent": "5", "of": {
        "kind": "sum", "of": {"energy": node or {"kind": "series_energy", "series": "agile"},
                              "standing": {"kind": "per_day", "amount": "0.50"}}}}
    doc.pop("checks")
    doc["completeness"] = "partial"
    return doc


def test_the_series_node_prices_the_cost_it_is_given_and_the_rest_of_the_tree_still_applies() -> None:
    definition = parse_definition(dynamic_document())
    inputs = BillInputs(30, 30, {}, D(0), import_cost_by_series={"agile": D("40.004")})
    bill = price_bill(definition, inputs)
    assert bill.root.children["of"].children["energy"].amount == D("40.00")  # rounded by the node
    assert bill.total == D("57.75")  # (40.00 + 30 x 0.50) x 1.05


def test_a_series_the_bill_was_not_given_is_refused() -> None:
    definition = parse_definition(dynamic_document())
    with pytest.raises(MissingSeries):
        price_bill(definition, BillInputs(30, 30, {}, D(0)))
    with pytest.raises(MissingSeries):
        price_bill(definition, BillInputs(30, 30, {}, D(0), import_cost_by_series={"other": D(1)}))


def test_the_node_can_keep_full_precision_and_is_checked_on_reading() -> None:
    node = {"kind": "series_energy", "series": "agile", "round": "none"}
    line = price_bill(parse_definition(dynamic_document(node)),
                      BillInputs(30, 30, {}, D(0), import_cost_by_series={"agile": D("1.2345")}))
    assert line.root.children["of"].children["energy"].amount == D("1.2345")
    for bad in ({"kind": "series_energy"}, {"kind": "series_energy", "series": "Agile Prices"},
                {"kind": "series_energy", "series": "agile", "price": "1"}):
        with pytest.raises(DefinitionError):
            parse_definition(dynamic_document(bad))


def test_the_worked_example_in_the_format_doc() -> None:
    """docs/format.md, "A tariff on a price series": 5.60 of energy, 0.45 standing, 5% VAT."""
    from custom_components.givenergy_inverter_manager.lib.tariffstore.compile import compile_area
    from tests.lib.tariffstore.fixtures import META, country

    tariff = {
        "schema": 1, "name": "Agile example", "provider": "Example Power",
        "effective_from": "2026-11-01",
        "source": {"id": "example-source", "url": "https://example.com/agile"},
        "bands": [{"name": "All day"}],
        "areas": {"all": {"standing": "0.45", "rates": {"All day": "0.25"}}},
        "bill": {"total": {"kind": "tax", "name": "VAT", "mode": "added", "percent": "5", "of": {
            "kind": "sum", "of": {"energy": {"kind": "series_energy", "series": "agile"},
                                  "standing": {"kind": "per_day"}}}}}}
    series = series_from_days([day("2026-11-16", ["0.10"] * 16 + ["0.30"] * 32)])
    start = datetime(2026, 11, 16, tzinfo=UTC)
    slots = [(start + timedelta(minutes=30 * i), D("0.5")) for i in range(48)]
    cost = series_cost(slots, series)
    assert cost == D("5.60")  # 16 x 0.5 x 0.10 + 32 x 0.5 x 0.30
    definition = parse_definition(compile_area(tariff, "all", block=country(), meta=META,
                                               on="2026-11-16"))
    bill = price_bill(definition, BillInputs(1, 1, {}, D(0), import_cost_by_series={"agile": cost}))
    assert bill.total == D("6.35")  # (5.60 + 0.45) x 1.05 = 6.3525
