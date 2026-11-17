"""definition_savings.py: what solar and a battery saved in a bill period, under a definition.

The same sum as `savings`, for a tariff held as a `TariffDefinition`: the house load bought from
the grid, less what was paid, priced as two bills over the same days. The standing charge and
levies cancel. Export credit is on the paid side only. The change in stored energy is valued
at what the grid energy put into the battery cost, else the cheapest import band, and battery
wear is taken off. A house load reading is required.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from ..timeutil import shift_real
from .bands import band_at
from .defaults import SLOT_SECONDS
from .definition import TariffDefinition
from .period_bill import PeriodBill, PeriodRules, price_period
from .price_curve import marginal_prices
from .savings import Battery, all_from_grid
from .slot_history import SlotHistory
from .slots import SlotDay

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class SavingsOptions:
    """What the caller adds to the sum: the battery, and the bill rules of the period."""

    battery: Battery | None = None
    rules: PeriodRules = field(default_factory=PeriodRules)


@dataclass(frozen=True)
class DefinitionSavings:
    """The saving over a bill period so far, with the two bills it is the difference of."""

    without_system: PeriodBill  # the whole house load bought from the grid
    actual: PeriodBill
    bill_difference: Decimal  # without_system total less actual total
    stored_energy_value: Decimal  # value of the change in stored energy, negative for a fall
    battery_wear: Decimal
    total: Decimal  # bill_difference + stored_energy_value - battery_wear
    coverage: float  # share of the priced days' time that was observed, 0 to 1


def definition_savings(
    history: SlotHistory,
    definition: TariffDefinition,
    through: date,
    options: SavingsOptions | None = None,
) -> DefinitionSavings:
    """The saving from the start of the bill period holding *through* to *through* included.

    Raises ValueError when those days hold no house load.
    """
    battery, rules = (options.battery, options.rules) if options else (None, PeriodRules())
    actual = price_period(history, definition, through, rules)
    days = history.between(actual.first_day, through)
    if not any(day.total("house") for day in days):
        raise ValueError("no house load was recorded, so there is nothing to compare")
    baseline_history = SlotHistory.from_days(history.tz, [all_from_grid(day) for day in days])
    without = price_period(baseline_history, definition, through, rules)
    difference = _cents(without.priced.total - actual.priced.total)
    stored = _stored_value(days, definition, battery, rules.is_holiday)
    wear = _cents(Decimal(repr(sum(d.total("battery_discharge") for d in days))) * _wear(battery))
    return DefinitionSavings(
        without, actual, difference, stored, wear, difference + stored - wear, actual.coverage
    )


def _cents(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _wear(battery: Battery | None) -> Decimal:
    return Decimal(repr(battery.wear_per_kwh)) if battery else Decimal(0)


def _stored_value(
    days: list[SlotDay],
    definition: TariffDefinition,
    battery: Battery | None,
    is_holiday: Callable[[date], bool],
) -> Decimal:
    if battery is None or battery.capacity_kwh <= 0 or battery.soc_before_pct is None:
        return Decimal(0)
    closing = next(
        (v for day in reversed(days) for v in reversed(day.soc_pct) if v is not None), None
    )
    if closing is None:
        return Decimal(0)
    change_kwh = Decimal(repr((closing - battery.soc_before_pct) / 100 * battery.capacity_kwh))
    return _cents(change_kwh * _stored_rate(days, definition, is_holiday))


def _stored_rate(
    days: list[SlotDay], definition: TariffDefinition, is_holiday: Callable[[date], bool]
) -> Decimal:
    """Average cost of the grid energy that went into the battery, else the cheapest band."""
    prices = marginal_prices(definition).import_prices
    kwh = cost = Decimal(0)
    for day in days:
        for index, charged in enumerate(day.flows["grid_to_battery"]):
            if charged:
                start = shift_real(day.start, timedelta(seconds=index * SLOT_SECONDS))
                amount = Decimal(repr(charged))
                kwh += amount
                cost += amount * prices[band_at(definition, start, is_holiday)]
    return cost / kwh if kwh > 0 else min(prices.values())
