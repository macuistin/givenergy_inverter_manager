"""
search.py: rank every plan of a store against the current one over past usage.

The history holds energy and no price, so each plan is priced over the same days by the same bill
engine. The window is a number of weeks, or a number of whole bills of the current tariff. A
re-pricing of measured usage, never a forecast, and it never writes: this module imports only the
tariff library.

A plan with no export price is priced with the export rate the user gave for it, or is left out
when none was given (`needs_export_rate`). The current plan is always priced as saved, since an
export rate of 0 is a real choice for it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

from ..tariff import BillInputs, SlotHistory, TariffDefinition, price_bill
from ..tariff.bands import export_by_band, import_by_band, no_holidays
from ..tariff.period_bill import bill_period_bounds

MAX_WEEKS = 104
MAX_BILLS = 24
AVERAGE_MONTH_DAYS = 30  # the period a weeks window shares the monthly levy over
TOP = 3


class Unit(Enum):
    WEEKS = "weeks"
    BILLS = "bills"


@dataclass(frozen=True)
class Window:
    unit: Unit
    count: int

    def __post_init__(self) -> None:
        limit = MAX_WEEKS if self.unit is Unit.WEEKS else MAX_BILLS
        if not 1 <= self.count <= limit:
            raise ValueError(f"the window must be 1 to {limit} {self.unit.value}")


@dataclass(frozen=True)
class DayRange:
    first: date
    last: date  # included
    period_days: int  # days the monthly charges are shared over


@dataclass(frozen=True)
class Candidate:
    key: str
    label: str
    definition: TariffDefinition
    export_rate: Decimal | None = None  # typed by the user for a plan with no export price


@dataclass(frozen=True)
class Ranked:
    key: str
    label: str
    total: float
    difference: float  # this plan less the current one: negative is cheaper
    rank: int


@dataclass(frozen=True)
class SearchResult:
    ranked: tuple[Ranked, ...]
    current_rank: int
    first_day: date
    last_day: date
    days: int
    days_recorded: int
    data_from: date | None
    skipped: int  # plans left out

    @property
    def compared(self) -> int:
        return len(self.ranked)


def ranges(window: Window, through: date, start_day: int, months: int = 1) -> list[DayRange]:
    """The day ranges to price, ending with the day *through* (weeks) or the last whole bill."""
    if window.unit is Unit.WEEKS:
        first = through - timedelta(days=window.count * 7 - 1)
        return [DayRange(first, through, AVERAGE_MONTH_DAYS)]
    first_of_open, _ = bill_period_bounds(start_day, through, months)
    found: list[DayRange] = []
    cursor = first_of_open
    for _ in range(window.count):
        first, following = bill_period_bounds(start_day, cursor - timedelta(days=1), months)
        found.append(DayRange(first, following - timedelta(days=1), (following - first).days))
        cursor = first
    return sorted(found, key=lambda r: r.first)


def needs_export_rate(definition: TariffDefinition) -> bool:
    """True when the plan lists no export price, so the user's own rate is needed to price it."""
    prices = definition.export_prices
    return not (prices.base.price > 0 or prices.zones)


def with_export_rate(definition: TariffDefinition, rate: Decimal) -> TariffDefinition:
    """*definition* paying *rate* for export, when it lists none."""
    if not needs_export_rate(definition):
        return definition
    base = replace(definition.export_prices.base, price=rate)
    return replace(definition, export_prices=replace(definition.export_prices, base=base))


@dataclass(frozen=True)
class Usage:
    """The measured usage to price: the history, the day ranges and the holiday calendar."""

    history: SlotHistory
    spans: Sequence[DayRange]
    is_holiday: Callable[[date], bool] = no_holidays


def price_ranges(usage: Usage, definition: TariffDefinition) -> Decimal:
    """The total of the bills for the usage's spans priced under *definition*."""
    is_holiday = usage.is_holiday
    total = Decimal(0)
    for span in usage.spans:
        days = usage.history.between(span.first, span.last)
        export: Decimal | dict[str, Decimal]
        if definition.export_prices.zones:
            export = export_by_band(days, definition, is_holiday)
        else:
            export = Decimal(repr(round(sum(d.total("export") for d in days), 6)))
        length = (span.last - span.first).days + 1
        inputs = BillInputs(
            length, span.period_days, import_by_band(days, definition, is_holiday), export
        )
        total += price_bill(definition, inputs).total
    return total


def search(usage: Usage, current: Candidate, others: Sequence[Candidate]) -> SearchResult:
    """Price *current* and every candidate over the usage and rank them, cheapest first."""
    spans = usage.spans
    skipped = 0
    priced: list[tuple[Candidate, Decimal]] = []
    for candidate in [current, *others]:
        definition = candidate.definition
        if needs_export_rate(definition) and candidate.key != current.key:
            if candidate.export_rate is None:
                skipped += 1
                continue
            definition = with_export_rate(definition, candidate.export_rate)
        priced.append((candidate, price_ranges(usage, definition)))
    priced.sort(key=lambda item: (item[1], item[0].key != current.key, item[0].label))
    base = next(total for cand, total in priced if cand.key == current.key)
    ranked = tuple(
        Ranked(c.key, c.label, float(t), float(t - base), index)
        for index, (c, t) in enumerate(priced, start=1)
    )
    days = usage.history.between(spans[0].first, spans[-1].last)
    return SearchResult(
        ranked=ranked,
        current_rank=next(r.rank for r in ranked if r.key == current.key),
        first_day=spans[0].first,
        last_day=spans[-1].last,
        days=(spans[-1].last - spans[0].first).days + 1,
        days_recorded=len(days),
        data_from=days[0].day if days else None,
        skipped=skipped,
    )


def rank_sentence(result: SearchResult) -> str:
    """Where the current plan stands, in words."""
    rank, total = result.current_rank, result.compared
    if rank == 1:
        return f"Your plan is the cheapest of the {total} compared."
    if rank <= TOP:
        return f"Your plan is number {rank} of the {total} compared, in the top {TOP}."
    gap = result.ranked[rank - 1].total - result.ranked[0].total
    return f"Your plan is number {rank} of the {total} compared, {gap:.2f} above the cheapest."
