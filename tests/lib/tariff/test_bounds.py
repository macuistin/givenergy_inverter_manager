# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""minimum and maximum: a floor or a cap on one node."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import BillInputs, DefinitionError, parse_definition, price_bill
from tests.lib.tariff.example_definition import example_document

D = Decimal


def bound(kind: str, amount: str, **extra: Any) -> dict[str, Any]:
    energy = {"kind": "per_kwh", "amount": "0.10"}
    return {"kind": kind, "amount": amount, "of": energy, **extra}


def total(node: dict[str, Any], kwh: str = "100", days: int = 30, period_days: int = 30) -> Any:
    doc = example_document()
    doc["bill"]["total"] = node
    doc.pop("checks")
    doc["completeness"] = "partial"
    inputs = BillInputs(days, period_days, {"Day": D(kwh)}, D(0))
    return price_bill(parse_definition(doc), inputs)


def test_a_minimum_lifts_a_small_bill() -> None:
    bill = total(bound("minimum", "15"))  # 100 kWh x 0.10 = 10.00, below 15
    assert bill.total == D("15")
    assert bill.root.children["of"].amount == D("10.00")


def test_a_minimum_leaves_a_larger_bill() -> None:
    assert total(bound("minimum", "15"), kwh="200").total == D("20.00")


def test_a_maximum_caps_a_large_bill() -> None:
    assert total(bound("maximum", "15"), kwh="200").total == D("15")
    assert total(bound("maximum", "15")).total == D("10.00")


def test_the_amount_scales_with_the_months_or_days_of_the_bill() -> None:
    assert total(bound("minimum", "1", per="day")).total == D("30")  # 30 days x 1
    assert total(bound("minimum", "12", per="month")).total == D("12")  # a one-month period


def test_a_floor_inside_a_tax_is_taxed() -> None:
    node = {"kind": "tax", "name": "Sales tax", "percent": "10", "mode": "added",
            "of": bound("minimum", "20")}
    assert total(node).total == D("22.00")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"amount": "-1"}, "0 or more"),
        ({"per": "year"}, "must be one of"),
        ({"of": {"kind": "formula"}}, "not a known kind"),
        ({"extra": "1"}, "not a known field"),
    ],
)
def test_a_bad_bound_is_refused(change: dict[str, Any], message: str) -> None:
    with pytest.raises(DefinitionError, match=message):
        total({**bound("minimum", "5"), **change})
