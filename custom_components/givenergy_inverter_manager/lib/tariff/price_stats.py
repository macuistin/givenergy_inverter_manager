"""price_stats.py: the lowest, highest and average price over a time range, and a rating.

The statistics read a price series from `price_curve`, so every tax and discount is already in.
The average is weighted by time, because slots can be of any length. A range the series does not
cover in full still gets statistics from the part it does cover, and says so in `complete`.

The rating places a price inside the range's own lowest to highest span, in five equal steps.
That makes it comparable across tariffs and countries: it says how a price compares with the
rest of the day, not whether it is cheap in money. A range with one price has no span, so every
price in it rates as normal.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from .price_curve import PriceSlot

RATINGS = ("very_low", "low", "normal", "high", "very_high")
type Rating = Literal["very_low", "low", "normal", "high", "very_high"]


@dataclass(frozen=True)
class PriceStats:
    """The prices over a range, per kWh."""

    lowest: Decimal
    highest: Decimal
    average: Decimal  # weighted by the time each price is in force
    complete: bool  # False when the series does not cover the whole range


def price_stats(
    slots: Sequence[PriceSlot],
    start: datetime,
    end: datetime,
    flow: Literal["import", "export"] = "import",
) -> PriceStats | None:
    """The statistics of *flow* prices from *start* to *end*, or None when none are held."""
    if end <= start:
        raise ValueError("end must be after start")
    prices: list[tuple[Decimal, Decimal]] = []  # (price, seconds in force)
    for slot in slots:
        seconds = (min(slot.end, end) - max(slot.start, start)).total_seconds()
        if seconds > 0:
            price = slot.import_price if flow == "import" else slot.export_price
            prices.append((price, Decimal(str(seconds))))
    if not prices:
        return None
    covered = sum((seconds for _, seconds in prices), Decimal(0))
    weighted = sum((price * seconds for price, seconds in prices), Decimal(0))
    return PriceStats(
        lowest=min(price for price, _ in prices),
        highest=max(price for price, _ in prices),
        average=weighted / covered,
        complete=covered == Decimal(str((end - start).total_seconds())),
    )


def price_rating(price: Decimal, stats: PriceStats) -> Rating:
    """Where *price* sits between the lowest and highest price of *stats*, in five steps."""
    span = stats.highest - stats.lowest
    if span <= 0:
        return "normal"
    position = (price - stats.lowest) / span
    step = min(int(position * len(RATINGS)), len(RATINGS) - 1)
    return RATINGS[max(step, 0)]  # type: ignore[return-value]
