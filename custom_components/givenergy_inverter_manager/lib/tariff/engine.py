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
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal

from .definition import (
    Adjust,
    Block,
    Bound,
    Demand,
    EnergyByBand,
    ExportCredit,
    Node,
    NodeRounding,
    PerDay,
    PerKwh,
    PerPeriod,
    SeriesEnergy,
    Sum,
    TariffDefinition,
    Tax,
    TaxMode,
    TieredEnergy,
)

_HUNDRED = Decimal(100)


class CheckFailed(ValueError):
    """A worked bill in a definition did not give the total the definition expects."""


class MissingPeak(ValueError):
    """A bill has a demand charge and no peak kW was given for its window."""


class MissingSeries(ValueError):
    """A bill has a series energy node and no cost was given for its series."""


@dataclass(frozen=True)
class BillInputs:
    """What a bill is priced from."""

    days: int  # days the bill covers
    period_days: int  # days in the whole bill period, which sets the share of a period charge
    import_kwh_by_band: Mapping[str, Decimal]
    # One total, paid at the base export price, or the kWh in each export band.
    export_kwh: Decimal | Mapping[str, Decimal]
    # Months in the whole bill period, for a charge made once a month. None uses the definition's.
    period_months: int | None = None
    # The highest half-hour kW in each demand window of the bill. A window the tree uses and this
    # leaves out is refused, never priced as zero.
    peak_kw: Mapping[str, Decimal] = field(default_factory=dict)
    # The cost of the import kWh under each price series the tree names, from `series_cost`. A
    # series the tree uses and this leaves out is refused, never priced as zero.
    import_cost_by_series: Mapping[str, Decimal] = field(default_factory=dict)


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
            check.period_days, check.period_days, check.import_kwh_by_band, check.export_kwh,
            peak_kw=check.peak_kw,
        )
        total = price_bill(definition, inputs).total
        if total != check.expected_total:
            raise CheckFailed(f"check {name!r} gives {total}, expected {check.expected_total}")


def _kwh_in(block: Block, scale: Decimal, total: Decimal) -> Decimal:
    """The kWh of *total* that fall inside *block*, with its limits multiplied by *scale*."""
    top = total if block.end is None else min(total, block.end * scale)
    return max(top - block.start * scale, Decimal(0))


def _netted(definition: TariffDefinition, inputs: BillInputs) -> BillInputs:
    """Inputs with export offset against import in the band of the same name, when the tariff nets.

    Only the kWh left over are priced: import that remains in each band, and the export that no
    import absorbed. There is no banking, so a surplus is paid, never carried to the next bill."""
    if definition.netting != "band":
        return inputs
    exported = inputs.export_kwh
    if not isinstance(exported, Mapping):
        exported = {definition.export_prices.base.name: exported}
    imported = dict(inputs.import_kwh_by_band)
    leftover: dict[str, Decimal] = {}
    for band, kwh in exported.items():
        offset = min(imported.get(band, Decimal(0)), kwh)
        if band in imported:
            imported[band] -= offset
        leftover[band] = kwh - offset
    return replace(inputs, import_kwh_by_band=imported, export_kwh=leftover)


class _Pricer:
    def __init__(self, definition: TariffDefinition, inputs: BillInputs) -> None:
        self._unit = Decimal(1).scaleb(-definition.rounding_places)
        self._prices = {definition.import_prices.base.name: definition.import_prices.base.price}
        self._prices.update({zone.name: zone.price for zone in definition.import_prices.zones})
        exported = definition.export_prices
        self._export_base = exported.base.name
        self._export_prices = {exported.base.name: exported.base.price}
        self._export_prices.update({zone.name: zone.price for zone in exported.zones})
        self._inputs = _netted(definition, inputs)
        self._months = inputs.period_months or definition.period_value(definition.period.months)

    def _round(self, value: Decimal, rounding: NodeRounding) -> Decimal:
        if rounding is NodeRounding.NONE:
            return value
        return value.quantize(self._unit, ROUND_HALF_UP)

    def line(self, node: Node) -> Line:
        leaf = self._leaf(node)
        if leaf is not None:
            return leaf
        if isinstance(node, Adjust):
            return self._adjust(node)
        if isinstance(node, Tax):
            return self._tax(node)
        if isinstance(node, Bound):
            return self._bound(node)
        assert isinstance(node, Sum)  # every other kind was handled by _leaf
        return self._sum(node)

    def _leaf(self, node: Node) -> Line | None:
        """The line for a node that holds no other node, or None for one that does."""
        if isinstance(node, EnergyByBand | SeriesEnergy | TieredEnergy):
            return self._import_energy(node)
        if isinstance(node, ExportCredit):
            return self._export(node)
        if isinstance(node, PerDay):
            return Line("per_day", self._round(node.amount * self._inputs.days, node.rounding))
        if isinstance(node, PerKwh):
            return self._per_kwh(node)
        if isinstance(node, Demand):
            return self._demand(node)
        if isinstance(node, PerPeriod):
            return self._per_period(node)
        return None

    def _import_energy(self, node: EnergyByBand | SeriesEnergy | TieredEnergy) -> Line:
        if isinstance(node, SeriesEnergy):
            return self._series(node)
        return self._tiered(node) if isinstance(node, TieredEnergy) else self._energy(node)

    def _energy(self, node: EnergyByBand) -> Line:
        costs = {}
        for band, kwh in self._inputs.import_kwh_by_band.items():
            cost = kwh * self._prices[band]
            costs[band] = self._round(cost, node.rounding) if node.round_bands else cost
        children = {band: Line("band", cost) for band, cost in costs.items()}
        amount = self._round(sum(costs.values(), Decimal(0)), node.rounding)
        return Line("energy_by_band", amount, children=children)

    def _series(self, node: SeriesEnergy) -> Line:
        if node.series not in self._inputs.import_cost_by_series:
            raise MissingSeries(f"no cost was given for the price series {node.series!r}")
        cost = self._inputs.import_cost_by_series[node.series]
        return Line("series_energy", self._round(cost, node.rounding))

    def _tiered(self, node: TieredEnergy) -> Line:
        in_scope = (
            kwh for band, kwh in self._inputs.import_kwh_by_band.items()
            if not node.bands or band in node.bands
        )
        total = sum(in_scope, Decimal(0))
        scale = self._limit_scale(node.limits)
        costs = {
            name: _kwh_in(block, scale, total) * block.price
            for name, block in node.blocks.items()
        }
        children = {name: Line("block", cost) for name, cost in costs.items()}
        amount = self._round(sum(costs.values(), Decimal(0)), node.rounding)
        return Line("tiered_energy", amount, children=children)

    def _bound(self, node: Bound) -> Line:
        inner = self.line(node.child)
        limit = self._round(node.amount * self._limit_scale(node.per), node.rounding)
        pick = max if node.kind == "minimum" else min
        return Line(node.kind, pick(inner.amount, limit), children={"of": inner})

    def _limit_scale(self, limits: str) -> Decimal:
        """How many times the written block limits fit in this bill."""
        if limits == "day":
            return Decimal(self._inputs.days)
        return Decimal(self._months) if limits == "month" else Decimal(1)

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

    def _per_kwh(self, node: PerKwh) -> Line:
        if node.on == "import":
            kwh = sum(self._inputs.import_kwh_by_band.values(), Decimal(0))
        else:
            exported = self._inputs.export_kwh
            kwh = sum(exported.values(), Decimal(0)) if isinstance(exported, Mapping) else exported
        return Line("per_kwh", self._round(kwh * node.amount, node.rounding))

    def _demand(self, node: Demand) -> Line:
        if node.window not in self._inputs.peak_kw:
            raise MissingPeak(f"no peak kW was given for the demand window {node.window!r}")
        months = Decimal(self._months) if node.per == "month" else Decimal(1)
        amount = node.price * self._inputs.peak_kw[node.window] * months
        return Line("demand", self._round(amount, node.rounding))

    def _per_period(self, node: PerPeriod) -> Line:
        amount = node.amount * self._months if node.per == "month" else node.amount
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
