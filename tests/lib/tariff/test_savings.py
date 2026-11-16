# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The saving from solar and a battery: the house load bought from the grid, less what was paid."""

from __future__ import annotations

from datetime import date, time
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import Battery, RatePeriod, TariffConfig, savings
from custom_components.givenergy_inverter_manager.lib.tariff.reprice import BillPeriod
from custom_components.givenergy_inverter_manager.lib.tariff.slots import SlotDay

DUBLIN = ZoneInfo("Europe/Dublin")
PERIOD = BillPeriod(1, 30)


def _tariff() -> TariffConfig:
    """Round figures with nothing but energy: 0.30 by day, 0.10 at night, 0.10 for export."""
    return TariffConfig(
        rate_periods=[RatePeriod("Night", 0.10, time(23, 0), time(8, 0))],
        base_rate=0.30,
        base_rate_name="Day",
        export_rate=0.10,
        standing_charge=0.0,
        pso_levy=0.0,
        vat_rate=0.0,
        discount_rate=0.0,
        bill_start_day=1,
    )


def _put(day: SlotDay, name: str, slots: range, kwh: float) -> None:
    series = day.loads if name == "house" else day.flows
    for index in slots:
        series[name][index] += kwh / len(slots)
        day.seconds[index] = 1800


def _solar_day() -> SlotDay:
    """House uses 10 kWh by day. Solar covers 4 of it and sends 2 more to the grid."""
    day = SlotDay(date(2026, 6, 1), DUBLIN)
    _put(day, "house", range(16, 36), 10.0)
    _put(day, "import", range(16, 36), 6.0)
    _put(day, "export", range(24, 28), 2.0)
    return day


def _battery_day() -> SlotDay:
    """Charge 4 kWh at the night rate, then run a 10 kWh daytime house from the battery."""
    day = SlotDay(date(2026, 6, 1), DUBLIN)
    _put(day, "house", range(16, 36), 10.0)
    _put(day, "import", range(0, 4), 4.0)
    _put(day, "grid_to_battery", range(0, 4), 4.0)
    _put(day, "battery_discharge", range(16, 36), 6.0)
    day.soc_pct[40] = 40.0
    return day


def test_solar_use_and_export_are_the_difference_between_the_two_bills():
    result = savings([_solar_day()], _tariff(), PERIOD)
    # Without the system: 10 x 0.30 = 3.00. Paid: 6 x 0.30 - 2 x 0.10 = 1.60.
    assert result.without_system.total == 3.00
    assert result.actual.total == 1.60
    assert result.total == 1.40
    assert result.stored_energy_value == 0.0
    assert result.coverage == pytest.approx(20 / 48)


def test_stored_energy_is_valued_at_what_the_grid_energy_cost():
    battery = Battery(capacity_kwh=10, soc_before_pct=20, wear_per_kwh=0.02)
    result = savings([_battery_day()], _tariff(), PERIOD, battery)
    # Paid 4 x 0.10 = 0.40 against 3.00, so 2.60. The battery holds 2 kWh more, bought at
    # 0.10, so +0.20. Wear is 6 kWh x 0.02 = 0.12. 2.60 + 0.20 - 0.12 = 2.68.
    assert result.bill_difference == 2.60
    assert result.stored_energy_value == 0.20
    assert result.battery_wear == 0.12
    assert result.total == 2.68


def test_a_fall_in_stored_energy_is_a_cost():
    battery = Battery(capacity_kwh=10, soc_before_pct=60)
    result = savings([_battery_day()], _tariff(), PERIOD, battery)
    assert result.stored_energy_value == -0.20  # 2 kWh lost at 0.10


def test_with_no_grid_charge_stored_energy_is_valued_at_the_cheapest_rate():
    day = _battery_day()
    day.flows["grid_to_battery"] = [0.0] * day.slot_count
    battery = Battery(capacity_kwh=10, soc_before_pct=20)
    assert savings([day], _tariff(), PERIOD, battery).stored_energy_value == 0.20


def test_without_the_opening_charge_or_a_reading_there_is_no_stored_energy_value():
    no_opening = Battery(capacity_kwh=10)
    assert savings([_battery_day()], _tariff(), PERIOD, no_opening).stored_energy_value == 0.0
    unseen = _battery_day()
    unseen.soc_pct = [None] * unseen.slot_count
    battery = Battery(capacity_kwh=10, soc_before_pct=20)
    assert savings([unseen], _tariff(), PERIOD, battery).stored_energy_value == 0.0


def test_no_house_load_is_refused():
    day = SlotDay(date(2026, 6, 1), DUBLIN)
    with pytest.raises(ValueError, match="no house load"):
        savings([day], _tariff(), PERIOD)
