"""engine.py: price a bill from a tariff definition, with an amount on every node of the tree.

The engine reads only totals: the kWh in each import band, the export kWh (one figure, or the
kWh in each export band) and the days of the bill. Turning slots into band totals is a separate
step, so the same arithmetic prices a worked check, a re-priced history or a live month. It does
all sums in `Decimal`.

Each node is worked out after everything inside it, so the tree sets the order and the tax base.
A node is rounded to the currency's smallest unit, halves upward, unless it says `round: none`.
A credit is a negative amount, so the total is plain addition.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .definition import (
    Adjust,
    EnergyByBand,
    ExportCredit,
    Node,
    NodeRounding,
    PerDay,
    PerPeriod,
    Sum,
    TariffDefinition,
    Tax,
    TaxMode,
)

_HUNDRED = Decimal(100)


class CheckFailed(ValueError):
    """A worked bill in a definition did not give the total the definition expects."""


@dataclass(frozen=True)
class BillInputs:
    """What a bill is priced from."""

    days: int  # days the bill covers
    period_days: int  # days in the whole bill period, which sets the share of a period charge
    import_kwh_by_band: Mapping[str, Decimal]
    # One total, paid at the base export price, or the kWh in each export band.
    export_kwh: Decimal | Mapping[str, Decimal]


@dataclass(frozen=True)
class Line:
    """One node of the bill with its amount. *children* holds the lines inside it, by name."""

    kind: str
    amount: Decimal
    name: str | None = None  # the name an adjust or tax node gives itself
    tax: Decimal | None = None  # the tax reported by a tax node, added or already included
    children: Mapping[str, Line] = field(default_factory=dict)


@dataclass(frozen=True)
class PricedBill:
    """A priced bill: the tree with its amounts, and the total."""

    total: Decimal
    root: Line


def price_bill(definition: TariffDefinition, inputs: BillInputs) -> PricedBill:
    """The bill for *inputs* under *definition*."""
    if inputs.days < 1 or inputs.period_days < 1:
        raise ValueError("days and period_days must be at least 1")
    root = _Pricer(definition, inputs).line(definition.total)
    return PricedBill(root.amount, root)


def verify_checks(definition: TariffDefinition) -> None:
    """Price each worked bill in *definition*. Raises CheckFailed for the first that differs."""
    for name, check in definition.checks.items():
        inputs = BillInputs(
            check.period_days, check.period_days, check.import_kwh_by_band, check.export_kwh
        )
        total = price_bill(definition, inputs).total
        if total != check.expected_total:
            raise CheckFailed(f"check {name!r} gives {total}, expected {check.expected_total}")


class _Pricer:
    def __init__(self, definition: TariffDefinition, inputs: BillInputs) -> None:
        self._unit = Decimal(1).scaleb(-definition.rounding_places)
        self._prices = {definition.import_prices.base.name: definition.import_prices.base.price}
        self._prices.update({zone.name: zone.price for zone in definition.import_prices.zones})
        exported = definition.export_prices
        self._export_base = exported.base.name
        self._export_prices = {exported.base.name: exported.base.price}
        self._export_prices.update({zone.name: zone.price for zone in exported.zones})
        self._inputs = inputs

    def _round(self, value: Decimal, rounding: NodeRounding) -> Decimal:
        if rounding is NodeRounding.NONE:
            return value
        return value.quantize(self._unit, ROUND_HALF_UP)

    def line(self, node: Node) -> Line:
        if isinstance(node, EnergyByBand):
            return self._energy(node)
        if isinstance(node, ExportCredit):
            return self._export(node)
        if isinstance(node, PerDay):
            amount = node.amount * self._inputs.days
            return Line("per_day", self._round(amount, node.rounding))
        if isinstance(node, PerPeriod):
            return self._per_period(node)
        if isinstance(node, Adjust):
            return self._adjust(node)
        if isinstance(node, Tax):
            return self._tax(node)
        return self._sum(node)

    def _energy(self, node: EnergyByBand) -> Line:
        costs = {}
        for band, kwh in self._inputs.import_kwh_by_band.items():
            cost = kwh * self._prices[band]
            costs[band] = self._round(cost, node.rounding) if node.round_bands else cost
        children = {band: Line("band", cost) for band, cost in costs.items()}
        amount = self._round(sum(costs.values(), Decimal(0)), node.rounding)
        return Line("energy_by_band", amount, children=children)

    def _export(self, node: ExportCredit) -> Line:
        exported = self._inputs.export_kwh
        if not isinstance(exported, Mapping):
            exported = {self._export_base: exported}
        credits = {band: -kwh * self._export_prices[band] for band, kwh in exported.items()}
        amount = self._round(sum(credits.values(), Decimal(0)), node.rounding)
        # A flat export keeps the line it always had. Bands are listed only when there are some.
        if len(self._export_prices) == 1:
            return Line("export_credit", amount)
        children = {band: Line("band", credit) for band, credit in credits.items()}
        return Line("export_credit", amount, children=children)

    def _per_period(self, node: PerPeriod) -> Line:
        amount = node.amount
        if node.share == "days_in_period":
            amount = amount * self._inputs.days / self._inputs.period_days
        return Line("per_period", self._round(amount, node.rounding))

    def _adjust(self, node: Adjust) -> Line:
        inner = self.line(node.child)
        change = self._round(inner.amount * node.percent / _HUNDRED, node.rounding)
        amount = self._round(inner.amount + change, node.rounding)
        return Line("adjust", amount, node.name, change, {"of": inner})

    def _tax(self, node: Tax) -> Line:
        inner = self.line(node.child)
        if node.mode is TaxMode.ADDED:
            tax = self._round(inner.amount * node.percent / _HUNDRED, node.rounding)
            amount = self._round(inner.amount + tax, node.rounding)
        else:
            share = inner.amount * node.percent / (_HUNDRED + node.percent)
            tax = self._round(share, node.rounding)
            amount = inner.amount
        return Line("tax", amount, node.name, tax, {"of": inner})

    def _sum(self, node: Sum) -> Line:
        children = {name: self.line(child) for name, child in node.children.items()}
        amount = self._round(sum((c.amount for c in children.values()), Decimal(0)), node.rounding)
        return Line("sum", amount, children=children)
