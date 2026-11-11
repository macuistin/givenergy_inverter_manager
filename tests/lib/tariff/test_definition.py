"""The tariff definition: a good document parses, and each way to be wrong is refused by name."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, time
from decimal import Decimal
from typing import Any

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import (
    DefinitionError,
    load_definition,
    parse_definition,
)
from custom_components.givenergy_inverter_manager.lib.tariff.definition import (
    Adjust,
    EnergyByBand,
    ExportCredit,
    NodeRounding,
    PerDay,
    PerPeriod,
    Sum,
    Tax,
    TaxMode,
)
from tests.lib.tariff.example_definition import example_document, example_text

Edit = Callable[[dict[str, Any]], None]


def refused(edit: Edit, where: str, text: str = "") -> None:
    doc = example_document()
    edit(doc)
    with pytest.raises(DefinitionError) as err:
        parse_definition(doc)
    assert err.value.path == where
    assert text in str(err.value)


def energy(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["bill"]["total"]["of"]["charges"]["of"]["of"]["energy"]


def test_example_parses() -> None:
    d = load_definition(example_text())
    assert d.id == "example-nightboost"
    assert d.provider.id == "example-energy"
    assert d.country == "IE" and d.region is None
    assert d.effective_from == date(2026, 1, 1) and d.effective_to is None
    assert d.complete and d.rounding_places == 2
    assert d.timezone_name == "Europe/Dublin"
    assert d.import_prices.base.price == Decimal("0.365")
    night, boost = d.import_prices.zones
    assert (night.priority, night.start, night.end) == (1, time(23), time(8))
    assert boost.price == Decimal("0.1056")
    assert d.period.start_day.input == "start_day" and d.period.start_day.fixed is None
    assert d.inputs["start_day"].default == 1
    assert d.checks["october-2026"].expected_total == Decimal("187.35")


def test_example_tree_nests_as_written() -> None:
    total = load_definition(example_text()).total
    assert isinstance(total, Sum)
    tax = total.children["charges"]
    assert isinstance(tax, Tax) and tax.mode is TaxMode.ADDED and tax.percent == 9
    assert isinstance(total.children["credit"], ExportCredit)
    assert isinstance(tax.child, Sum)
    adjust = tax.child.children["energy"]
    assert isinstance(adjust, Adjust) and adjust.percent == Decimal("-5.5")
    assert isinstance(adjust.child, EnergyByBand) and adjust.child.round_bands
    assert isinstance(tax.child.children["standing"], PerDay)
    levy = tax.child.children["levy"]
    assert isinstance(levy, PerPeriod) and levy.share == "days_in_period"
    assert levy.rounding is NodeRounding.MINOR_UNIT


def test_round_none_and_included_tax() -> None:
    doc = example_document()
    energy(doc)["round"] = "none"
    doc["bill"]["total"]["of"]["charges"]["mode"] = "included"
    d = parse_definition(doc)
    tax = d.total.children["charges"]  # type: ignore[union-attr]
    assert tax.mode is TaxMode.INCLUDED
    assert tax.child.children["energy"].rounding is NodeRounding.NONE


def test_fixed_start_day_and_optional_fields() -> None:
    doc = example_document()
    doc["bill"]["period"]["start_day"] = 15
    doc["region"] = "IE-D"
    doc["supersedes"] = None
    doc["source_url"] = None
    doc["last_verified"] = None
    doc["effective_to"] = "2027-01-01"
    del doc["checks"]
    doc["completeness"] = "partial"
    d = parse_definition(doc)
    assert d.period.start_day.fixed == 15 and d.region == "IE-D"
    assert d.checks == {} and not d.complete and d.effective_to == date(2027, 1, 1)


def test_zone_days_months_and_holidays() -> None:
    doc = example_document()
    doc["import"]["zones"][0].update(
        {"days": ["sat", "sun"], "months": [11, 12, 1], "holidays": "weekend"}
    )
    zone = parse_definition(doc).import_prices.zones[0]
    assert zone.days == frozenset({5, 6}) and zone.months == frozenset({11, 12, 1})
    assert zone.holidays_as_weekend


def test_supersedes_and_currency_places() -> None:
    doc = example_document()
    doc["revision"] = 3
    doc["supersedes"] = 2
    doc["currency"] = "JPY"
    d = parse_definition(doc)
    assert d.supersedes == 2 and d.rounding_places == 0
    doc["currency"] = "KWD"
    assert parse_definition(doc).rounding_places == 3


def test_load_refuses_bad_json_and_floats() -> None:
    for text in ("{", "[]", json.dumps({"x": 1}).replace("1", "NaN")):
        with pytest.raises(DefinitionError):
            load_definition(text)
    with pytest.raises(DefinitionError, match="decimal point"):
        load_definition(example_text().replace('"0.365"', "0.365"))
    with pytest.raises(DefinitionError, match="not allowed"):
        load_definition(example_text().replace('"0.365"', "Infinity"))


def test_document_must_be_an_object() -> None:
    with pytest.raises(DefinitionError, match="must be an object"):
        parse_definition([])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("edit", "where", "text"),
    [
        (lambda d: d.update(extra=1), "extra", "not a known field"),
        (lambda d: d.pop("bill"), "bill", "missing"),
        (lambda d: d.update(schema=2), "schema", ""),
        (lambda d: d.update(id="Bad Id"), "id", "lowercase"),
        (lambda d: d.update(name=""), "name", "non-empty"),
        (lambda d: d.update(service="gas"), "service", "one of"),
        (lambda d: d.update(customer_class="x"), "customer_class", "one of"),
        (lambda d: d.update(country="Ireland"), "country", "ISO 3166-1"),
        (lambda d: d.update(region="GB-SCT"), "region", "belong to the country IE"),
        (lambda d: d.update(region="scotland"), "region", "ISO 3166-2"),
        (lambda d: d.update(currency="euro"), "currency", "ISO 4217"),
        (lambda d: d.update(timezone="Mars/Base"), "timezone", "not a time zone"),
        (lambda d: d.update(effective_from="01/01/2026"), "effective_from", "YYYY-MM-DD"),
        (lambda d: d.update(effective_from="2026-02-30"), "effective_from", "real date"),
        (lambda d: d.update(effective_to="2026-01-01"), "effective_to", "after"),
        (lambda d: d.update(source_url="ftp://x"), "source_url", "https://"),
        (lambda d: d.update(revision=0), "revision", ""),
        (lambda d: d.update(supersedes=1), "supersedes", "earlier"),
        (lambda d: d.update(completeness="maybe"), "completeness", "one of"),
        (lambda d: d["provider"].update(extra=1), "provider.extra", "not a known"),
        (lambda d: d["provider"].update(id="A B"), "provider.id", "lowercase"),
    ],
)
def test_identity_refusals(edit: Edit, where: str, text: str) -> None:
    refused(edit, where, text)


def test_complete_needs_a_check() -> None:
    refused(lambda d: d.pop("checks"), "completeness", "at least one")
    refused(lambda d: d.update(checks={}), "completeness", "at least one")


@pytest.mark.parametrize(
    ("edit", "where", "text"),
    [
        (lambda d: d["inputs"].update({"Bad": {}}), "inputs.Bad", "valid input name"),
        (lambda d: d["inputs"]["start_day"].update(type="text"), "inputs.start_day.type", ""),
        (lambda d: d["inputs"]["start_day"].update(min=9, max=3), "inputs.start_day.min", "above"),
        (lambda d: d["inputs"]["start_day"].update(default=40), "inputs.start_day.default", ""),
        (lambda d: d["inputs"]["start_day"].update(min=True), "inputs.start_day.min", "whole"),
        (lambda d: d["inputs"]["start_day"].update(max=31), "bill.period.start_day.input", "within"),
        (
            lambda d: d["bill"]["period"].update(start_day={"input": "nope"}),
            "bill.period.start_day.input",
            "not declared",
        ),
        (lambda d: d["bill"]["period"].update(start_day=31), "bill.period.start_day", ""),
        (lambda d: d["bill"]["period"].update(start_day="1"), "bill.period.start_day", "whole"),
        (lambda d: d["bill"]["period"].update(rule="weekly"), "bill.period.rule", "one of"),
    ],
)
def test_input_and_period_refusals(edit: Edit, where: str, text: str) -> None:
    refused(edit, where, text)


@pytest.mark.parametrize(
    ("edit", "where", "text"),
    [
        (lambda d: d["import"]["base"].update(price="-1"), "import.base.price", "0 or more"),
        (lambda d: d["import"]["base"].update(price="abc"), "import.base.price", "decimal string"),
        (lambda d: d["import"]["base"].update(price=0.5), "import.base.price", "decimal string"),
        (lambda d: d["import"]["base"].update(price="1e2"), "import.base.price", "decimal string"),
        (lambda d: d["import"]["zones"][0].update(name="Day"), "import.zones", "like the base"),
        (lambda d: d["import"]["zones"][0].update(name="Boost"), "import.zones", "own name"),
        (lambda d: d["import"]["zones"][0].update(priority=2), "import.zones", "own priority"),
        (lambda d: d["import"]["zones"][0].update(hours="25:00-08:00"), "import.zones[0].hours", "HH:MM"),
        (lambda d: d["import"]["zones"][0].update(hours="08:00-08:00"), "import.zones[0].hours", "same time"),
        (lambda d: d["import"]["zones"][0].update(days=["fun"]), "import.zones[0].days", "distinct"),
        (lambda d: d["import"]["zones"][0].update(days=["mon", "mon"]), "import.zones[0].days", "distinct"),
        (lambda d: d["import"]["zones"][0].update(months=[13]), "import.zones[0].months", ""),
        (lambda d: d["import"]["zones"][0].update(months=[1, 1]), "import.zones[0].months", "repeat"),
        (lambda d: d["import"]["zones"][0].update(holidays="maybe"), "import.zones[0].holidays", "one of"),
        (lambda d: d["import"]["zones"][0].update(valid="2026"), "import.zones[0].valid", "not a known"),
        (lambda d: d["import"].update(zones="x"), "import.zones", "list"),
        (lambda d: d["import"]["zones"].append(5), "import.zones[2]", "object"),
        (lambda d: d["export"].update(tiers=[]), "export.tiers", "not a known"),
    ],
)
def test_price_refusals(edit: Edit, where: str, text: str) -> None:
    refused(edit, where, text)


@pytest.mark.parametrize(
    ("edit", "where", "text"),
    [
        (lambda d: energy(d).update(kind="formula"), "bill.total.of.charges.of.of.energy.kind", "not a known"),
        (lambda d: energy(d).pop("kind"), "bill.total.of.charges.of.of.energy.kind", "missing"),
        (lambda d: energy(d)["of"].update(percent="0"), "bill.total.of.charges.of.of.energy.of.percent", "not a known"),
        (lambda d: energy(d).update(percent="-100"), "bill.total.of.charges.of.of.energy.percent", "above -100"),
        (lambda d: energy(d).update(round="up"), "bill.total.of.charges.of.of.energy.round", "one of"),
        (lambda d: energy(d)["of"].update(round_bands="yes"), "bill.total.of.charges.of.of.energy.of.round_bands", "true or false"),
        (lambda d: d["bill"]["total"]["of"]["charges"].update(mode="both"), "bill.total.of.charges.mode", "one of"),
        (lambda d: d["bill"]["total"]["of"]["charges"].update(percent="-9"), "bill.total.of.charges.percent", "0 or more"),
        (lambda d: d["bill"]["total"]["of"]["charges"].pop("of"), "bill.total.of.charges.of", "missing"),
        (lambda d: d["bill"]["total"].update(of={}), "bill.total.of", "at least one"),
        (lambda d: d["bill"]["total"]["of"].update({"Bad Name": {"kind": "export_credit"}}), "bill.total.of.Bad Name", "valid name"),
        (lambda d: d["bill"]["total"].update(round="x"), "bill.total.round", "one of"),
    ],
)
def test_bill_refusals(edit: Edit, where: str, text: str) -> None:
    refused(edit, where, text)


def test_tree_depth_is_limited() -> None:
    node: dict[str, Any] = {"kind": "export_credit"}
    for _ in range(9):
        node = {"kind": "adjust", "name": "A", "percent": "1", "of": node}
    doc = example_document()
    doc["bill"]["total"] = node
    with pytest.raises(DefinitionError, match="nested deeper than 8"):
        parse_definition(doc)


@pytest.mark.parametrize(
    ("edit", "where", "text"),
    [
        (lambda d: d["checks"].update({"Bad Name": {}}), "checks.Bad Name", "valid name"),
        (lambda d: d["checks"]["october-2026"]["import_kwh_by_band"].update(Peak="1"), "checks.october-2026.import_kwh_by_band.Peak", "not a band"),
        (lambda d: d["checks"]["october-2026"].update(period_days=0), "checks.october-2026.period_days", ""),
        (lambda d: d["checks"]["october-2026"].update(export_kwh="-1"), "checks.october-2026.export_kwh", "0 or more"),
        (lambda d: d["checks"]["october-2026"].pop("expected_total"), "checks.october-2026.expected_total", "missing"),
    ],
)
def test_check_refusals(edit: Edit, where: str, text: str) -> None:
    refused(edit, where, text)


def test_error_without_a_path_names_the_definition() -> None:
    assert str(DefinitionError("", "bad")) == "definition: bad"
