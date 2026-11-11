# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The figures the energy accumulator derives from its running totals."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import EnergyAccumulator


def test_cost_and_net_position_come_from_the_cost_by_period():
    acc = EnergyAccumulator(
        import_cost_by_period={"Night": 1.20, "Day": 2.30}, export_earnings=0.50
    )

    assert acc.total_import_cost == pytest.approx(3.50)
    assert acc.total_cost == pytest.approx(3.50)
    assert acc.net_position == pytest.approx(-3.00)  # earned 0.50, paid 3.50


def test_import_is_split_into_peak_and_cheap_fractions():
    acc = EnergyAccumulator(import_kwh=10.0, import_kwh_peak=2.5, import_kwh_cheap=7.5)

    assert acc.peak_import_fraction == 0.25
    assert acc.cheap_import_fraction == 0.75


def test_with_no_import_both_fractions_are_zero():
    acc = EnergyAccumulator()

    assert acc.peak_import_fraction == 0.0
    assert acc.cheap_import_fraction == 0.0


def test_grid_energy_stored_in_the_battery_is_not_counted_against_the_house():
    acc = EnergyAccumulator(import_kwh=10.0, grid_to_battery_kwh=6.0, house_kwh=16.0)

    assert acc.grid_to_house_kwh == 4.0
    assert acc.supplied_without_grid_kwh == 12.0
    assert acc.self_sufficiency_pct == 75.0  # 4 of 16 kWh came from the grid


def test_a_grid_to_battery_reading_over_the_import_never_goes_negative():
    acc = EnergyAccumulator(import_kwh=5.0, grid_to_battery_kwh=6.0, house_kwh=10.0)

    assert acc.grid_to_house_kwh == 0.0
    assert acc.self_sufficiency_pct == 100.0


def test_with_no_consumption_self_sufficiency_is_full_and_the_solar_share_is_nothing():
    acc = EnergyAccumulator(solar_kwh=5.0)

    assert acc.self_sufficiency_pct == 100.0
    assert acc.solar_share_pct == 0.0


def test_the_solar_share_counts_generation_kept_on_site():
    acc = EnergyAccumulator(solar_kwh=8.0, export_kwh=2.0, house_kwh=12.0)

    assert acc.solar_share_pct == 50.0  # 6 kWh kept of 12 kWh used
    assert acc.self_consumption_pct == 75.0  # 6 of 8 kWh generated was used on site


def test_the_solar_share_is_capped_at_the_whole_load():
    assert EnergyAccumulator(solar_kwh=20.0, house_kwh=5.0).solar_share_pct == 100.0


def test_with_no_generation_nothing_was_self_consumed():
    assert EnergyAccumulator(export_kwh=1.0).self_consumption_pct == 0.0
