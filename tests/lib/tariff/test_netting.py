# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""Netting: export kWh offset import kWh in the band of the same name, inside one bill."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import BillInputs, DefinitionError, parse_definition, price_bill

D = Decimal


def document(netting: str | None = "band") -> dict[str, Any]:
    bill: dict[str, Any] = {
        "period": {"rule": "monthly", "start_day": 1},
        "total": {"kind": "sum", "of": {
            "energy": {"kind": "energy_by_band"},
            "export": {"kind": "export_credit"}}}}
    if netting:
        bill["netting"] = netting
    return {
        "schema": 1, "id": "net-plan", "revision": 1, "supersedes": None, "name": "Net plan",
        "service": "electricity", "customer_class": "residential",
        "provider": {"id": "p-energy", "name": "P Energy"}, "country": "US", "region": None,
        "currency": "USD", "timezone": "America/Chicago", "effective_from": "2026-01-01",
        "effective_to": None, "source_url": None, "last_verified": None,
        "completeness": "partial", "inputs": {},
        "import": {"base": {"name": "Off", "price": "0.10"}, "zones": [
            {"name": "Peak", "priority": 1, "price": "0.30", "hours": "16:00-21:00"}]},
        "export": {"base": {"name": "Off", "price": "0.04"}, "zones": [
            {"name": "Peak", "priority": 1, "price": "0.08", "hours": "16:00-21:00"}]},
        "bill": bill,
    }


def price(doc: dict[str, Any], imported: dict[str, str], exported: Any) -> Any:
    kwh = {band: D(v) for band, v in imported.items()}
    out = {b: D(v) for b, v in exported.items()} if isinstance(exported, dict) else D(exported)
    return price_bill(parse_definition(doc), BillInputs(30, 30, kwh, out))


def test_export_offsets_import_in_the_same_band() -> None:
    priced = price(document(), {"Off": "300", "Peak": "100"}, {"Off": "120", "Peak": "40"})
    assert priced.root.children["energy"].amount == D("36.00")  # 180 x 0.10 + 60 x 0.30


def test_only_the_surplus_is_paid_at_the_export_price() -> None:
    priced = price(document(), {"Off": "100", "Peak": "10"}, {"Off": "150", "Peak": "10"})
    assert priced.root.children["energy"].amount == D("0.00")
    assert priced.root.children["export"].amount == D("-2.00")  # 50 x 0.04, peak fully absorbed
    assert priced.total == D("-2.00")


def test_a_band_with_no_import_pays_its_whole_export() -> None:
    priced = price(document(), {"Off": "100"}, {"Off": "10", "Peak": "25"})
    assert priced.root.children["export"].amount == D("-2.00")  # 25 x 0.08, the Off export netted


def test_without_netting_both_sides_are_priced_in_full() -> None:
    priced = price(document(None), {"Off": "100"}, {"Off": "40"})
    assert priced.root.children["energy"].amount == D("10.00")
    assert priced.root.children["export"].amount == D("-1.60")


def test_a_plain_export_total_nets_in_the_band_of_the_base_export_price() -> None:
    priced = price(document(), {"Off": "100", "Peak": "10"}, "30")
    # The 30 kWh net the Off band: 70 x 0.10 + 10 x 0.30.
    assert priced.root.children["energy"].amount == D("10.00")
    assert priced.root.children["export"].amount == D("0.00")


def test_netting_never_makes_import_negative() -> None:
    priced = price(document(), {"Off": "5"}, {"Off": "5"})
    assert priced.total == D("0.00")


def test_netting_needs_an_import_band_for_each_export_band() -> None:
    doc = document()
    doc["export"]["zones"][0]["name"] = "Shoulder"
    with pytest.raises(DefinitionError, match="export band 'Shoulder' has no import band"):
        parse_definition(doc)


def test_netting_must_be_a_known_rule() -> None:
    with pytest.raises(DefinitionError, match="must be one of"):
        parse_definition(document("annual"))
