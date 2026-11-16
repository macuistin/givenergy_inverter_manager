"""price_curve.py: what one more kWh costs in each band, and the price series over a time range.

The price of a band is not read from the document. It is the bill engine's own answer: the bill
with a large extra amount in that band, less the bill without it, divided by that amount. So a
levy, a discount, VAT before or after the discount, and any later charge shape the engine learns
are in the price without a second copy of the rules here. A charge that does not depend on the
energy (a standing charge, a monthly levy) cancels out.

The series is cut at the engine's slot length. A slot takes the band in force at its start, on the
clock of the definition's time zone, as `bands.py` does. Slots are real elapsed time, so a clock
change gives the right number of them. Neighbouring slots with the same band and prices are
joined, so a fixed-band tariff gives a few long slots.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from .bands import band_at, export_band_at, no_holidays
from .defaults import SLOT_SECONDS
from .definition import ExportPrices, ImportPrices, TariffDefinition
from .engine import BillInputs, price_bill

# Large, so the cent rounding of a line moves the price by less than a millionth.
_STEP = Decimal(1_000_000)
_DAYS = 30
_SLOT = timedelta(seconds=SLOT_SECONDS)


@dataclass(frozen=True)
class MarginalPrices:
    """What one more kWh costs, or earns, in each band, with every tax and discount applied."""

    import_prices: Mapping[str, Decimal]
    export_prices: Mapping[str, Decimal]


@dataclass(frozen=True)
class PriceSlot:
    """A stretch of time with one import price and one export price, per kWh."""

    start: datetime
    end: datetime
    import_band: str
    export_band: str
    import_price: Decimal
    export_price: Decimal


def marginal_prices(definition: TariffDefinition) -> MarginalPrices:
    """The price of one more kWh in every import band and every export band."""
    none = _bill(definition, {}, Decimal(0))
    imports = {
        name: (_bill(definition, {name: _STEP}, Decimal(0)) - none) / _STEP
        for name in _band_names(definition.import_prices)
    }
    exports = {
        name: (none - _bill(definition, {}, _export(definition, name))) / _STEP
        for name in _band_names(definition.export_prices)
    }
    return MarginalPrices(imports, exports)


def price_curve(
    definition: TariffDefinition,
    start: datetime,
    end: datetime,
    is_holiday: Callable[[date], bool] = no_holidays,
) -> tuple[PriceSlot, ...]:
    """The prices from *start* to *end* (aware times), joined where they do not change.

    The first slot begins at *start* and the last ends at *end*. Between them slots begin on the
    engine's slot grid, counted from the Unix epoch.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must have a time zone")
    if end <= start:
        raise ValueError("end must be after start")
    marginal = marginal_prices(definition)
    slots: list[PriceSlot] = []
    cursor = start
    while cursor < end:
        following = min(_next_edge(cursor), end)
        bands = (
            band_at(definition, cursor, is_holiday),
            export_band_at(definition, cursor, is_holiday),
        )
        slot = _slot(cursor, following, bands, marginal)
        if slots and _same(slots[-1], slot):
            slot = _joined(slots.pop(), slot)
        slots.append(slot)
        cursor = following
    return tuple(slots)


def _bill(
    definition: TariffDefinition,
    imported: Mapping[str, Decimal],
    exported: Decimal | Mapping[str, Decimal],
) -> Decimal:
    return price_bill(definition, BillInputs(_DAYS, _DAYS, imported, exported)).total


def _export(definition: TariffDefinition, name: str) -> Decimal | Mapping[str, Decimal]:
    return {name: _STEP} if definition.export_prices.zones else _STEP


def _band_names(prices: ImportPrices | ExportPrices) -> list[str]:
    return [prices.base.name, *dict.fromkeys(zone.name for zone in prices.zones)]


def _next_edge(moment: datetime) -> datetime:
    seconds = int(moment.timestamp()) // SLOT_SECONDS * SLOT_SECONDS + SLOT_SECONDS
    return datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(moment.tzinfo)


def _slot(
    start: datetime, end: datetime, bands: tuple[str, str], marginal: MarginalPrices
) -> PriceSlot:
    in_band, out_band = bands
    return PriceSlot(
        start, end, in_band, out_band,
        marginal.import_prices[in_band], marginal.export_prices[out_band],
    )


def _same(left: PriceSlot, right: PriceSlot) -> bool:
    return (left.end == right.start and left.import_band == right.import_band
            and left.export_band == right.export_band)


def _joined(left: PriceSlot, right: PriceSlot) -> PriceSlot:
    return PriceSlot(left.start, right.end, left.import_band, left.export_band,
                     left.import_price, left.export_price)
