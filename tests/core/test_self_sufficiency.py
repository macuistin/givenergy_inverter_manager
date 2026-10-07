"""Self-sufficiency is the share of the house's consumption that did not come from the grid.

Grid energy that went into the battery is stored, so it does not count against it.
"""

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


# ── Grid energy stored in the battery ────────────────────────────────────────


def test_overnight_charge_does_not_count_against_the_house():
    """The live case: 12.1 kWh imported, 7.5 kWh of it into the battery, 11.3 kWh of load.

    The old formula clamped to 0 because import was larger than the load.
    """
    acc = _acc(house_kwh=11.3, import_kwh=12.1, grid_to_battery_kwh=7.5)
    assert acc.self_sufficiency_pct == pytest.approx((1 - (12.1 - 7.5) / 11.3) * 100)
    assert acc.self_sufficiency_pct == pytest.approx(59.3, abs=0.05)


def test_without_a_grid_to_battery_reading_all_import_counts_as_before():
    acc = _acc(house_kwh=11.3, import_kwh=12.1, grid_to_battery_kwh=0.0)
    assert acc.self_sufficiency_pct == 0.0


def test_grid_to_house_is_import_less_the_battery_charge():
    acc = _acc(house_kwh=11.3, import_kwh=12.1, grid_to_battery_kwh=7.5)
    assert acc.grid_to_house_kwh == pytest.approx(4.6)


def test_a_charge_reading_above_import_leaves_no_grid_to_house():
    """The two counters can disagree by a rounding step. Neither goes negative."""
    acc = _acc(house_kwh=10.0, import_kwh=7.4, grid_to_battery_kwh=7.5)
    assert acc.grid_to_house_kwh == 0.0
    assert acc.self_sufficiency_pct == pytest.approx(100.0)


def test_supplied_without_grid_is_the_load_not_drawn_from_the_grid():
    acc = _acc(house_kwh=11.3, import_kwh=12.1, grid_to_battery_kwh=7.5)
    assert acc.supplied_without_grid_kwh == pytest.approx(11.3 - 4.6)


def test_supplied_without_grid_is_zero_when_the_grid_met_the_whole_load():
    acc = _acc(house_kwh=4.0, import_kwh=9.0, grid_to_battery_kwh=1.0)
    assert acc.supplied_without_grid_kwh == 0.0


def test_ev_and_immersion_energy_bought_from_the_grid_still_counts_as_grid():
    """Both are in house_kwh. Only the battery's share of import is taken off."""
    acc = _acc(
        house_kwh=20.0, zappi_kwh=8.0, immersion_kwh=2.0, import_kwh=18.0, grid_to_battery_kwh=6.0
    )
    assert acc.grid_to_house_kwh == pytest.approx(12.0)
    assert acc.self_sufficiency_pct == pytest.approx(40.0)


def test_discharge_of_grid_origin_energy_counts_as_supplied_from_storage():
    """10 kWh bought cheap overnight into the battery and then used by the house: 100%."""
    acc = _acc(house_kwh=10.0, import_kwh=10.0, grid_to_battery_kwh=10.0, battery_discharge_kwh=10.0)
    assert acc.self_sufficiency_pct == pytest.approx(100.0)
