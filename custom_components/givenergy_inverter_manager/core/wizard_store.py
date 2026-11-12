"""
wizard_store.py - the words and values of the "choose a tariff from the list" screens.

Pure Python. The screens in `wizard/store_steps.py` fetch from the tariff store and call these to
turn a store tariff into saved options (`StoreChoice`) and to describe it for the review screen.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..conf import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_BILL_START_DAY,
    CONF_CURRENCY,
    CONF_DISCOUNT_RATE,
    CONF_EXPORT_RATE,
    CONF_PSO_LEVY,
    CONF_RATE_PERIODS,
    CONF_STANDING_CHARGE,
    CONF_TARIFF_SOURCE,
    CONF_VAT_INCLUDED,
    CONF_VAT_RATE,
)
from ..lib.tariff import TariffDefinition
from .tariff_source import NotRepresentable, materialise, prices_match

# Country names for the codes the store holds. Any other code is shown as it is.
COUNTRY_NAMES: dict[str, str] = {
    "AU": "Australia",
    "FR": "France",
    "GB": "United Kingdom",
    "IE": "Ireland",
    "ZA": "South Africa",
}
OFFERED = frozenset({"available", "partial"})
SOURCE_KIND = "store"
MAX_REASONS = 3


@dataclass(frozen=True)
class StoreChoice:
    """A store tariff turned into saved options, or the reasons it could not be."""

    options: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not self.reasons


def country_choices(countries: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """{code: label} for the countries that hold tariffs. A partial one says so in its label."""
    choices = {}
    for code, entry in sorted(countries.items()):
        if entry.get("availability") not in OFFERED:
            continue
        name = COUNTRY_NAMES.get(code, code)
        partial = entry.get("availability") == "partial"
        choices[code] = f"{name} (some suppliers only)" if partial else name
    return choices


def default_country(choices: Mapping[str, str], home: str | None) -> str | None:
    """Home Assistant's own country when the store holds it, else the first offered."""
    if home and home.upper() in choices:
        return home.upper()
    return next(iter(choices), None)


def choose_tariff(definition: TariffDefinition, bill_start_day: int) -> StoreChoice:
    """The options that price *definition*, or why they cannot.

    The options must price probe usage to the smallest currency unit as the tariff does.
    """
    try:
        options = materialise(definition)
    except NotRepresentable as err:
        return StoreChoice(reasons=err.reasons)
    options[CONF_BILL_START_DAY] = bill_start_day
    differences = prices_match(definition, options)
    if differences:
        return StoreChoice(reasons=["the saved rates do not price it to the cent"])
    return StoreChoice(options=options)


def source_record(picked: Mapping[str, str], definition: TariffDefinition) -> dict[str, Any]:
    """What is saved as `tariff_source`: enough to find this tariff in the store again.

    *picked* holds the country, provider, tariff and area the user chose.
    """
    return {
        "kind": SOURCE_KIND,
        "country": picked["country"],
        "provider": picked["provider"],
        "tariff": picked["tariff"],
        "area": picked["area"],
        "name": definition.name,
        "provider_name": definition.provider.name,
        "effective_from": definition.effective_from.isoformat(),
        "auto_update": True,
    }


def source_options(record: Mapping[str, Any], choice: StoreChoice) -> dict[str, Any]:
    """The option values a store tariff sets, the source record included."""
    return {**choice.options, CONF_TARIFF_SOURCE: dict(record)}


def _money(value: float, currency: str) -> str:
    return f"{value:g} {currency}"


def review_text(definition: TariffDefinition, choice: StoreChoice) -> str:
    """The tariff in the words of a bill, or why it cannot be used as the active tariff."""
    if not choice.usable:
        reasons = "\n".join(f"- {reason}" for reason in choice.reasons[:MAX_REASONS])
        return (
            f"{definition.name} cannot be used as your tariff yet, because:\n\n{reasons}\n\n"
            "Choose Enter it myself to type the rates in from your bill."
        )
    return _described(choice.options, definition)


def _described(options: Mapping[str, Any], definition: TariffDefinition) -> str:
    currency = str(options[CONF_CURRENCY])
    lines = [f"{options[CONF_BASE_RATE_NAME]}: {_money(options[CONF_BASE_RATE], currency)} per kWh"]
    lines += [
        f"{row['name']}: {_money(row['rate'], currency)} per kWh, {row['start']} to {row['end']}"
        for row in options[CONF_RATE_PERIODS]
    ]
    lines.append(f"Export: {_money(options[CONF_EXPORT_RATE], currency)} per kWh")
    lines.append(f"Standing charge: {_money(options[CONF_STANDING_CHARGE], currency)} per day")
    if options[CONF_PSO_LEVY]:
        lines.append(f"Levy: {_money(options[CONF_PSO_LEVY], currency)} per billing period")
    if options[CONF_DISCOUNT_RATE]:
        lines.append(f"Discount: {options[CONF_DISCOUNT_RATE]:g}% off the energy charge")
    if options[CONF_VAT_RATE]:
        where = "already in the prices" if options[CONF_VAT_INCLUDED] else "added to the prices"
        lines.append(f"VAT: {options[CONF_VAT_RATE]:g}%, {where}")
    since = f"Prices in force from {definition.effective_from:%-d %B %Y}, as published."
    source = f" Source: {definition.source_url}." if definition.source_url else ""
    rates = "\n".join(f"- {line}" for line in lines)
    return f"{rates}\n\n{since}{source} Check them against your bill."


def source_text(record: Mapping[str, Any] | None) -> str:
    """Where the saved tariff came from, in a sentence, for the menus and the change list."""
    if not isinstance(record, Mapping) or record.get("kind") not in {SOURCE_KIND, "based_on"}:
        return "Entered by hand"
    plan = f"{record.get('provider_name', record.get('provider'))} {record.get('name', '')}".strip()
    since = f"prices from {record.get('effective_from')}"
    if record["kind"] == "based_on":
        return f"{plan}, {since}, then edited by hand"
    return f"{plan}, {since}, from the store"
