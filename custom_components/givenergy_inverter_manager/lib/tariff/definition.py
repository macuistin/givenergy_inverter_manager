"""definition.py: a tariff and its bill written as data.

A definition is one document that holds everything needed to price energy and work out a bill:
the supplier, the dates it applies, the prices, the customer's own inputs and the bill as a tree
of nodes. It is data, not code. The only things a document can ask for are the node kinds listed
here, so a document from a shared store can do nothing but price.

The shape is described in `definition_parse.py`, which turns a JSON document into these types and
refuses anything it does not understand. Nothing here reads a price source or a slot. Money is
`Decimal` throughout, never a float.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, time, tzinfo
from decimal import Decimal
from enum import Enum

SCHEMA_VERSION = 1


class DefinitionError(ValueError):
    """A document that is not a valid definition. *path* names the field, such as `bill.total`."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path or 'definition'}: {message}")
        self.path = path


class NodeRounding(Enum):
    """How a node's amount is rounded before its parent uses it."""

    MINOR_UNIT = "minor_unit"  # to the currency's smallest unit, halves upward
    NONE = "none"  # keep full precision until the parent rounds


class TaxMode(Enum):
    """Whether a tax is added to the wrapped amount or already inside it."""

    ADDED = "added"
    INCLUDED = "included"


@dataclass(frozen=True)
class Provider:
    id: str  # stable slug, such as "example-energy"
    name: str  # for display, may change


@dataclass(frozen=True)
class Band:
    """The base price, charged when no zone applies."""

    name: str
    price: Decimal  # per kWh, in the document's currency


@dataclass(frozen=True)
class Zone:
    """A price that applies in some hours. The applicable zone of highest priority wins."""

    name: str
    priority: int  # unique across the tariff's zones
    price: Decimal
    start: time  # local clock time the zone begins
    end: time  # local clock time it ends. Earlier than start means it runs past midnight
    days: frozenset[int]  # weekdays it applies on, Monday 0 to Sunday 6. Empty means every day
    months: frozenset[int]  # months it applies in, 1 to 12. Empty means every month
    holidays_as_weekend: bool  # whether a public holiday counts as a weekend day


@dataclass(frozen=True)
class ImportPrices:
    base: Band
    zones: tuple[Zone, ...]


@dataclass(frozen=True)
class ExportPrices:
    """What exported energy is paid. With no zones it is one flat price."""

    base: Band
    zones: tuple[Zone, ...] = ()


@dataclass(frozen=True)
class InputSpec:
    """A value the customer supplies, with the range it must stay inside."""

    minimum: int
    maximum: int
    default: int


@dataclass(frozen=True)
class PeriodValue:
    """One whole number of the bill period: fixed by the tariff, or an input."""

    fixed: int | None
    input: str | None


StartDay = PeriodValue  # the name the start day had before the period gained other values


@dataclass(frozen=True)
class PeriodRule:
    """When a bill period starts and how long it runs.

    A period is *months* calendar months long and starts on *start_day* of a month. *start_month*
    names one month a period starts in, which places a period of two months or more in the year.
    """

    rule: str  # "monthly": the period is a whole number of calendar months
    start_day: PeriodValue
    months: PeriodValue = PeriodValue(1, None)
    start_month: PeriodValue = PeriodValue(1, None)


# The bill tree. Each node is worked out after everything inside it, so nesting sets the order.


@dataclass(frozen=True)
class EnergyByBand:
    """Import kWh in each band times the band's price."""

    round_bands: bool  # round each band's cost before adding them, as a supplier bill lists it
    rounding: NodeRounding


@dataclass(frozen=True)
class ExportCredit:
    """Export kWh times the export price, or the kWh in each export band times its price. A
    credit."""

    rounding: NodeRounding


@dataclass(frozen=True)
class PerDay:
    """An amount for each day of the bill."""

    amount: Decimal
    rounding: NodeRounding


@dataclass(frozen=True)
class PerPeriod:
    """An amount for the bill period, of which a bill carries the share of its days.

    With *per* "month" the amount is for one month, so a longer period charges it once a month.
    """

    amount: Decimal
    share: str  # "days_in_period" or "whole"
    rounding: NodeRounding
    per: str = "period"  # "period" or "month"


@dataclass(frozen=True)
class Adjust:
    """Wraps one node and adds a percentage of it. A saving is a negative percentage."""

    name: str
    percent: Decimal
    child: Node
    rounding: NodeRounding


@dataclass(frozen=True)
class Tax:
    """Wraps one node and adds, or reports, a percentage tax on everything inside it."""

    name: str
    percent: Decimal
    mode: TaxMode
    child: Node
    rounding: NodeRounding


@dataclass(frozen=True)
class Sum:
    """Adds its children. They are held by name, so their order never matters."""

    children: Mapping[str, Node]
    rounding: NodeRounding


Node = EnergyByBand | ExportCredit | PerDay | PerPeriod | Adjust | Tax | Sum


@dataclass(frozen=True)
class Check:
    """A worked bill the definition must reproduce. Another implementation can run it too."""

    period_days: int
    import_kwh_by_band: Mapping[str, Decimal]
    export_kwh: Decimal | Mapping[str, Decimal]  # one total, or the kWh in each export band
    expected_total: Decimal


@dataclass(frozen=True)
class TariffDefinition:
    """A validated tariff document. Build one with `parse_definition`."""

    id: str
    revision: int
    supersedes: int | None  # the earlier revision of this id this one replaces
    name: str
    service: str
    customer_class: str
    provider: Provider
    country: str  # ISO 3166-1 alpha-2
    region: str | None  # ISO 3166-2, or None for a national tariff
    currency: str  # ISO 4217
    timezone: tzinfo
    timezone_name: str
    effective_from: date  # included
    effective_to: date | None  # excluded, None while open ended
    source_url: str | None
    last_verified: date | None
    complete: bool  # False when the tree does not hold every charge on the supplier's bill
    inputs: Mapping[str, InputSpec]
    import_prices: ImportPrices
    export_prices: ExportPrices
    period: PeriodRule
    rounding_places: int  # decimal places of the currency's smallest unit
    total: Node
    checks: Mapping[str, Check]

    def period_value(self, value: PeriodValue) -> int:
        """The number *value* stands for: its fixed number, or the default of its input."""
        if value.fixed is not None:
            return value.fixed
        assert value.input is not None  # parse_definition accepts a fixed number or an input
        return self.inputs[value.input].default
