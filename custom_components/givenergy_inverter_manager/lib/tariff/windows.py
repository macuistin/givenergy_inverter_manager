"""windows.py: the cheapest or dearest stretch of a given length in a price series.

The prices are constant inside a slot, so the best window always starts either where a slot starts
or ends exactly when a slot ends. Trying only those starts finds the exact best for any duration
and any slot length, with no rounding to a slot. A window costs the load's power, times the time
spent in each slot, times that slot's all-in price from `price_curve`.

A window is only offered where the series has a price for every moment of it. When the series ends
before the latest end asked for, the result says so and does not guess the rest.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from .price_curve import PriceSlot

_HOUR = Decimal(3600)


@dataclass(frozen=True)
class WindowSearch:
    """What to look for. Times are aware. A range left out is the whole series."""

    duration: timedelta
    flow: Literal["import", "export"] = "import"
    highest: bool = False  # the dearest window, not the cheapest
    latest: bool = False  # on a tie, the latest start, not the earliest
    power_kw: Decimal = Decimal(1)
    earliest_start: datetime | None = None
    latest_end: datetime | None = None  # a "finish by" time


@dataclass(frozen=True)
class Window:
    """The window found, and what it costs against starting as early as allowed."""

    start: datetime
    end: datetime
    cost: Decimal  # the load's cost over the window, in the currency of the prices
    average_price: Decimal  # per kWh
    reference_cost: Decimal | None  # the same load starting at the earliest start
    complete: bool  # False when the series ends before the latest end asked for

    @property
    def saving(self) -> Decimal | None:
        """The reference cost less this cost. Negative when a dearest window was asked for."""
        return None if self.reference_cost is None else self.reference_cost - self.cost


def find_window(slots: Sequence[PriceSlot], search: WindowSearch) -> Window | None:
    """The best window under *search*, or None when no window fits inside the priced time."""
    if search.duration <= timedelta(0) or search.power_kw <= 0:
        raise ValueError("duration and power must be above zero")
    if not slots:
        return None
    first, last = _range(slots, search)
    costs = {
        start: cost
        for start in _starts(slots, search.duration, first, last)
        if (cost := _cost(slots, search, start)) is not None
    }
    if not costs:
        return None
    best = min(costs, key=lambda start: _rank(search, start, costs[start]))
    hours = Decimal(search.duration.total_seconds()) / _HOUR
    return Window(
        start=best,
        end=best + search.duration,
        cost=costs[best],
        average_price=costs[best] / (hours * search.power_kw),
        reference_cost=_cost(slots, search, first),
        complete=search.latest_end is None or search.latest_end <= slots[-1].end,
    )


def _rank(search: WindowSearch, start: datetime, cost: Decimal) -> tuple[Decimal, float]:
    """Smaller is better: cost (negated for the dearest), then start (negated for the latest)."""
    when = start.timestamp()
    return (-cost if search.highest else cost, -when if search.latest else when)


def _range(slots: Sequence[PriceSlot], search: WindowSearch) -> tuple[datetime, datetime]:
    """The part of the priced time the search may use."""
    first, last = slots[0].start, slots[-1].end
    if search.earliest_start is not None:
        first = max(first, search.earliest_start)
    if search.latest_end is not None:
        last = min(last, search.latest_end)
    return first, last


def _starts(
    slots: Sequence[PriceSlot], duration: timedelta, first: datetime, last: datetime
) -> list[datetime]:
    edges = {first, last - duration}
    for slot in slots:
        edges.update((slot.start, slot.end - duration))
    return sorted(s for s in edges if s >= first and s + duration <= last)


def _cost(slots: Sequence[PriceSlot], search: WindowSearch, start: datetime) -> Decimal | None:
    end = start + search.duration
    seconds = Decimal(0)
    total = Decimal(0)
    for slot in slots:
        overlap = min(slot.end, end).timestamp() - max(slot.start, start).timestamp()
        if overlap <= 0:
            continue
        price = slot.import_price if search.flow == "import" else slot.export_price
        seconds += Decimal(overlap)
        total += price * Decimal(overlap)
    if seconds != Decimal(search.duration.total_seconds()):
        return None
    return total * search.power_kw / _HOUR
