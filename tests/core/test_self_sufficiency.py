"""Self-sufficiency is the share of the house's consumption that was not bought from the grid."""

import pytest

from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator


def _acc(**fields) -> EnergyAccumulator:
    return EnergyAccumulator(**fields)


def test_nothing_imported_is_fully_self_sufficient():
    assert _acc(house_kwh=10.0, import_kwh=0.0).self_sufficiency_pct == pytest.approx(100.0)


def test_half_the_load_imported_is_half_self_sufficient():
    assert _acc(house_kwh=10.0, import_kwh=5.0).self_sufficiency_pct == pytest.approx(50.0)


def test_import_equal_to_the_load_is_not_self_sufficient():
    assert _acc(house_kwh=10.0, import_kwh=10.0).self_sufficiency_pct == 0.0


def test_importing_more_than_the_load_to_charge_the_battery_stays_at_zero():
    assert _acc(house_kwh=10.0, import_kwh=14.0).self_sufficiency_pct == 0.0


def test_ev_and_immersion_are_part_of_house_load_and_not_added_again():
    acc = _acc(house_kwh=10.0, zappi_kwh=4.0, immersion_kwh=2.0, import_kwh=5.0)
    assert acc.self_sufficiency_pct == pytest.approx(50.0)


def test_solar_and_battery_discharge_do_not_hide_grid_import():
    """The old sum read 100% with 25 kWh imported, because solar and discharge were added to it."""
    acc = _acc(house_kwh=40.0, import_kwh=25.0, solar_kwh=16.0, battery_discharge_kwh=20.0)
    assert acc.self_sufficiency_pct == pytest.approx(37.5)


def test_no_consumption_reads_full():
    assert _acc(house_kwh=0.0, import_kwh=0.0).self_sufficiency_pct == 100.0
