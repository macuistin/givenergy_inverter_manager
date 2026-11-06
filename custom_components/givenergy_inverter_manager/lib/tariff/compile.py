"""compile.py: write a TariffConfig, the tariff as the options hold it, as a definition document.

The options describe one household's tariff: a base rate, timed rates where the cheapest wins, a
saving on energy, a standing charge, a monthly levy and VAT. This builds the document that prices
the same bill, then reads it through `parse_definition`, so the document is checked the same way
as one from a store. The options do not hold a currency code, country or time zone, so the caller
passes them as a `Locale`.

The cheapest-wins rule becomes priorities: the dearest timed rate gets priority 1, so a cheaper
rate that is also active outranks it. Equal rates keep the order they were listed in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from .config import TariffConfig
from .definition import DefinitionError, TariffDefinition
from .definition_parse import parse_definition


@dataclass(frozen=True)
class Locale:
    """What the options do not hold: where the tariff applies and from when."""

    currency: str  # ISO 4217
    country: str  # ISO 3166-1 alpha-2
    timezone_name: str
    effective_from: date


def definition_from_config(config: TariffConfig, locale: Locale) -> TariffDefinition:
    """The definition that prices the same bill as *config*.

    Raises DefinitionError when the options cannot be written as a document, for example a bill
    start day after the 28th, which a monthly period cannot name.
    """
    return parse_definition(
        {
            "schema": 1,
            "id": "household-options",
            "revision": 1,
            "supersedes": None,
            "name": "Tariff from the saved options",
            "service": "electricity",
            "customer_class": "residential",
            "provider": {"id": "household", "name": "Household"},
            "country": locale.country,
            "region": None,
            "currency": locale.currency,
            "timezone": locale.timezone_name,
            "effective_from": locale.effective_from.isoformat(),
            "effective_to": None,
            "source_url": None,
            "last_verified": None,
            "completeness": "partial",
            "inputs": {},
            "import": {
                "base": {"name": config.base_rate_name, "price": _text(config.base_rate)},
                "zones": _zones(config),
            },
            "export": {"base": {"name": "Export", "price": _text(config.export_rate)}},
            "bill": {"period": _period(config), "total": _total(config)},
        }
    )


def _text(value: float) -> str:
    """A float written as the decimal string it prints as, so 0.1056 stays 0.1056."""
    return str(Decimal(repr(value)))


def _zones(config: TariffConfig) -> list[dict[str, Any]]:
    # sorted is stable, so equal rates keep their listed order and the later one wins a tie,
    # as min() over the same list would pick the first. Reverse the tie order to match.
    ordered = sorted(enumerate(config.rate_periods), key=lambda item: (-item[1].rate, -item[0]))
    return [
        {
            "name": period.name,
            "priority": priority,
            "price": _text(period.rate),
            "hours": f"{period.start:%H:%M}-{period.end:%H:%M}",
        }
        for priority, (_, period) in enumerate(ordered, start=1)
    ]


def _period(config: TariffConfig) -> dict[str, Any]:
    if not 1 <= config.bill_start_day <= 28:
        raise DefinitionError(
            "bill.period.start_day", "a monthly period can start on day 1 to 28 only"
        )
    return {"rule": "monthly", "start_day": config.bill_start_day}


def _total(config: TariffConfig) -> dict[str, Any]:
    energy = {
        "kind": "adjust",
        "name": "Saving",
        "percent": _text(-config.discount_rate) if config.discount_rate else "0",
        "of": {"kind": "energy_by_band", "round_bands": True},
    }
    charges = {
        "kind": "tax",
        "name": "VAT",
        "percent": _text(config.vat_rate),
        "mode": "added",
        "of": {
            "kind": "sum",
            "of": {
                "energy": energy,
                "standing": {"kind": "per_day", "amount": _text(config.standing_charge)},
                "levy": {
                    "kind": "per_period",
                    "amount": _text(config.pso_levy),
                    "share": "days_in_period",
                },
            },
        },
    }
    return {"kind": "sum", "of": {"charges": charges, "credit": {"kind": "export_credit"}}}
