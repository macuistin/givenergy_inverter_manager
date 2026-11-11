"""period_bill.py: the bill so far for the current bill period, priced from the slot history.

    slots  ->  bands.import_by_band, export_by_band  ->  engine.price_bill  ->  bill

The history holds energy and no price, so any tariff definition can be priced over the same days
with the same engine and the same rounding. The bill period comes from the definition's own start
day, or from a start day the caller passes, so a re-priced bill can follow the active tariff's
dates. The bill covers the days from the period start to the day given, that day included.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .bands import export_by_band, import_by_band, no_holidays
from .definition import TariffDefinition
from .engine import BillInputs, PricedBill, price_bill
from .slot_history import SlotHistory


@dataclass(frozen=True)
class PeriodRules:
    """What the caller decides about the period, beyond the definition itself."""

    start_day: int | None = None  # follow another tariff's bill dates; None uses the definition's
    is_holiday: Callable[[date], bool] = no_holidays


@dataclass(frozen=True)
class PeriodBill:
    """A bill period priced from the history."""

    first_day: date  # first day of the bill period
    next_first_day: date  # first day of the next period
    through: date  # last day priced, included
    days: int  # days priced, from first_day to through
    period_days: int  # days in the whole bill period
    data_from: date | None  # first day in the history inside the period, None when none
    days_recorded: int  # days inside the period the history holds
    import_kwh_by_band: Mapping[str, Decimal]  # the import the bill priced, by band name
    coverage: float  # share of the priced days' time that was observed, 0 to 1
    priced: PricedBill


def start_day_of(definition: TariffDefinition) -> int:
    """The day of the month the definition's bill period starts."""
    start = definition.period.start_day
    if start.fixed is not None:
        return start.fixed
    assert start.input is not None  # parse_definition accepts a fixed day or an input
    return definition.inputs[start.input].default


def bill_period_bounds(start_day: int, on: date) -> tuple[date, date]:
    """The first day of the bill period holding *on*, and the first day of the next period.

    A start day past the end of a short month falls on that month's last day.
    """
    this_start = _start_in_month(start_day, on.year, on.month)
    if on >= this_start:
        year, month = (on.year + 1, 1) if on.month == 12 else (on.year, on.month + 1)
        return this_start, _start_in_month(start_day, year, month)
    year, month = (on.year - 1, 12) if on.month == 1 else (on.year, on.month - 1)
    return _start_in_month(start_day, year, month), this_start


def price_period(
    history: SlotHistory,
    definition: TariffDefinition,
    through: date,
    rules: PeriodRules | None = None,
) -> PeriodBill:
    """The bill so far for the period holding *through*, priced under *definition*.

    *rules.start_day* overrides the definition's own bill start day. Days with no history count as
    days of the bill with no import, so *coverage* tells a quiet day from a missing one.
    """
    rules = rules or PeriodRules()
    first, following = bill_period_bounds(rules.start_day or start_day_of(definition), through)
    days = history.between(first, through)
    bands = import_by_band(days, definition, rules.is_holiday)
    # A flat export stays one total, so its credit is unchanged to the last decimal place.
    export: Decimal | dict[str, Decimal]
    if definition.export_prices.zones:
        export = export_by_band(days, definition, rules.is_holiday)
    else:
        export = _decimal(sum(day.total("export") for day in days))
    length = (through - first).days + 1
    inputs = BillInputs(length, (following - first).days, bands, export)
    return PeriodBill(
        first_day=first,
        next_first_day=following,
        through=through,
        days=length,
        period_days=(following - first).days,
        data_from=days[0].day if days else None,
        days_recorded=len(days),
        import_kwh_by_band=bands,
        coverage=sum(day.coverage for day in days) / length,
        priced=price_bill(definition, inputs),
    )


def _start_in_month(start_day: int, year: int, month: int) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, max(1, min(start_day, last)))


def _decimal(value: float) -> Decimal:
    return Decimal(repr(round(value, 6)))
