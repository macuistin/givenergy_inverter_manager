# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The cheapest or dearest window of a given length in a price series."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import PriceSlot, WindowSearch, find_window, parse_definition, price_curve
from tests.lib.tariff.example_definition import example_document

D = Decimal
DUBLIN = ZoneInfo("Europe/Dublin")
MIDNIGHT = datetime(2026, 6, 1, 0, 0, tzinfo=DUBLIN)


def _slots(*prices: str, minutes: int = 30, export: str = "0.10") -> list[PriceSlot]:
    """Slots of the same length, one per price, from midnight."""
    step = timedelta(minutes=minutes)
    return [
        PriceSlot(
            MIDNIGHT + step * index, MIDNIGHT + step * (index + 1), "b", "x", D(price), D(export)
        )
        for index, price in enumerate(prices)
    ]


def _at(minutes: int) -> datetime:
    return MIDNIGHT + timedelta(minutes=minutes)


def test_the_cheapest_window_is_the_run_with_the_lowest_total() -> None:
    slots = _slots("0.30", "0.10", "0.10", "0.30", "0.05", "0.30")
    found = find_window(slots, WindowSearch(timedelta(hours=1)))
    assert found is not None
    assert (found.start, found.end) == (_at(30), _at(90))
    assert found.cost == D("0.10")
    assert found.average_price == D("0.10")


def test_the_dearest_window_can_be_asked_for() -> None:
    slots = _slots("0.30", "0.10", "0.10", "0.30", "0.40", "0.05")
    found = find_window(slots, WindowSearch(timedelta(hours=1), highest=True))
    assert found is not None and found.start == _at(90)


def test_a_duration_that_is_not_a_whole_number_of_slots_is_exact() -> None:
    # The cheap slot is 30 minutes. A 45 minute window starts at its start or ends at its end.
    slots = _slots("0.30", "0.10", "0.30")
    found = find_window(slots, WindowSearch(timedelta(minutes=45)))
    assert found is not None
    assert found.start in (_at(30), _at(15))
    assert found.cost == D("0.10") * D("0.5") + D("0.30") * D("0.25")


def test_a_window_that_starts_between_slot_edges_is_found() -> None:
    # A 30 minute dip in the middle of long dear slots: only a start on the dip's edge is best.
    slots = _slots("0.40", "0.40", "0.10", "0.40", "0.40")
    found = find_window(slots, WindowSearch(timedelta(minutes=30)))
    assert found is not None and found.start == _at(60)


def test_power_scales_the_cost_and_not_the_price() -> None:
    slots = _slots("0.20", "0.20")
    found = find_window(slots, WindowSearch(timedelta(hours=1), power_kw=D("3")))
    assert found is not None
    assert found.cost == D("0.60")
    assert found.average_price == D("0.20")


def test_ties_go_to_the_earliest_start_or_the_latest() -> None:
    slots = _slots("0.10", "0.10", "0.10")
    early = find_window(slots, WindowSearch(timedelta(minutes=30)))
    late = find_window(slots, WindowSearch(timedelta(minutes=30), latest=True))
    assert early is not None and early.start == _at(0)
    assert late is not None and late.start == _at(60)


def test_a_finish_by_time_limits_the_search() -> None:
    slots = _slots("0.30", "0.20", "0.30", "0.01")
    found = find_window(slots, WindowSearch(timedelta(minutes=30), latest_end=_at(90)))
    assert found is not None and found.start == _at(30) and found.complete


def test_an_earliest_start_limits_the_search() -> None:
    slots = _slots("0.01", "0.30", "0.20")
    found = find_window(slots, WindowSearch(timedelta(minutes=30), earliest_start=_at(30)))
    assert found is not None and found.start == _at(60)


def test_the_saving_is_against_starting_as_early_as_allowed() -> None:
    slots = _slots("0.40", "0.10")
    found = find_window(slots, WindowSearch(timedelta(minutes=30)))
    assert found is not None
    assert found.reference_cost == D("0.20")
    assert found.saving == D("0.15")  # 0.20 for a 30 minute load at 0.40, less 0.05 at 0.10


def test_a_finish_by_time_after_the_prices_end_is_reported() -> None:
    slots = _slots("0.30", "0.10")
    found = find_window(slots, WindowSearch(timedelta(minutes=30), latest_end=_at(300)))
    assert found is not None and found.start == _at(30) and not found.complete


def test_export_windows_use_the_export_price() -> None:
    slots = [
        PriceSlot(_at(0), _at(30), "b", "x", D("0.10"), D("0.05")),
        PriceSlot(_at(30), _at(60), "b", "x", D("0.50"), D("0.20")),
    ]
    found = find_window(slots, WindowSearch(timedelta(minutes=30), flow="export", highest=True))
    assert found is not None and found.start == _at(30) and found.cost == D("0.10")


def test_no_window_fits_when_the_prices_are_shorter_than_the_duration() -> None:
    assert find_window(_slots("0.10"), WindowSearch(timedelta(hours=1))) is None
    assert find_window([], WindowSearch(timedelta(hours=1))) is None


def test_a_gap_in_the_prices_is_not_priced_over() -> None:
    slots = _slots("0.10", "0.10", "0.10", "0.10")
    gapped = [slots[0], slots[1], slots[3]]
    found = find_window(gapped, WindowSearch(timedelta(hours=1)))
    assert found is not None and found.start == _at(0)
    assert find_window(gapped[1:], WindowSearch(timedelta(hours=1))) is None


def test_a_duration_or_power_of_zero_is_refused() -> None:
    with pytest.raises(ValueError, match="above zero"):
        find_window(_slots("0.1"), WindowSearch(timedelta(0)))
    with pytest.raises(ValueError, match="above zero"):
        find_window(_slots("0.1"), WindowSearch(timedelta(hours=1), power_kw=D(0)))


def test_a_window_over_the_clocks_going_back_costs_real_elapsed_time() -> None:
    definition = parse_definition(example_document())
    start = datetime(2026, 10, 25, 0, 0, tzinfo=DUBLIN)
    curve = price_curve(definition, start, start + timedelta(hours=25))
    prices = {slot.import_band: slot.import_price for slot in curve}
    found = find_window(curve, WindowSearch(timedelta(hours=4)))
    assert found is not None
    assert found.end.timestamp() - found.start.timestamp() == 4 * 3600
    # The two boost hours and two night hours beside them, whatever the clock says.
    assert found.cost == 2 * prices["Boost"] + 2 * prices["Night"]
