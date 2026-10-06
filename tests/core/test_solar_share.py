"""Solar share is the share of the house's consumption met by solar kept on site."""

import pytest

from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator


def _acc(**fields) -> EnergyAccumulator:
    return EnergyAccumulator(**fields)


def test_no_consumption_is_zero_not_full():
    assert _acc(house_kwh=0.0, solar_kwh=5.0, export_kwh=0.0).solar_share_pct == 0.0


def test_solar_all_exported_covers_nothing():
    assert _acc(house_kwh=10.0, solar_kwh=6.0, export_kwh=6.0).solar_share_pct == 0.0


def test_solar_all_kept_is_the_solar_over_the_load():
    assert _acc(house_kwh=10.0, solar_kwh=4.0, export_kwh=0.0).solar_share_pct == pytest.approx(
        40.0
    )


def test_solar_that_exceeds_the_load_is_capped_at_full():
    assert _acc(house_kwh=10.0, solar_kwh=14.0, export_kwh=0.0).solar_share_pct == 100.0


def test_export_larger_than_solar_is_floored_at_zero():
    assert _acc(house_kwh=10.0, solar_kwh=2.0, export_kwh=3.0).solar_share_pct == 0.0


def test_grid_import_and_battery_discharge_do_not_change_it():
    base = _acc(house_kwh=10.0, solar_kwh=8.0, export_kwh=2.0)
    with_import = _acc(
        house_kwh=10.0,
        solar_kwh=8.0,
        export_kwh=2.0,
        import_kwh=9.0,
        battery_discharge_kwh=5.0,
    )
    assert base.solar_share_pct == pytest.approx(60.0)
    assert with_import.solar_share_pct == base.solar_share_pct


def test_grid_charged_battery_lowers_self_sufficiency_but_not_solar_share():
    acc = _acc(house_kwh=10.0, solar_kwh=8.0, export_kwh=2.0, import_kwh=5.0)
    assert acc.self_sufficiency_pct == pytest.approx(50.0)
    assert acc.solar_share_pct == pytest.approx(60.0)


def test_ev_and_immersion_are_part_of_house_load_and_not_added_again():
    acc = _acc(house_kwh=10.0, zappi_kwh=4.0, immersion_kwh=2.0, solar_kwh=8.0, export_kwh=2.0)
    assert acc.solar_share_pct == pytest.approx(60.0)
