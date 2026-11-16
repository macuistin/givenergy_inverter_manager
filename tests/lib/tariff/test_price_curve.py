# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The price of one more kWh in each band, and the price series over a time range."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import (
    BillInputs,
    marginal_prices,
    parse_definition,
    price_bill,
    price_curve,
)
from tests.lib.tariff.example_definition import example_document

D = Decimal
DUBLIN = ZoneInfo("Europe/Dublin")
# The example document takes 5.5% off the energy and adds 9% VAT, so a price is x 0.945 x 1.09.
FACTOR = D("0.945") * D("1.09")


def _elapsed(curve) -> timedelta:  # type: ignore[no-untyped-def]
    """Real elapsed time: a subtraction of two times in one zone ignores the clock change."""
    return timedelta(seconds=sum(slot.end.timestamp() - slot.start.timestamp() for slot in curve))


def _definition(**export):  # type: ignore[no-untyped-def]
    doc = example_document()
    if export:
        doc["export"]["zones"] = [export]
    return parse_definition(doc)


def test_an_import_price_has_the_discount_and_vat_in_it() -> None:
    prices = marginal_prices(_definition()).import_prices
    assert prices["Day"] == pytest.approx(D("0.365") * FACTOR, abs=D("0.000001"))
    assert prices["Night"] == pytest.approx(D("0.18") * FACTOR, abs=D("0.000001"))
    assert prices["Boost"] == pytest.approx(D("0.1056") * FACTOR, abs=D("0.000001"))


def test_an_export_price_is_what_the_bill_credits_for_a_kwh() -> None:
    definition = _definition()
    price = marginal_prices(definition).export_prices["Export"]
    without = price_bill(definition, BillInputs(30, 30, {}, D(0))).total
    with_ten = price_bill(definition, BillInputs(30, 30, {}, D(10))).total
    assert price > 0
    assert without - with_ten == pytest.approx(price * 10, abs=D("0.01"))


def test_a_band_of_an_export_zone_has_its_own_price() -> None:
    zone = {"name": "Peak export", "priority": 1, "price": "0.30", "hours": "16:00-19:00"}
    prices = marginal_prices(_definition(**zone)).export_prices
    assert prices["Peak export"] > prices["Export"] > 0


def test_a_fixed_band_tariff_is_a_few_long_slots() -> None:
    start = datetime(2026, 6, 1, 0, 0, tzinfo=DUBLIN)
    curve = price_curve(_definition(), start, start + timedelta(days=1))
    assert [slot.import_band for slot in curve] == ["Night", "Boost", "Night", "Day", "Night"]
    assert curve[0].start == start and curve[-1].end == start + timedelta(days=1)
    for before, after in zip(curve, curve[1:]):
        assert before.end == after.start


def test_the_first_and_last_slot_are_cut_to_the_range() -> None:
    start = datetime(2026, 6, 1, 8, 10, tzinfo=DUBLIN)
    end = datetime(2026, 6, 1, 8, 50, tzinfo=DUBLIN)
    curve = price_curve(_definition(), start, end)
    assert (curve[0].start, curve[-1].end) == (start, end)
    assert {slot.import_band for slot in curve} == {"Day"}


def test_the_day_the_clocks_go_back_has_twenty_five_hours() -> None:
    start = datetime(2026, 10, 25, 0, 0, tzinfo=DUBLIN)
    end = datetime(2026, 10, 26, 0, 0, tzinfo=DUBLIN)
    curve = price_curve(_definition(), start, end)
    assert _elapsed(curve) == timedelta(hours=25)
    boost = [slot for slot in curve if slot.import_band == "Boost"]
    assert [slot.start.astimezone(DUBLIN).hour for slot in boost] == [2]


def test_the_day_the_clocks_go_forward_has_twenty_three_hours() -> None:
    start = datetime(2026, 3, 29, 0, 0, tzinfo=DUBLIN)
    end = datetime(2026, 3, 30, 0, 0, tzinfo=DUBLIN)
    curve = price_curve(_definition(), start, end)
    assert _elapsed(curve) == timedelta(hours=23)


def test_the_range_is_read_in_any_time_zone() -> None:
    utc = datetime(2026, 6, 1, 1, 0, tzinfo=timezone.utc)  # 02:00 in Dublin in June
    curve = price_curve(_definition(), utc, utc + timedelta(minutes=30))
    assert curve[0].import_band == "Boost"


def test_a_range_needs_a_time_zone_and_a_length() -> None:
    naive = datetime(2026, 6, 1)
    aware = datetime(2026, 6, 1, tzinfo=DUBLIN)
    with pytest.raises(ValueError, match="time zone"):
        price_curve(_definition(), naive, aware)
    with pytest.raises(ValueError, match="after"):
        price_curve(_definition(), aware, aware)
