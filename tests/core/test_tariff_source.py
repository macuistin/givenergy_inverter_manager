"""Copying a store tariff into the saved options, and proving the copy prices the same."""

from __future__ import annotations

import copy
from datetime import date, time
from typing import Any

import pytest

from custom_components.givenergy_inverter_manager.core.tariff_source import (
    NotRepresentable,
    materialise,
    prices_match,
)
from custom_components.givenergy_inverter_manager.lib.tariff import (
    Locale,
    TariffConfig,
    definition_from_config,
    parse_definition,
)
from custom_components.givenergy_inverter_manager.lib.tariff.periods import RatePeriod


def hhmm(value: str) -> time:
    return time.fromisoformat(value)


LOCALE = Locale("EUR", "IE", "Europe/Dublin", date(2026, 1, 1))


def _config(**changes: Any) -> TariffConfig:
    values: dict[str, Any] = {
        "rate_periods": [
            RatePeriod("Night", 0.18, hhmm("23:00"), hhmm("08:00")),
            RatePeriod("Boost", 0.1056, hhmm("02:00"), hhmm("04:00")),
        ],
        "base_rate": 0.365,
        "base_rate_name": "Day",
        "export_rate": 0.195,
        "standing_charge": 0.8259,
        "pso_levy": 1.46,
        "vat_rate": 9.0,
        "discount_rate": 5.5,
        "bill_start_day": 1,
    }
    values.update(changes)
    return TariffConfig(**values)


def _document(**changes: Any) -> dict[str, Any]:
    """The document the options compile to, as a plain dict a test can change."""
    document: dict[str, Any] = {
        "schema": 1, "id": "t", "revision": 1, "supersedes": None, "name": "T",
        "service": "electricity", "customer_class": "residential",
        "provider": {"id": "p", "name": "P"}, "country": "IE", "region": None,
        "currency": "EUR", "timezone": "Europe/Dublin", "effective_from": "2026-01-01",
        "effective_to": None, "source_url": None, "last_verified": None,
        "completeness": "partial", "inputs": {},
        "import": {
            "base": {"name": "Day", "price": "0.365"},
            "zones": [
                {"name": "Night", "priority": 1, "price": "0.18", "hours": "23:00-08:00"},
                {"name": "Boost", "priority": 2, "price": "0.1056", "hours": "02:00-04:00"},
            ],
        },
        "export": {"base": {"name": "Export", "price": "0.195"}},
        "bill": {
            "period": {"rule": "monthly", "start_day": 1},
            "total": {
                "kind": "tax", "name": "VAT", "percent": "9", "mode": "added",
                "of": {"kind": "sum", "of": {
                    "energy": {"kind": "energy_by_band", "round_bands": True},
                    "standing": {"kind": "per_day", "amount": "0.8259"},
                }},
            },
        },
    }
    document.update(changes)
    return document


def test_options_round_trip_prices_the_same() -> None:
    definition = definition_from_config(_config(), LOCALE)
    options = materialise(definition)
    assert options["base_rate"] == 0.365
    assert [p["name"] for p in options["rate_periods"]] == ["Night", "Boost"]
    assert options["vat_rate"] == 9.0
    assert options["discount_rate"] == 5.5
    assert options["pso_levy_per_month"] == 1.46
    assert prices_match(definition, options) == []


def test_a_weekday_band_is_refused_with_its_reason() -> None:
    document = _document()
    document["import"]["zones"][0]["days"] = ["sat", "sun"]
    with pytest.raises(NotRepresentable) as refused:
        materialise(parse_definition(document))
    assert any("weekday" in reason for reason in refused.value.reasons)


def test_a_dearer_band_over_a_cheaper_one_is_refused() -> None:
    document = _document()
    document["import"]["zones"][1]["price"] = "0.30"  # Boost, higher priority, now dearer
    with pytest.raises(NotRepresentable) as refused:
        materialise(parse_definition(document))
    assert any("dearer" in reason for reason in refused.value.reasons)


def test_export_by_time_of_day_is_refused() -> None:
    document = _document()
    document["export"]["zones"] = [
        {"name": "Peak", "priority": 1, "price": "0.30", "hours": "17:00-19:00"}
    ]
    with pytest.raises(NotRepresentable) as refused:
        materialise(parse_definition(document))
    assert any("export" in reason for reason in refused.value.reasons)


def test_a_second_tax_is_refused() -> None:
    document = _document()
    inner = copy.deepcopy(document["bill"]["total"])
    document["bill"]["total"] = {
        "kind": "tax", "name": "Levy", "percent": "1", "mode": "added", "of": inner
    }
    with pytest.raises(NotRepresentable):
        materialise(parse_definition(document))


def test_prices_that_include_vat_are_converted_and_checked() -> None:
    document = _document()
    document["bill"]["total"]["mode"] = "included"
    definition = parse_definition(document)
    options = materialise(definition)
    assert options["base_rate"] == pytest.approx(0.365 / 1.09, abs=1e-6)
    # The conversion can differ by a cent over a bill, so the check, not the conversion, decides.
    assert isinstance(prices_match(definition, options), list)


def test_a_wrong_copy_is_caught() -> None:
    definition = definition_from_config(_config(), LOCALE)
    options = materialise(definition)
    options["standing_charge_per_day"] = 0.9
    assert prices_match(definition, options)
