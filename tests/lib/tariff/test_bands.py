"""Slots matched to the bands of a definition, and checked against the existing tariff model."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from custom_components.givenergy_inverter_manager.lib.tariff import (
    BillInputs,
    SlotDay,
    SlotEnergy,
    parse_definition,
    price_bill,
)
from custom_components.givenergy_inverter_manager.lib.tariff.bands import (
    band_at,
    import_by_band,
)
from custom_components.givenergy_inverter_manager.lib.tariff.reprice import (
    import_by_band as old_import_by_band,
)
from custom_components.givenergy_inverter_manager.lib.timeutil import shift_real
from tests.lib.tariff.example_definition import example_document
from tests.lib.tariff.test_reprice import _tariff

DUBLIN = ZoneInfo("Europe/Dublin")


def at(day: str, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=DUBLIN)


def definition(**zone_changes: Any) -> Any:
    doc = example_document()
    doc["import"]["zones"][0].update(zone_changes)
    return parse_definition(doc)


def test_highest_priority_wins_and_base_is_the_rest() -> None:
    d = parse_definition(example_document())
    assert band_at(d, at("2026-10-05", "03:00")) == "Boost"  # inside Night too, higher priority
    assert band_at(d, at("2026-10-05", "05:00")) == "Night"
    assert band_at(d, at("2026-10-05", "12:00")) == "Day"
    assert band_at(d, at("2026-10-05", "08:00")) == "Day"  # the end of a zone is excluded
    assert band_at(d, at("2026-10-05", "23:00")) == "Night"  # the start is included


def test_moment_in_another_zone_is_read_on_the_definition_clock() -> None:
    d = parse_definition(example_document())
    utc = datetime.fromisoformat("2026-07-05T01:30:00+00:00")  # 02:30 in Dublin in summer
    assert band_at(d, utc) == "Boost"


def test_zone_past_midnight_belongs_to_the_day_it_began() -> None:
    d = definition(days=["fri"])  # Night, Friday only
    assert band_at(d, at("2026-10-02", "23:30")) == "Night"  # Friday evening
    assert band_at(d, at("2026-10-03", "01:00")) == "Night"  # still Friday's zone
    assert band_at(d, at("2026-10-03", "23:30")) == "Day"  # Saturday evening
    assert band_at(d, at("2026-10-02", "01:00")) == "Day"  # Thursday's, which has no Night


def test_months_limit_a_zone() -> None:
    d = definition(months=[12, 1])
    assert band_at(d, at("2026-12-05", "05:00")) == "Night"
    assert band_at(d, at("2026-10-05", "05:00")) == "Day"


def test_holiday_counts_as_weekend_only_for_weekend_zones() -> None:
    holiday = date(2026, 10, 26)  # a Monday

    def is_holiday(day: date) -> bool:
        return day == holiday

    weekend = definition(days=["sat", "sun"], holidays="weekend")
    assert band_at(weekend, at("2026-10-26", "12:00"), is_holiday) == "Day"
    weekend_night = definition(days=["sat", "sun"], holidays="weekend", hours="00:00-23:59")
    assert band_at(weekend_night, at("2026-10-26", "12:00"), is_holiday) == "Night"
    assert band_at(weekend_night, at("2026-10-26", "12:00")) == "Day"  # not a holiday
    weekdays = definition(days=["mon", "tue"], holidays="weekend", hours="00:00-23:59")
    assert band_at(weekdays, at("2026-10-26", "12:00"), is_holiday) == "Day"
    assert band_at(weekdays, at("2026-10-26", "12:00")) == "Night"
    normal = definition(days=["mon"], hours="00:00-23:59")
    assert band_at(normal, at("2026-10-26", "12:00"), is_holiday) == "Night"


def history() -> list[SlotDay]:
    days = []
    for offset in range(3):
        day = SlotDay(date(2026, 10, 25) + timedelta(days=offset), DUBLIN)  # the clock change
        for index in range(day.slot_count):
            begin = shift_real(day.start, timedelta(minutes=30 * index))
            end = shift_real(begin, timedelta(minutes=30))
            day.add(SlotEnergy({"import": 0.1 + 0.01 * index}), begin, end)
        days.append(day)
    return days


def test_bands_match_the_existing_tariff_model_across_a_clock_change() -> None:
    days = history()
    assert days[0].slot_count == 50  # 25 October 2026 is the clock change
    new = import_by_band(days, parse_definition(example_document()))
    old = old_import_by_band(days, _tariff())
    assert set(new) == set(old)
    for band, kwh in old.items():
        assert abs(float(new[band]) - kwh) < 1e-5


def test_bands_price_the_bill() -> None:
    d = parse_definition(example_document())
    days = history()
    totals = import_by_band(days, d)
    bill = price_bill(d, BillInputs(3, 30, totals, Decimal(0)))
    assert bill.total > 0
