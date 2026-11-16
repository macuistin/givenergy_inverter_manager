"""savings.py: what solar and a battery saved over some days, from the half-hourly history.

The saving is what the house load would have cost bought from the grid at the rate in force,
less what was paid. Both sides are priced as a bill under the same tariff, so the discount,
VAT and levies apply to each, and the standing charge cancels. Export credit is on the paid
side only: it is money the system earned.

Two corrections keep the figure fair, as in stored_energy.py. Energy bought to fill the
battery is paid for today but earns its keep when the battery gives it back, so the change
in stored energy is valued and added. Battery wear is a cost of the saving, so it is taken off.

With solar and no battery there is no stored energy, with a battery and no solar there is no
solar use. The same sum covers both. Without a house load reading nothing can be compared, so
the call is refused.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .billing import BillBreakdown, money
from .config import TariffConfig
from .reprice import BillPeriod, Rounding, import_rates, reprice
from .slots import SlotDay


@dataclass(frozen=True)
class Battery:
    """What the battery costs and holds. Leave it out for a house with no battery."""

    capacity_kwh: float
    soc_before_pct: float | None = None  # charge when the first day began, None if unknown
    wear_per_kwh: float = 0.0  # cost of each kWh discharged


@dataclass(frozen=True)
class Savings:
    """The saving over the days, with the two bills it is the difference of."""

    without_system: BillBreakdown  # the whole house load bought from the grid
    actual: BillBreakdown
    bill_difference: float  # without_system.total less actual.total
    stored_energy_value: float  # value of the change in stored energy, negative for a fall
    battery_wear: float
    total: float  # bill_difference + stored_energy_value - battery_wear
    coverage: float  # share of the days' time that was observed, 0 to 1


def savings(
    days: Sequence[SlotDay],
    tariff: TariffConfig,
    period: BillPeriod,
    battery: Battery | None = None,
) -> Savings:
    """The saving over *days*, the days of one bill or any part of it, in any order.

    Raises ValueError when the days hold no house load.
    """
    if not any(day.total("house") for day in days):
        raise ValueError("no house load was recorded, so there is nothing to compare")
    actual = reprice(days, tariff, period, Rounding.TOTAL)
    baseline = reprice([_all_from_grid(day) for day in days], tariff, period, Rounding.TOTAL)
    difference = money(baseline.bill.total - actual.bill.total)
    stored = _stored_value(days, tariff, battery)
    wear = money(sum(day.total("battery_discharge") for day in days) * _wear(battery))
    return Savings(
        baseline.bill,
        actual.bill,
        difference,
        stored,
        wear,
        money(difference + stored - wear),
        actual.coverage,
    )


def _wear(battery: Battery | None) -> float:
    return battery.wear_per_kwh if battery else 0.0


def _all_from_grid(day: SlotDay) -> SlotDay:
    """The day as it would have been with no solar and no battery."""
    return SlotDay(
        day.day,
        day.tz,
        flows={"import": list(day.loads["house"])},
        loads=dict(day.loads),
        seconds=list(day.seconds),
    )


def _stored_value(days: Sequence[SlotDay], tariff: TariffConfig, battery: Battery | None) -> float:
    if battery is None or battery.capacity_kwh <= 0 or battery.soc_before_pct is None:
        return 0.0
    ordered = sorted(days, key=lambda d: d.day)
    closing = next(
        (v for day in reversed(ordered) for v in reversed(day.soc_pct) if v is not None), None
    )
    if closing is None:
        return 0.0
    change_kwh = (closing - battery.soc_before_pct) / 100 * battery.capacity_kwh
    return money(change_kwh * _stored_rate(days, tariff))


def _stored_rate(days: Sequence[SlotDay], tariff: TariffConfig) -> float:
    """Average cost of the grid energy that went into the battery, else the cheapest rate."""
    kwh = cost = 0.0
    for day in days:
        charges = day.flows["grid_to_battery"]
        for charged, rate in zip(charges, import_rates(day, tariff), strict=True):
            kwh += charged
            cost += charged * tariff.effective_import_rate(rate)
    if kwh > 0:
        return cost / kwh
    return tariff.effective_import_rate(tariff.get_cheapest_rate().rate)
