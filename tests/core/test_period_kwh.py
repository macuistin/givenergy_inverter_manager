"""The accumulators keep the kWh imported and used in each rate period, beside the cost."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run


def _step(acc: EnergyAccumulator, at: datetime, grid_w: float, load_w: float) -> None:
    raw = _raw(grid_power_w=grid_w, house_load_w=load_w, solar_power_w=0.0)
    _run(
        raw=raw,
        cfg=_nightboost_cfg(),
        now=at,
        acc=acc,
        last_update_time=at - timedelta(minutes=30),
    )


def test_import_kwh_goes_to_the_period_that_priced_it():
    acc = EnergyAccumulator()

    _step(acc, datetime(2026, 10, 14, 3, 0), 2000.0, 2000.0)  # Nightboost 02:00 to 04:00
    _step(acc, datetime(2026, 10, 14, 6, 0), 1000.0, 1000.0)  # Night
    _step(acc, datetime(2026, 10, 14, 14, 0), 4000.0, 4000.0)  # Day

    assert acc.import_kwh_by_period == {
        "Nightboost": pytest.approx(1.0),
        "Night": pytest.approx(0.5),
        "Day": pytest.approx(2.0),
    }


def test_the_kwh_by_period_add_up_to_the_import_total():
    acc = EnergyAccumulator()
    for hour, watts in ((1, 1500.0), (3, 2500.0), (9, 800.0), (23, 3000.0)):
        _step(acc, datetime(2026, 10, 14, hour, 0), watts, watts)

    assert sum(acc.import_kwh_by_period.values()) == pytest.approx(acc.import_kwh)
    assert set(acc.import_kwh_by_period) == set(acc.import_cost_by_period)


def test_house_use_is_kept_by_period_whatever_the_grid_supplied():
    acc = EnergyAccumulator()

    _step(acc, datetime(2026, 10, 14, 6, 0), 0.0, 1000.0)  # Night, the battery supplied it
    _step(acc, datetime(2026, 10, 14, 14, 0), 500.0, 3000.0)  # Day

    assert acc.house_kwh_by_period == {"Night": pytest.approx(0.5), "Day": pytest.approx(1.5)}
    assert sum(acc.house_kwh_by_period.values()) == pytest.approx(acc.house_kwh)


def test_a_new_accumulator_has_no_period_kwh():
    acc = EnergyAccumulator()

    assert acc.import_kwh_by_period == {}
    assert acc.house_kwh_by_period == {}
    assert acc == EnergyAccumulator()
