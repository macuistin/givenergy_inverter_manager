"""
tariff_source.py - copy a store tariff into the saved tariff options, and prove the copy is right.

The saved options describe a flat tariff: a base rate, timed rates where the cheapest wins, one
export rate, a standing charge, a monthly levy, a saving and VAT, either added on top of the prices
or already inside them (`vat_included`). A
tariff from the store is a document with richer rules. `materialise` turns the document into those
options when, and only when, the options can price it the same. `prices_match` is the proof: it
prices both over probe usage and compares the totals to the smallest currency unit.

Pure Python. It reads the tariff libraries and the option keys and nothing else, so no chain of
imports reaches the inverter (tests/test_shadow_cannot_write.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from typing import Any

from ..conf import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_CURRENCY,
    CONF_DISCOUNT_RATE,
    CONF_EXPORT_RATE,
    CONF_PSO_LEVY,
    CONF_RATE_PERIODS,
    CONF_STANDING_CHARGE,
    CONF_VAT_INCLUDED,
    CONF_VAT_RATE,
)
from ..lib.tariff import (
    BillInputs,
    Locale,
    TariffDefinition,
    definition_from_config,
    price_bill,
)
from ..lib.tariff.definition import (
    Adjust,
    EnergyByBand,
    ExportCredit,
    Node,
    PerDay,
    PerPeriod,
    Sum,
    Tax,
    TaxMode,
    Zone,
)
from .tariff_config import build_tariff

MAX_TIMED_RATES = 5  # the options form holds this many timed rates
SLOTS_PER_DAY = 48
PROBE_DAYS = 30
PROBE_EXPORTS = (Decimal(0), Decimal("47.5"))


class NotRepresentable(ValueError):
    """The options cannot price this tariff the same way. `reasons` say why, in plain words."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass
class _Charges:
    """The parts of a bill tree the options have a key for."""

    vat: Tax | None = None
    saving: Adjust | None = None
    standing: PerDay | None = None
    levy: PerPeriod | None = None
    energy: int = 0
    credit: int = 0
    other: int = 0


def _children(node: Node) -> list[Node]:
    if isinstance(node, Sum):
        return list(node.children.values())
    if isinstance(node, Tax | Adjust):
        return [node.child]
    return []


def _collect(node: Node, found: _Charges, *, taxed: bool) -> None:
    """*taxed* is True inside a tax that is added on top, where an export credit would be taxed."""
    if isinstance(node, Tax):
        found.other += found.vat is not None  # a second tax has no key
        found.vat = node
    elif isinstance(node, Adjust):
        found.other += found.saving is not None
        found.saving = node
    elif isinstance(node, PerDay):
        found.other += found.standing is not None
        found.standing = node
    elif isinstance(node, PerPeriod):
        found.other += found.levy is not None or node.share != "days_in_period"
        found.levy = node
    elif isinstance(node, EnergyByBand):
        found.energy += 1
        found.other += not node.round_bands
    elif isinstance(node, ExportCredit):
        found.credit += 1
        found.other += taxed  # the options pay the export credit outside the tax
    adds_tax = isinstance(node, Tax) and node.mode is TaxMode.ADDED
    for child in _children(node):
        _collect(child, found, taxed=taxed or adds_tax)


def _charge_reasons(found: _Charges) -> list[str]:
    reasons = []
    if found.energy != 1 or found.standing is None:
        reasons.append("the bill is not energy plus a daily standing charge")
    if found.other:
        reasons.append("the bill has a charge, tax or rounding rule the options cannot hold")
    if found.saving is not None and not isinstance(found.saving.child, EnergyByBand):
        reasons.append("the saving is applied to more than the energy")
    return reasons


def _clock(value: time) -> str:
    return f"{value:%H:%M}"


def _covered(zone: Zone) -> set[int]:
    """The half hours of the day a zone covers."""
    start = value_slot(zone.start)
    end = value_slot(zone.end)
    if start < end:
        return set(range(start, end))
    return set(range(start, SLOTS_PER_DAY)) | set(range(end))


def value_slot(value: time) -> int:
    return value.hour * 2 + value.minute // 30


def _zone_reasons(zones: tuple[Zone, ...]) -> list[str]:
    reasons = []
    if any(z.days or z.months or z.holidays_as_weekend for z in zones):
        reasons.append("it has weekday, seasonal or public holiday rates")
    if len(zones) > MAX_TIMED_RATES:
        reasons.append(f"it has more than {MAX_TIMED_RATES} timed rates")
    if any(z.start.minute % 30 or z.end.minute % 30 for z in zones):
        reasons.append("a timed rate starts or ends between half hours")
    if _cheapest_is_not_last(zones):
        reasons.append("a dearer timed rate overrides a cheaper one it overlaps")
    return reasons


def _cheapest_is_not_last(zones: tuple[Zone, ...]) -> bool:
    """True when, in some half hour, the zone that wins by priority is not the cheapest there."""
    covers = [(z, _covered(z)) for z in zones]
    for slot in range(SLOTS_PER_DAY):
        active = [z for z, covered in covers if slot in covered]
        if len(active) > 1:
            winner = max(active, key=lambda z: z.priority)
            if any(z.price < winner.price for z in active):
                return True
    return False


def _number(value: Decimal) -> float:
    return float(value)


def _periods(definition: TariffDefinition) -> list[dict[str, Any]]:
    ordered = sorted(definition.import_prices.zones, key=lambda z: z.priority)
    return [
        {
            "name": z.name,
            "rate": _number(z.price),
            "start": _clock(z.start),
            "end": _clock(z.end),
        }
        for z in ordered
    ]


def materialise(definition: TariffDefinition) -> dict[str, Any]:
    """The tariff options that price *definition*, without the bill start day.

    Raises NotRepresentable, with every reason found, when the options cannot hold it. A result is
    only a candidate until `prices_match` agrees.
    """
    found = _Charges()
    _collect(definition.total, found, taxed=False)
    reasons = _charge_reasons(found)
    reasons += _zone_reasons(definition.import_prices.zones)
    if definition.export_prices.zones:
        reasons.append("the export price changes by time of day")
    if reasons or found.standing is None:
        raise NotRepresentable(reasons)
    vat = found.vat
    return {
        CONF_BASE_RATE: _number(definition.import_prices.base.price),
        CONF_BASE_RATE_NAME: definition.import_prices.base.name,
        CONF_RATE_PERIODS: _periods(definition),
        CONF_EXPORT_RATE: _number(definition.export_prices.base.price),
        CONF_STANDING_CHARGE: _number(found.standing.amount),
        CONF_PSO_LEVY: _number(found.levy.amount) if found.levy else 0.0,
        CONF_VAT_RATE: _number(vat.percent) if vat else 0.0,
        CONF_VAT_INCLUDED: bool(vat and vat.mode is TaxMode.INCLUDED),
        CONF_DISCOUNT_RATE: _number(-found.saving.percent) if found.saving else 0.0,
        CONF_CURRENCY: definition.currency,
    }


def _probe_usage(names: list[str]) -> list[Mapping[str, Decimal]]:
    """Fixed, awkward usage: whole numbers, many decimals and an unused band."""
    shapes = ("257", "12.345", "0.004", "1234.567")
    probes: list[Mapping[str, Decimal]] = []
    for shape in shapes:
        probes.append({n: Decimal(shape) + Decimal(i) / 7 for i, n in enumerate(names)})
    probes.append({n: Decimal(0) if i else Decimal(99) for i, n in enumerate(names)})
    return probes


def prices_match(
    definition: TariffDefinition,
    options: Mapping[str, Any],
    exports: tuple[Decimal, ...] = PROBE_EXPORTS,
) -> list[str]:
    """What differs when *options* price the same usage as *definition*. Empty means it matches.

    Each probe is a whole bill, so the totals must agree to the currency's smallest unit. *exports*
    are the exported kWh probed. A typed export rate leaves out the non-zero one, because the
    tariff pays nothing for export to compare it with.
    """
    own = definition_from_config(
        build_tariff({**options, "bill_start_day": 1}),
        Locale(definition.currency, definition.country, definition.timezone_name,
               definition.effective_from),
    )
    names = [definition.import_prices.base.name] + [z.name for z in definition.import_prices.zones]
    differences = []
    for days in (28, PROBE_DAYS, 31):
        for usage in _probe_usage(names):
            for export in exports:
                bill = BillInputs(days, PROBE_DAYS, usage, export)
                want = price_bill(definition, bill).total
                got = price_bill(own, bill).total
                if want != got:
                    differences.append(f"{days} days, usage {dict(usage)}: {want} against {got}")
    return differences
