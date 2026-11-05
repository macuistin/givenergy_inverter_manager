"""The engine prices a definition: the worked October bill, and each node on its own."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import (
    BillInputs,
    CheckFailed,
    parse_definition,
    price_bill,
    verify_checks,
)
from tests.lib.tariff.example_definition import example_document

D = Decimal


def october() -> BillInputs:
    kwh = {"Boost": D(257), "Day": D(67), "Night": D(619)}
    return BillInputs(30, 30, kwh, D(47))


def test_october_bill_reproduces() -> None:
    bill = price_bill(parse_definition(example_document()), october())
    assert bill.total == D("187.35")
    charges = bill.root.children["charges"]
    assert charges.name == "VAT" and charges.tax == D("16.23") and charges.amount == D("196.52")
    inner = charges.children["of"].children
    assert inner["energy"].amount == D("154.05") and inner["energy"].tax == D("-8.97")
    energy = inner["energy"].children["of"]
    assert energy.amount == D("163.02")
    assert energy.children["Boost"].amount == D("27.14")
    assert inner["standing"].amount == D("24.78") and inner["levy"].amount == D("1.46")
    assert bill.root.children["credit"].amount == D("-9.17")


def test_checks_in_the_document_pass() -> None:
    verify_checks(parse_definition(example_document()))


def test_a_check_that_does_not_reproduce_is_refused() -> None:
    doc = example_document()
    doc["checks"]["october-2026"]["expected_total"] = "187.36"
    with pytest.raises(CheckFailed, match="october-2026"):
        verify_checks(parse_definition(doc))


def test_bands_rounded_together_when_not_per_band() -> None:
    doc = example_document()
    doc["bill"]["total"]["of"]["charges"]["of"]["of"]["energy"]["of"]["round_bands"] = False
    line = price_bill(parse_definition(doc), october()).root.children["charges"]
    energy = line.children["of"].children["energy"].children["of"]
    assert energy.amount == D("163.01")  # 27.1392 + 24.455 + 111.42 = 163.0142, a cent below 163.02


def test_included_tax_is_reported_not_added() -> None:
    doc = example_document()
    doc["bill"]["total"]["of"]["charges"]["mode"] = "included"
    charges = price_bill(parse_definition(doc), october()).root.children["charges"]
    assert charges.amount == D("180.29")
    assert charges.tax == D("14.89")  # 180.29 * 9 / 109


def test_round_none_keeps_full_precision() -> None:
    doc = example_document()
    node: dict[str, Any] = doc["bill"]["total"]["of"]["charges"]["of"]["of"]["standing"]
    node["round"] = "none"
    node["amount"] = "0.82595"
    standing = price_bill(parse_definition(doc), october()).root
    line = standing.children["charges"].children["of"].children["standing"]
    assert line.amount == D("24.7785")


def test_period_charge_share() -> None:
    doc = example_document()
    inputs = BillInputs(15, 30, october().import_kwh_by_band, D(0))
    levy = price_bill(parse_definition(doc), inputs).root.children["charges"]
    assert levy.children["of"].children["levy"].amount == D("0.73")  # 1.46 * 15 / 30
    whole = doc["bill"]["total"]["of"]["charges"]["of"]["of"]["levy"]
    whole["share"] = "whole"
    levy = price_bill(parse_definition(doc), inputs).root.children["charges"]
    assert levy.children["of"].children["levy"].amount == D("1.46")


def test_zero_decimal_currency_rounds_to_whole_units() -> None:
    doc = example_document()
    doc["currency"] = "JPY"
    doc["checks"] = {}
    doc["completeness"] = "partial"
    bill = price_bill(parse_definition(doc), october())
    assert bill.total == bill.total.to_integral_value()


def test_bad_days_are_refused() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        price_bill(parse_definition(example_document()), BillInputs(0, 30, {}, D(0)))
