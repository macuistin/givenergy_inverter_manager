"""reprice.py: price the half-hourly history under a tariff, and build the bill from it.

The history (slots.py) holds energy, never a price, so any tariff can be applied to any days.
Each slot's import is priced at the rate in force when the slot starts, so a rate window that
starts or ends inside a half hour is priced as if it began at the slot start. The usual windows
begin on the hour or half hour and are priced exactly.

A supplier bill takes the meter's kWh for each rate band, prices each band and rounds each line
to the cent. Pricing slot by slot and rounding once is a cent or two out for the same energy.
Rounding.PER_BAND does what the bill does. Rounding.TOTAL is the figure the cost sensors add up.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from ..timeutil import shift_real
from .billing import BillBreakdown, money
from .config import TariffConfig
from .defaults import SLOT_SECONDS
from .periods import RatePeriod
from .slots import SlotDay


class Rounding(Enum):
    """How the energy lines are rounded before the rest of the bill is worked out."""

    TOTAL = "total"  # add the band costs, round once
    PER_BAND = "per_band"  # round each band's cost to the cent first, as a supplier bill does


@dataclass(frozen=True)
class BillPeriod:
    """The length of the bill: the days it covers and the days of the whole period.

    *period_days* sets the share of the monthly levy charged. None means an average month.
    """

    days: int
    period_days: int | None = None


@dataclass(frozen=True)
class Repriced:
    """Slots priced under one tariff."""

    import_kwh_by_band: dict[str, float]  # kWh imported in each rate band, in first-seen order
    export_kwh: float
    energy_cost: float  # the bands' cost before the discount and VAT
    export_credit: float
    bill: BillBreakdown
    coverage: float  # share of the days' time that was observed, 0 to 1


def import_by_band(days: Sequence[SlotDay], tariff: TariffConfig) -> dict[str, float]:
    """kWh imported in each rate band, the band taken from each slot's start."""
    bands: dict[str, float] = {}
    for day in days:
        for index, kwh in enumerate(day.flows["import"]):
            if kwh:
                band = _band_at(day, index, tariff).name
                bands[band] = bands.get(band, 0.0) + kwh
    return bands


def import_rates(day: SlotDay, tariff: TariffConfig) -> list[float]:
    """The import rate in force at the start of each slot, before the discount and VAT."""
    rates = _band_rates(tariff)
    return [rates[_band_at(day, index, tariff).name] for index in range(day.slot_count)]


def reprice(
    days: Sequence[SlotDay],
    tariff: TariffConfig,
    period: BillPeriod,
    rounding: Rounding = Rounding.TOTAL,
) -> Repriced:
    """The bill for *days* under *tariff*. The days are the bill period, in any order."""
    bands = import_by_band(days, tariff)
    rates = _band_rates(tariff)
    costs = [kwh * rates[name] for name, kwh in bands.items()]
    if rounding is Rounding.PER_BAND:
        costs = [money(c) for c in costs]
    energy_cost = sum(costs)
    export_kwh = sum(day.total("export") for day in days)
    export_credit = tariff.calculate_export_earnings(export_kwh)
    bill = tariff.calculate_bill(energy_cost, period.days, period.period_days, export_credit)
    return Repriced(bands, export_kwh, energy_cost, export_credit, bill, _coverage(days))


def _band_at(day: SlotDay, index: int, tariff: TariffConfig) -> RatePeriod:
    start = shift_real(day.start, timedelta(seconds=index * SLOT_SECONDS))
    return tariff.get_current_rate(start.astimezone(day.tz))


def _band_rates(tariff: TariffConfig) -> dict[str, float]:
    rates = {period.name: period.rate for period in tariff.rate_periods}
    rates[tariff.base_rate_name] = tariff.base_rate
    return rates


def _coverage(days: Sequence[SlotDay]) -> float:
    return sum(day.coverage for day in days) / len(days) if days else 0.0
