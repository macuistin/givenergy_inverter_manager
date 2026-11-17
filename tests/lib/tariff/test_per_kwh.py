# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""per_kwh: an amount for each kWh imported or exported."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import BillInputs, DefinitionError, parse_definition, price_bill
from tests.lib.tariff.example_definition import example_document

D = Decimal


def doc_with(node: dict[str, Any]) -> dict[str, Any]:
    doc = example_document()
    doc["bill"]["total"] = {"kind": "sum", "of": {"adder": node}}
    doc.pop("checks")
    doc["completeness"] = "partial"
    return doc


def total(node: dict[str, Any], export: Any = D(0)) -> Decimal:
    inputs = BillInputs(30, 30, {"Day": D(100), "Night": D(50)}, export)
    return price_bill(parse_definition(doc_with(node)), inputs).total


def test_import_kwh_in_every_band_are_charged() -> None:
    assert total({"kind": "per_kwh", "amount": "0.012"}) == D("1.80")  # 150 x 0.012


def test_a_negative_amount_is_a_credit() -> None:
    assert total({"kind": "per_kwh", "amount": "-0.02"}) == D("-3.00")


def test_export_kwh_can_be_charged_or_given_by_band() -> None:
    node = {"kind": "per_kwh", "amount": "0.01", "on": "export"}
    assert total(node, D(40)) == D("0.40")
    assert total(node, {"Export": D(30), "Other": D(10)}) == D("0.40")


def test_rounding_follows_the_node() -> None:
    node = {"kind": "per_kwh", "amount": "0.0123", "round": "none"}
    inputs = BillInputs(30, 30, {"Day": D(100), "Night": D(50)}, D(0))
    line = price_bill(parse_definition(doc_with(node)), inputs).root.children["adder"]
    assert line.amount == D("1.845")  # 150 x 0.0123, kept whole until the parent rounds


@pytest.mark.parametrize(
    ("node", "message"),
    [
        ({"kind": "per_kwh"}, "amount: is missing"),
        ({"kind": "per_kwh", "amount": "1", "on": "both"}, "must be one of"),
        ({"kind": "per_kwh", "amount": 1.5}, "must be a decimal string"),
        ({"kind": "per_kwh", "amount": "1", "extra": "x"}, "not a known field"),
    ],
)
def test_a_bad_node_is_refused(node: dict[str, Any], message: str) -> None:
    with pytest.raises(DefinitionError, match=message):
        parse_definition(doc_with(node))
