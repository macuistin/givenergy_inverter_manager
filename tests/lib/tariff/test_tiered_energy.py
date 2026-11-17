# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""Tiered energy: the first kWh at one price, the next at another."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import BillInputs, DefinitionError, parse_definition, price_bill
from tests.lib.tariff.example_definition import example_document

D = Decimal


def tiered(limits: str | None = None, **extra: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "kind": "tiered_energy",
        "blocks": {
            "baseline": {"from_kwh": "0", "upto_kwh": "300", "price": "0.20"},
            "middle": {"from_kwh": "300", "upto_kwh": "600", "price": "0.30"},
            "high": {"from_kwh": "600", "price": "0.45"},
        },
    }
    if limits:
        node["limits"] = limits
    node.update(extra)
    doc = example_document()
    doc["bill"]["total"] = node
    doc.pop("checks")
    doc["completeness"] = "partial"
    return doc


def bill(doc: dict[str, Any], kwh: dict[str, str], days: int = 30, period_days: int = 30) -> Any:
    inputs = BillInputs(days, period_days, {b: D(k) for b, k in kwh.items()}, D(0))
    return price_bill(parse_definition(doc), inputs)


def test_kwh_fill_the_blocks_in_order() -> None:
    priced = bill(tiered(), {"Day": "500", "Night": "250"})  # 750 kWh in all
    blocks = priced.root.children
    assert blocks["baseline"].amount == D("60.00")
    assert blocks["middle"].amount == D("90.00")
    assert blocks["high"].amount == D("67.50")
    assert priced.total == D("217.50")


def test_a_bill_inside_the_first_block_uses_only_it() -> None:
    priced = bill(tiered(), {"Day": "100"})
    assert priced.total == D("20.00")
    assert priced.root.children["middle"].amount == D("0")


def test_a_block_limit_is_for_the_whole_period_by_default() -> None:
    assert bill(tiered(), {"Day": "400"}, days=10, period_days=30).total == D("60.00") + D("30.00")


def test_monthly_limits_grow_with_the_months_of_the_period() -> None:
    doc = tiered("month")
    doc["bill"]["period"] = {"rule": "monthly", "start_day": 1, "months": 2}
    # Limits double to 600 and 1200, so 700 kWh is 600 at 0.20 and 100 at 0.30.
    assert bill(doc, {"Day": "700"}, 60, 60).total == D("150.00")


def test_daily_limits_follow_the_days_of_the_bill() -> None:
    doc = tiered("day")
    # A limit of 10 kWh a day over 10 days: 100 kWh at 0.20, the other 50 at 0.40.
    doc["bill"]["total"]["blocks"] = {
        "baseline": {"from_kwh": "0", "upto_kwh": "10", "price": "0.20"},
        "rest": {"from_kwh": "10", "price": "0.40"},
    }
    assert bill(doc, {"Day": "150"}, days=10, period_days=30).total == D("20.00") + D("20.00")


def test_blocks_are_ordered_by_start_not_by_name() -> None:
    doc = tiered()
    blocks = doc["bill"]["total"]["blocks"]
    doc["bill"]["total"]["blocks"] = {k: blocks[k] for k in ("high", "baseline", "middle")}
    assert bill(doc, {"Day": "750"}).total == D("217.50")


def test_the_node_works_inside_a_tax() -> None:
    doc = tiered()
    doc["bill"]["total"] = {
        "kind": "tax", "name": "Sales tax", "percent": "10", "mode": "added",
        "of": doc["bill"]["total"],
    }
    assert bill(doc, {"Day": "100"}).total == D("22.00")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"blocks": {}}, "needs at least one block"),
        ({"blocks": {"a": {"from_kwh": "5", "price": "0.1"}}}, "must start at 0 kWh"),
        (
            {"blocks": {"a": {"from_kwh": "0", "upto_kwh": "5", "price": "0.1"}}},
            "needs a last block with no upto_kwh",
        ),
        (
            {"blocks": {"a": {"from_kwh": "0", "upto_kwh": "5", "price": "0.1"},
                        "b": {"from_kwh": "6", "price": "0.2"}}},
            "must start at 5 kWh",
        ),
        (
            {"blocks": {"a": {"from_kwh": "0", "price": "0.1"},
                        "b": {"from_kwh": "5", "price": "0.2"}}},
            "comes after a block with no upto_kwh",
        ),
        ({"blocks": {"a": {"from_kwh": "0", "upto_kwh": "0", "price": "0.1"}}}, "above from_kwh"),
        ({"blocks": {"A": {"from_kwh": "0", "price": "0.1"}}}, "not a valid name"),
        ({"blocks": {"a": {"from_kwh": "0", "price": "-1"}}}, "0 or more"),
        ({"blocks": {"a": {"from_kwh": "0", "price": "1", "extra": "1"}}}, "not a known field"),
        ({"limits": "year"}, "must be one of"),
        ({"surprise": "1"}, "not a known field"),
    ],
)
def test_a_bad_tier_table_is_refused(change: dict[str, Any], message: str) -> None:
    doc = tiered()
    doc["bill"]["total"].update(change)
    with pytest.raises(DefinitionError, match=message):
        parse_definition(doc)


def per_band_doc() -> dict[str, Any]:
    """Peak kWh and the other bands each have a tier table of their own."""
    doc = example_document()
    doc["bill"]["total"] = {"kind": "sum", "of": {
        "peak": {"kind": "tiered_energy", "bands": ["Boost"], "blocks": {
            "low": {"from_kwh": "0", "upto_kwh": "100", "price": "0.50"},
            "high": {"from_kwh": "100", "price": "0.70"}}},
        "rest": {"kind": "tiered_energy", "bands": ["Day", "Night"], "blocks": {
            "low": {"from_kwh": "0", "upto_kwh": "300", "price": "0.10"},
            "high": {"from_kwh": "300", "price": "0.20"}}}}}
    doc.pop("checks")
    doc["completeness"] = "partial"
    return doc


def test_a_table_prices_only_the_bands_it_names() -> None:
    kwh = {"Boost": "150", "Day": "200", "Night": "200"}
    priced = bill(per_band_doc(), kwh)
    peak = priced.root.children["peak"]
    rest = priced.root.children["rest"]
    assert peak.amount == D("85.00")  # 100 x 0.50 + 50 x 0.70
    assert rest.amount == D("50.00")  # 300 x 0.10 + 100 x 0.20
    assert priced.total == D("135.00")


def test_a_band_with_no_kwh_leaves_its_table_empty() -> None:
    priced = bill(per_band_doc(), {"Day": "100"})
    assert priced.root.children["peak"].amount == D("0")
    assert priced.total == D("10.00")


@pytest.mark.parametrize(
    ("bands", "message"),
    [
        ([], "must be a list of band names"),
        (["Day", "Day"], "names a band twice"),
        ([1], "must be a list of band names"),
        (["Weekend"], "'Weekend' is not an import band"),
    ],
)
def test_a_bad_band_list_is_refused(bands: Any, message: str) -> None:
    doc = per_band_doc()
    doc["bill"]["total"]["of"]["peak"]["bands"] = bands
    with pytest.raises(DefinitionError, match=message):
        parse_definition(doc)


def test_a_band_named_inside_a_tax_is_checked_too() -> None:
    doc = per_band_doc()
    doc["bill"]["total"] = {"kind": "tax", "name": "Tax", "percent": "10", "mode": "added",
                            "of": doc["bill"]["total"]}
    doc["bill"]["total"]["of"]["of"]["peak"]["bands"] = ["Nope"]
    with pytest.raises(DefinitionError, match="bill.total.of.of.peak.bands"):
        parse_definition(doc)
