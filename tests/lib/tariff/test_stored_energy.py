# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The value of the energy the battery gained or lost since the period began."""

from __future__ import annotations

from datetime import time

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import (
    EnergyAccumulator,
    RatePeriod,
    StoredEnergy,
    TariffConfig,
    stored_energy_change,
    value_per_stored_kwh,
)


def _tariff() -> TariffConfig:
    return TariffConfig(
        rate_periods=[RatePeriod("Night", 0.10, time(23, 0), time(8, 0))],
        base_rate=0.30,
        base_rate_name="Day",
        export_rate=0.20,
        standing_charge=0.80,
        pso_levy=1.50,
        vat_rate=10.0,
        discount_rate=0.0,
        bill_start_day=1,
    )


def test_a_stored_kwh_is_worth_the_average_cost_of_the_grid_energy_stored():
    acc = EnergyAccumulator(grid_to_battery_cost=1.20, grid_to_battery_priced_kwh=8.0)

    assert value_per_stored_kwh(acc, _tariff()) == pytest.approx(0.15)


def test_with_no_grid_charge_a_stored_kwh_is_worth_the_cheapest_rate_with_vat():
    # The 0.10 night rate plus 10% VAT.
    assert value_per_stored_kwh(EnergyAccumulator(), _tariff()) == pytest.approx(0.11)


def test_the_change_is_the_rise_in_state_of_charge_times_the_capacity():
    acc = EnergyAccumulator(soc_at_start_pct=20.0)

    stored = stored_energy_change(acc, 70.0, 10.0, _tariff())

    assert stored.change_kwh == pytest.approx(5.0)  # half of a 10 kWh battery
    assert stored.value == pytest.approx(0.55)  # 5 kWh at 0.11


def test_a_fall_is_valued_as_the_negative_of_the_same_rise():
    acc = EnergyAccumulator(soc_at_start_pct=70.0)

    assert stored_energy_change(acc, 20.0, 10.0, _tariff()).value == pytest.approx(-0.55)


@pytest.mark.parametrize(
    ("start_pct", "soc_pct", "capacity_kwh"),
    [(None, 50.0, 10.0), (20.0, None, 10.0), (20.0, 50.0, 0.0)],
)
def test_without_a_start_a_reading_or_a_capacity_there_is_no_change(
    start_pct, soc_pct, capacity_kwh
):
    acc = EnergyAccumulator(soc_at_start_pct=start_pct)

    assert stored_energy_change(acc, soc_pct, capacity_kwh, _tariff()) == StoredEnergy()
