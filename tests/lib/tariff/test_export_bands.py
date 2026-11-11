"""An export price that changes with the time of day: the document, the slots and the credit."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import (
    BillInputs,
    CheckFailed,
    DefinitionError,
    SlotDay,
    SlotEnergy,
    SlotHistory,
    export_band_at,
    export_by_band,
    parse_definition,
    price_bill,
    price_period,
    verify_checks,
)
from custom_components.givenergy_inverter_manager.lib.timeutil import shift_real
from tests.lib.tariff.example_definition import example_document

D = Decimal
DUBLIN = ZoneInfo("Europe/Dublin")
PEAK = {"name": "Peak export", "priority": 1, "price": "0.30", "hours": "16:00-19:00"}
IMPORT = {"Boost": D(257), "Day": D(67), "Night": D(619)}


def banded(**zone_changes: Any) -> dict[str, Any]:
    doc = example_document()
    doc["export"]["zones"] = [PEAK | zone_changes]
    return doc


def at(day: str, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=DUBLIN)


def day_exporting(day: date, kwh_per_slot: float) -> SlotDay:
    slots = SlotDay(day, DUBLIN)
    for index in range(slots.slot_count):
        begin = shift_real(slots.start, timedelta(minutes=30 * index))
        slots.add(SlotEnergy({"export": kwh_per_slot}), begin, shift_real(begin, timedelta(minutes=30)))
    return slots


def test_a_document_with_no_export_zones_reads_as_before() -> None:
    d = parse_definition(example_document())
    assert d.export_prices.zones == ()
    assert export_band_at(d, at("2026-10-05", "17:00")) == "Export"


def test_export_zones_are_read_like_import_zones() -> None:
    d = parse_definition(banded())
    (zone,) = d.export_prices.zones
    assert (zone.name, zone.price, zone.start.hour, zone.end.hour) == ("Peak export", D("0.30"), 16, 19)
    assert export_band_at(d, at("2026-10-05", "17:00")) == "Peak export"
    assert export_band_at(d, at("2026-10-05", "19:00")) == "Export"  # the end is excluded


def test_export_zone_follows_days() -> None:
    d = parse_definition(banded(days=["mon"]))
    assert export_band_at(d, at("2026-10-05", "17:00")) == "Peak export"  # a Monday
    assert export_band_at(d, at("2026-10-06", "17:00")) == "Export"


@pytest.mark.parametrize(
    ("zones", "where", "text"),
    [
        ([PEAK, PEAK | {"priority": 2}], "export.zones", "own name"),
        ([PEAK, PEAK | {"name": "Other"}], "export.zones", "own priority"),
        ([PEAK | {"name": "Export"}], "export.zones", "like the base"),
        ([PEAK | {"hours": "16-19"}], "export.zones[0].hours", "HH:MM-HH:MM"),
        ([PEAK | {"price": "-0.1"}], "export.zones[0].price", "0 or more"),
    ],
)
def test_export_zone_refusals(zones: list[dict[str, Any]], where: str, text: str) -> None:
    doc = example_document()
    doc["export"]["zones"] = zones
    with pytest.raises(DefinitionError) as raised:
        parse_definition(doc)
    assert raised.value.path == where and text in str(raised.value)


def test_export_by_band_credits_each_band_at_its_price() -> None:
    d = parse_definition(banded())
    bill = price_bill(d, BillInputs(30, 30, IMPORT, {"Export": D(40), "Peak export": D(7)}))
    credit = bill.root.children["credit"]
    assert credit.amount == D("-9.90")  # 40 x 0.195 + 7 x 0.30
    assert credit.children["Export"].amount == D("-7.800")
    assert credit.children["Peak export"].amount == D("-2.10")
    assert bill.total == D("196.52") - D("9.90")


def test_one_export_figure_is_paid_at_the_base_price() -> None:
    d = parse_definition(banded())
    bill = price_bill(d, BillInputs(30, 30, IMPORT, D(47)))
    assert bill.root.children["credit"].amount == D("-9.17")


def test_a_flat_export_line_has_no_band_lines() -> None:
    bill = price_bill(parse_definition(example_document()), BillInputs(30, 30, IMPORT, D(47)))
    assert bill.root.children["credit"].children == {}


def test_a_check_can_give_export_by_band() -> None:
    doc = banded()
    doc["checks"]["october-2026"].update(
        export_kwh={"Export": "40", "Peak export": "7"}, expected_total="186.62"
    )
    d = parse_definition(doc)
    assert d.checks["october-2026"].export_kwh == {"Export": D(40), "Peak export": D(7)}
    verify_checks(d)
    doc["checks"]["october-2026"]["expected_total"] = "187.35"
    with pytest.raises(CheckFailed):
        verify_checks(parse_definition(doc))


def test_a_check_naming_an_unknown_export_band_is_refused() -> None:
    doc = banded()
    doc["checks"]["october-2026"]["export_kwh"] = {"Evening": "1"}
    with pytest.raises(DefinitionError, match="not an export band") as raised:
        parse_definition(doc)
    assert raised.value.path == "checks.october-2026.export_kwh.Evening"


def test_slots_are_split_into_export_bands() -> None:
    d = parse_definition(banded())
    totals = export_by_band([day_exporting(date(2026, 10, 5), 0.5)], d)
    assert totals == {"Export": D("21.0"), "Peak export": D("3.0")}  # 6 of 48 slots are 16:00 to 19:00


def test_a_period_is_credited_by_export_band() -> None:
    history = SlotHistory(DUBLIN)
    history._days = {date(2026, 10, 5): day_exporting(date(2026, 10, 5), 0.5)}
    flat = price_period(history, parse_definition(example_document()), date(2026, 10, 5))
    peak = price_period(history, parse_definition(banded()), date(2026, 10, 5))
    assert flat.priced.root.children["credit"].amount == D("-4.68")  # 24 x 0.195
    assert peak.priced.root.children["credit"].amount == D("-5.00")  # 21 x 0.195 + 3 x 0.30, 4.995
