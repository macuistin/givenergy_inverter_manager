"""The saving compares what was paid with what the same load would have cost from the grid.

The grid price depends on when the load ran. Pricing every kWh at the day rate overstated
the saving whenever load ran in a cheaper period, such as an EV charging at night.
"""

from datetime import datetime, timedelta

import pytest

from custom_components.givenergy_inverter_manager.accumulation import _deserialize, _serialize
from tests.conftest import _nightboost_cfg, _raw, _run

STEP = timedelta(seconds=30)
LOAD_W = 3600.0
STEP_KWH = LOAD_W / 1000 * STEP.total_seconds() / 3600
KEEP = (1 - 0.055) * (1 + 0.09)  # discount, then VAT, as in _nightboost_cfg


def _cycle(hour, *, solar_w=0.0, grid_w=0.0):
    now = datetime(2026, 10, 6, hour, 0)
    raw = _raw(house_load_w=LOAD_W, solar_power_w=solar_w, grid_power_w=grid_w)
    data, _ = _run(raw=raw, cfg=_nightboost_cfg(), now=now, last_update_time=now - STEP)
    return data


def test_day_load_is_priced_at_the_day_rate():
    data = _cycle(12)
    assert data.today.grid_equivalent_load_cost == pytest.approx(STEP_KWH * 0.3334 * KEEP)


def test_night_load_is_priced_at_the_night_rate():
    data = _cycle(0)
    assert data.today.grid_equivalent_load_cost == pytest.approx(STEP_KWH * 0.1644 * KEEP)


def test_nightboost_load_is_priced_at_the_nightboost_rate():
    data = _cycle(3)
    assert data.today.grid_equivalent_load_cost == pytest.approx(STEP_KWH * 0.0965 * KEEP)


def test_load_bought_from_the_grid_at_the_time_saves_nothing():
    data = _cycle(3, grid_w=LOAD_W)
    assert data.saving_vs_grid_today == pytest.approx(0.0, abs=1e-4)


def test_load_covered_by_solar_saves_what_the_grid_would_have_charged():
    data = _cycle(12, solar_w=LOAD_W)
    assert data.saving_vs_grid_today == pytest.approx(STEP_KWH * 0.3334 * KEEP, abs=1e-4)


def test_cheaper_period_gives_a_smaller_saving_for_the_same_solar_cover():
    night = _cycle(0, solar_w=LOAD_W)
    day = _cycle(12, solar_w=LOAD_W)
    assert night.saving_vs_grid_today < day.saving_vs_grid_today


class TestStoredAccumulators:
    STORED = {
        "import_kwh": 10.0,
        "house_kwh": 20.0,
        "import_cost_by_period": {"Night": 2.0, "Day": 1.0},
    }

    def test_cost_is_saved_and_restored(self):
        state = _deserialize({"today": {**self.STORED, "grid_equivalent_load_cost": 4.5}})
        assert state.today.grid_equivalent_load_cost == 4.5
        assert _serialize(state)["today"]["grid_equivalent_load_cost"] == 4.5

    def test_data_saved_before_the_cost_was_tracked_uses_the_average_rate_paid(self):
        state = _deserialize({"today": self.STORED})
        assert state.today.grid_equivalent_load_cost == pytest.approx(20.0 * 3.0 / 10.0)

    def test_no_import_means_no_estimate(self):
        state = _deserialize({"today": {"house_kwh": 20.0}})
        assert state.today.grid_equivalent_load_cost == 0.0
