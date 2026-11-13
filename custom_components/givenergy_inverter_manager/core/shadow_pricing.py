"""
shadow_pricing.py - what the usage of this bill period would cost under each shadow tariff.

The bill of every tariff, the active one included, is worked out the same way: the stored
half-hourly slots go through the same band matching and the same bill engine, over the bill
period of the active tariff. The two totals are therefore like for like, and the difference is
down to the rates alone. Every figure is a re-pricing of measured usage. Nothing here can write:
this module imports only the option keys, the shadow list and the tariff library.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from html import escape
from typing import Any

from ..conf import CONF_SHADOW_TARIFFS
from ..lib.tariff import (
    DefinitionError,
    Line,
    Locale,
    PeriodBill,
    SlotHistory,
    TariffDefinition,
    definition_from_config,
    price_period,
)
from .html_table import bold, html_table
from .shadow_tariffs import KEY_NAME, shadow_config, shadow_entries
from .tariff_config import build_tariff

# The pricing never reads the currency, the country or the start date of a definition. These
# are the codes the document format reserves for "none": ISO 4217 XXX and ISO 3166 ZZ.
_NO_CURRENCY = "XXX"
_NO_COUNTRY = "ZZ"
_ALWAYS = date(2000, 1, 1)


@dataclass(frozen=True)
class BandCost:
    """The import in one band of a tariff and what it cost."""

    band: str
    kwh: float
    cost: float


@dataclass(frozen=True)
class ShadowBill:
    """One shadow tariff's bill so far."""

    name: str
    key: str  # a stable word for entity ids and unique ids, from the name
    total: float
    difference: float  # the shadow's total less the active tariff's: positive costs more
    data_from: date | None  # first day inside the bill period the history holds
    coverage: float  # observed share of the days priced, 0 to 1
    days_recorded: int  # days inside the bill period that the history holds
    bands: tuple[BandCost, ...]  # import and cost by band, in the order the bands were met


@dataclass(frozen=True)
class ShadowReport:
    """The active tariff and each shadow, priced over the same days."""

    active_total: float
    first_day: date
    through: date
    days: int
    period_days: int
    active_data_from: date | None
    bills: tuple[ShadowBill, ...]


def shadow_key(name: str, taken: set[str]) -> str:
    """A lowercase word for *name* that is not in *taken*, which it joins."""
    base = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_") or "tariff"
    key, number = base, 2
    while key in taken:
        key, number = f"{base}_{number}", number + 1
    taken.add(key)
    return key


def shadow_keys(raw: Any) -> list[str]:
    """The key of each saved shadow tariff, in order."""
    taken: set[str] = set()
    return [shadow_key(str(entry[KEY_NAME]), taken) for entry in shadow_entries(raw)]


def _definition(config: Mapping[str, Any], timezone_name: str) -> TariffDefinition:
    return definition_from_config(
        build_tariff(dict(config)), Locale(_NO_CURRENCY, _NO_COUNTRY, timezone_name, _ALWAYS)
    )


def price_shadows(
    history: SlotHistory,
    active: Mapping[str, Any],
    through: date,
    timezone_name: str,
) -> ShadowReport | None:
    """The report for the bill period holding *through*, None when there is nothing to show.

    *active* is the config in force. It holds the shadow tariffs.

    Nothing to show means no shadow tariff is saved, or a tariff cannot be written as a
    definition, for example a bill start day past the 28th.
    """
    entries = shadow_entries(active.get(CONF_SHADOW_TARIFFS))
    if not entries:
        return None
    try:
        real = price_period(history, _definition(active, timezone_name), through)
        priced = [
            price_period(history, _definition(shadow_config(entry, active), timezone_name), through)
            for entry in entries
        ]
    except DefinitionError:
        return None
    active_total = float(real.priced.total)
    taken: set[str] = set()
    bills = tuple(
        ShadowBill(
            name=str(entry[KEY_NAME]),
            key=shadow_key(str(entry[KEY_NAME]), taken),
            total=float(bill.priced.total),
            difference=round(float(bill.priced.total) - active_total, 2),
            data_from=bill.data_from,
            coverage=bill.coverage,
            days_recorded=bill.days_recorded,
            bands=_band_costs(bill),
        )
        for entry, bill in zip(entries, priced, strict=True)
    )
    return ShadowReport(
        active_total, real.first_day, through, real.days, real.period_days, real.data_from, bills
    )


def _band_costs(bill: PeriodBill) -> tuple[BandCost, ...]:
    """Each band's kWh beside its cost, read from the energy line of the priced bill."""
    energy = _energy_line(bill.priced.root)
    if energy is None:
        return ()
    return tuple(
        BandCost(band, float(kwh), float(energy.children[band].amount))
        for band, kwh in bill.import_kwh_by_band.items()
        if band in energy.children
    )


def _energy_line(line: Line) -> Line | None:
    """The first energy-by-band line in the bill tree, or None when the tariff has none."""
    if line.kind == "energy_by_band":
        return line
    for child in line.children.values():
        found = _energy_line(child)
        if found is not None:
            return found
    return None


def bands_table(bill: ShadowBill, symbol: str) -> str:
    """The bill's import by band as a table that fills its card, with a total row.

    Empty without bands.
    """
    if not bill.bands:
        return ""
    rows = [[escape(b.band), f"{b.kwh:.1f}", f"{symbol}{b.cost:.2f}"] for b in bill.bands]
    total_kwh = sum(b.kwh for b in bill.bands)
    total_cost = sum(b.cost for b in bill.bands)
    rows.append([bold("Total"), bold(f"{total_kwh:.1f}"), bold(f"{symbol}{total_cost:.2f}")])
    return html_table(["Band", "kWh", "Energy cost"], rows)
