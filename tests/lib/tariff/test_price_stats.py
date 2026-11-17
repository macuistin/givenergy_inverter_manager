# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The lowest, highest and average price of a range, and the rating of a price."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import PriceSlot, price_rating, price_stats
from custom_components.givenergy_inverter_manager.lib.tariff.price_stats import RATINGS, PriceStats

D = Decimal
MIDNIGHT = datetime(2026, 6, 1, 0, 0, tzinfo=ZoneInfo("Europe/Dublin"))


def _slot(minutes_from: int, minutes_to: int, price: str, export: str = "0.05") -> PriceSlot:
    return PriceSlot(
        MIDNIGHT + timedelta(minutes=minutes_from),
        MIDNIGHT + timedelta(minutes=minutes_to),
        "b", "x", D(price), D(export),
    )


DAY = (MIDNIGHT, MIDNIGHT + timedelta(days=1))


def test_the_average_is_weighted_by_time() -> None:
    slots = [_slot(0, 360, "0.10"), _slot(360, 1440, "0.30")]
    stats = price_stats(slots, *DAY)
    assert stats == PriceStats(D("0.10"), D("0.30"), D("0.25"), True)


def test_export_prices_can_be_asked_for() -> None:
    slots = [_slot(0, 720, "0.10", "0.02"), _slot(720, 1440, "0.30", "0.06")]
    stats = price_stats(slots, *DAY, flow="export")
    assert stats is not None and (stats.lowest, stats.highest) == (D("0.02"), D("0.06"))


def test_slots_are_cut_at_the_range() -> None:
    slots = [_slot(0, 600, "0.10"), _slot(600, 1440, "0.90")]
    stats = price_stats(slots, MIDNIGHT, MIDNIGHT + timedelta(hours=12))
    assert stats is not None and stats.highest == D("0.90") and stats.complete


def test_a_range_the_prices_do_not_cover_is_marked_incomplete() -> None:
    stats = price_stats([_slot(0, 720, "0.10")], *DAY)
    assert stats is not None and stats.complete is False and stats.average == D("0.10")


def test_a_range_with_no_prices_has_no_statistics() -> None:
    assert price_stats([_slot(0, 60, "0.10")], MIDNIGHT + timedelta(days=2),
                       MIDNIGHT + timedelta(days=3)) is None
    assert price_stats([], *DAY) is None


def test_an_empty_range_is_refused() -> None:
    with pytest.raises(ValueError, match="after start"):
        price_stats([], MIDNIGHT, MIDNIGHT)


@pytest.mark.parametrize(
    ("price", "rating"),
    [("0.10", "very_low"), ("0.1799", "very_low"), ("0.18", "low"), ("0.20", "low"), ("0.30", "normal"),
     ("0.40", "high"), ("0.50", "very_high"), ("0.60", "very_high"), ("0.05", "very_low")],
)
def test_a_price_is_rated_by_its_place_in_the_range(price: str, rating: str) -> None:
    stats = PriceStats(D("0.10"), D("0.50"), D("0.30"), True)
    assert price_rating(D(price), stats) == rating


def test_a_single_price_rates_as_normal() -> None:
    stats = PriceStats(D("0.20"), D("0.20"), D("0.20"), True)
    assert price_rating(D("0.20"), stats) == "normal"


def test_there_are_five_ratings_from_low_to_high() -> None:
    assert RATINGS == ("very_low", "low", "normal", "high", "very_high")
