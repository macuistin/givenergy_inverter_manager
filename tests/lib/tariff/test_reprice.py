# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The half-hourly history priced under a tariff, against the bill and against the accumulator."""

from __future__ import annotations

from datetime import date, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import (
    RatePeriod,
    TariffConfig,
)
from custom_components.givenergy_inverter_manager.lib.tariff.reprice import (
    BillPeriod,
    Rounding,
    import_by_band,
    reprice,
)
from custom_components.givenergy_inverter_manager.lib.tariff.slots import SlotDay

DUBLIN = ZoneInfo("Europe/Dublin")
UTC = timezone.utc


def _tariff(**changes) -> TariffConfig:
    """A tariff with the shape of a real bill: two timed bands over a day rate, a saving, a
    monthly levy and VAT. The figures are round, not any supplier's."""
    fields = {
        "rate_periods": [
            RatePeriod("Night", 0.18, time(23, 0), time(8, 0)),
            RatePeriod("Boost", 0.1056, time(2, 0), time(4, 0)),
        ],
        "base_rate": 0.365,
        "base_rate_name": "Day",
        "export_rate": 0.195,
        "standing_charge": 0.8259,
        "pso_levy": 1.46,
        "vat_rate": 9.0,
        "discount_rate": 5.5,
        "bill_start_day": 16,
    }
    return TariffConfig(**{**fields, **changes})


# Slot numbers (half hours from midnight) on a day with no clock change.
BOOST = range(4, 8)  # 02:00 to 04:00
NIGHT = [*range(0, 4), *range(8, 16), *range(46, 48)]  # 23:00 to 08:00 except the boost
DAY = range(16, 46)  # 08:00 to 23:00
SOLAR = range(24, 28)


def _spread(day: SlotDay, series: str, slots, kwh: float) -> None:
    for index in slots:
        day.flows[series][index] += kwh / len(slots)
        day.seconds[index] = 1800


def _october_bill_days() -> list[SlotDay]:
    """Thirty days, 16 September to 15 October, using 257, 67 and 619 kWh in the three bands
    and exporting 47 kWh, as the meter registers of the bill being checked read."""
    days = []
    for offset in range(30):
        day = SlotDay(date(2026, 9, 16) + timedelta(days=offset), DUBLIN)
        _spread(day, "import", BOOST, 257 / 30)
        _spread(day, "import", NIGHT, 619 / 30)
        _spread(day, "import", DAY, 67 / 30)
        _spread(day, "export", SOLAR, 47 / 30)
        days.append(day)
    return days


def test_the_bands_come_out_as_the_meter_registers_read():
    bands = import_by_band(_october_bill_days(), _tariff())
    assert bands == pytest.approx({"Boost": 257.0, "Night": 619.0, "Day": 67.0})


def test_rounding_each_band_reproduces_the_bill_to_the_cent():
    bill = reprice(
        _october_bill_days(), _tariff(), BillPeriod(30, 30), Rounding.PER_BAND
    ).bill
    assert bill.energy == 163.02
    assert bill.supplier_saving == 8.97
    assert bill.standing_charge == 24.78
    assert bill.pso_levy == 1.46
    assert bill.before_vat == 180.29
    assert bill.vat == 16.23
    assert bill.export_credit == 9.17
    assert bill.total == 187.35


def test_rounding_once_is_the_cent_short_that_the_cost_sensors_give():
    result = reprice(_october_bill_days(), _tariff(), BillPeriod(30, 30), Rounding.TOTAL)
    assert result.bill.energy == 163.01
    assert result.bill.total == 187.34


def test_the_same_slots_priced_under_another_tariff():
    flat = _tariff(rate_periods=[], base_rate=0.25)
    result = reprice(_october_bill_days(), flat, BillPeriod(30, 30), Rounding.TOTAL)
    assert result.import_kwh_by_band == pytest.approx({"Day": 943.0})
    assert result.energy_cost == pytest.approx(943 * 0.25)


def test_the_export_credit_and_coverage_are_reported():
    result = reprice(_october_bill_days(), _tariff(), BillPeriod(30, 30))
    assert result.export_kwh == pytest.approx(47.0)
    assert result.export_credit == pytest.approx(47 * 0.195)
    assert result.coverage == pytest.approx(1.0)  # every slot of every day was observed


def test_no_days_is_an_empty_bill_with_no_coverage():
    result = reprice([], _tariff(), BillPeriod(1, 30))
    assert result.import_kwh_by_band == {}
    assert result.coverage == 0.0
    assert result.energy_cost == 0.0


def test_the_repeated_hour_on_a_fall_back_day_is_priced_both_times():
    day = SlotDay(date(2026, 10, 25), DUBLIN)
    assert day.slot_count == 50
    # 01:00 to 02:00 happens twice. Both passes are in the Night band, and so is 02:00 to 04:00
    # Boost, which on this day is four real slots later than on a normal day.
    for index in range(day.slot_count):
        day.flows["import"][index] = 1.0
    bands = import_by_band([day], _tariff())
    assert bands["Boost"] == 4.0  # 02:00 to 04:00 wall clock, whichever clock is in force
    assert sum(bands.values()) == 50.0


def test_a_slot_straddling_a_window_edge_is_priced_by_its_start():
    day = SlotDay(date(2026, 6, 1), DUBLIN)
    day.flows["import"][46] = 1.0  # 23:00 to 23:30, the first slot of Night
    day.flows["import"][45] = 1.0  # 22:30 to 23:00, still Day
    bands = import_by_band([day], _tariff())
    assert bands == {"Day": 1.0, "Night": 1.0}

