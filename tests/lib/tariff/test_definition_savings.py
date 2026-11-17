# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The saving under a tariff definition agrees with the saving under the same tariff as options."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import (
    Battery,
    Locale,
    PeriodRules,
    SavingsOptions,
    RatePeriod,
    SlotHistory,
    TariffConfig,
    definition_from_config,
    definition_savings,
    savings,
)
from custom_components.givenergy_inverter_manager.lib.tariff.reprice import BillPeriod
from custom_components.givenergy_inverter_manager.lib.tariff.slots import SlotDay
from tests.lib.tariff.test_savings import _battery_day, _put, _solar_day, _tariff

DUBLIN = ZoneInfo("Europe/Dublin")
LOCALE = Locale("EUR", "IE", "Europe/Dublin", date(2026, 1, 1))
THROUGH = date(2026, 6, 1)


def _history(*days: SlotDay) -> SlotHistory:
    return SlotHistory.from_days(DUBLIN, days)


def _definition(tariff: TariffConfig | None = None):
    return definition_from_config(tariff or _tariff(), LOCALE)


def test_solar_use_and_export_are_the_difference_between_the_two_bills() -> None:
    result = definition_savings(_history(_solar_day()), _definition(), THROUGH)

    # Without the system: 10 x 0.30. Paid: 6 x 0.30 - 2 x 0.10. The standing charge cancels.
    assert result.bill_difference == Decimal("1.40")
    assert result.total == Decimal("1.40")
    assert result.stored_energy_value == 0
    assert result.battery_wear == 0
    assert result.coverage == pytest.approx(20 / 48)


def test_it_agrees_with_the_saving_under_the_same_tariff_as_options() -> None:
    battery = Battery(capacity_kwh=10, soc_before_pct=20, wear_per_kwh=0.02)
    old = savings([_battery_day()], _tariff(), BillPeriod(1, 30), battery)

    new = definition_savings(
        _history(_battery_day()), _definition(), THROUGH, SavingsOptions(battery)
    )

    assert float(new.total) == pytest.approx(old.total, abs=0.005)
    assert float(new.stored_energy_value) == pytest.approx(old.stored_energy_value, abs=0.005)
    assert float(new.battery_wear) == pytest.approx(old.battery_wear, abs=0.005)


def test_stored_energy_is_valued_at_what_the_grid_energy_cost() -> None:
    battery = Battery(capacity_kwh=10, soc_before_pct=20, wear_per_kwh=0.02)

    result = definition_savings(
        _history(_battery_day()), _definition(), THROUGH, SavingsOptions(battery)
    )

    # Paid 4 x 0.10 against 3.00, so 2.60. Two kWh more stored at 0.10 is +0.20. Wear is 0.12.
    assert result.bill_difference == Decimal("2.60")
    assert result.stored_energy_value == Decimal("0.20")
    assert result.battery_wear == Decimal("0.12")
    assert result.total == Decimal("2.68")


def test_a_fall_in_stored_energy_is_a_cost() -> None:
    battery = Battery(capacity_kwh=10, soc_before_pct=60)

    result = definition_savings(
        _history(_battery_day()), _definition(), THROUGH, SavingsOptions(battery)
    )

    assert result.stored_energy_value == Decimal("-0.20")


def test_with_no_grid_charge_stored_energy_is_valued_at_the_cheapest_band() -> None:
    day = _battery_day()
    day.flows["grid_to_battery"] = [0.0] * day.slot_count
    battery = Battery(capacity_kwh=10, soc_before_pct=20)

    result = definition_savings(_history(day), _definition(), THROUGH, SavingsOptions(battery))

    assert result.stored_energy_value == Decimal("0.20")


def test_without_the_opening_charge_or_a_reading_there_is_no_stored_energy_value() -> None:
    no_opening = Battery(capacity_kwh=10)
    unseen = _battery_day()
    unseen.soc_pct = [None] * unseen.slot_count
    opening = Battery(capacity_kwh=10, soc_before_pct=20)

    assert (
        definition_savings(
            _history(_battery_day()), _definition(), THROUGH, SavingsOptions(no_opening)
        ).stored_energy_value
        == 0
    )
    assert (
        definition_savings(
            _history(unseen), _definition(), THROUGH, SavingsOptions(opening)
        ).stored_energy_value
        == 0
    )


def test_days_after_the_day_priced_and_before_the_period_are_left_out() -> None:
    earlier, later = _solar_day(), _solar_day()
    earlier.day = date(2026, 5, 20)  # in the previous bill period
    later.day = date(2026, 6, 2)

    result = definition_savings(_history(earlier, _solar_day(), later), _definition(), THROUGH)

    assert result.total == Decimal("1.40")


def test_the_holiday_rule_reaches_the_bands() -> None:
    result = definition_savings(
        _history(_solar_day()),
        _definition(),
        THROUGH,
        SavingsOptions(rules=PeriodRules(is_holiday=lambda _day: True)),
    )

    assert result.total == Decimal("1.40")


def test_no_house_load_is_refused() -> None:
    with pytest.raises(ValueError, match="no house load"):
        definition_savings(_history(SlotDay(THROUGH, DUBLIN)), _definition(), THROUGH)
