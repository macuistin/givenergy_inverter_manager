"""Cost accumulation across a dated rate change: old rates before the date, new from it.

The engine prices each step at the tariff in force on the step's date, and adds to the
running totals. It never recalculates a total that is already stored.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_EXPORT_RATE,
    CONF_RATE_PERIODS,
    CONF_TARIFF_CHANGES,
)
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run

CHANGE_DAY = date(2026, 11, 1)
OLD_BASE, OLD_EXPORT = 0.3334, 0.195
NEW_BASE, NEW_EXPORT = 0.40, 0.21
# Discount 5.5% off the energy rate, then 9% VAT, as the tariff bills each kWh.
BILLED = (1 - 0.055) * 1.09


def _cfg(with_change: bool = True) -> dict:
    cfg = _nightboost_cfg()
    if with_change:
        cfg[CONF_TARIFF_CHANGES] = [
            {
                "effective": CHANGE_DAY.isoformat(),
                CONF_BASE_RATE: NEW_BASE,
                CONF_BASE_RATE_NAME: "Standard",
                CONF_EXPORT_RATE: NEW_EXPORT,
                CONF_RATE_PERIODS: [],
            }
        ]
    return cfg


def _afternoon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 14, 30)


def _step(acc: EnergyAccumulator, day: date, cfg: dict, grid_w: float):
    """One 30 minute step at 14:30 on *day*, drawing grid_w from the grid (negative exports)."""
    now = _afternoon(day)
    raw = _raw(grid_power_w=grid_w, house_load_w=abs(grid_w), solar_power_w=0.0)
    data, _ = _run(raw=raw, cfg=cfg, now=now, acc=acc, last_update_time=now - timedelta(minutes=30))
    return data


class TestImportCost:
    def test_the_day_before_the_change_is_priced_at_the_old_rate(self):
        acc = EnergyAccumulator()
        data = _step(acc, date(2026, 10, 31), _cfg(), 2000.0)
        assert acc.import_cost_by_period == {"Day": pytest.approx(OLD_BASE * BILLED)}
        assert data.current_rate == pytest.approx(OLD_BASE)

    def test_the_effective_day_is_priced_at_the_new_rate(self):
        acc = EnergyAccumulator()
        data = _step(acc, CHANGE_DAY, _cfg(), 2000.0)
        assert acc.import_cost_by_period == {"Standard": pytest.approx(NEW_BASE * BILLED)}
        assert data.current_rate == pytest.approx(NEW_BASE)
        assert data.current_rate_name == "Standard"

    def test_costs_already_stored_are_not_restated_when_the_rates_change(self):
        acc = EnergyAccumulator()
        cfg = _cfg()
        _step(acc, date(2026, 10, 31), cfg, 2000.0)
        stored_before = dict(acc.import_cost_by_period)
        _step(acc, CHANGE_DAY, cfg, 2000.0)
        assert acc.import_cost_by_period["Day"] == stored_before["Day"]
        assert acc.import_cost_by_period["Standard"] == pytest.approx(NEW_BASE * BILLED)
        assert acc.total_import_cost == pytest.approx((OLD_BASE + NEW_BASE) * BILLED)

    def test_a_house_load_cost_follows_the_same_split(self):
        acc = EnergyAccumulator()
        cfg = _cfg()
        _step(acc, date(2026, 10, 31), cfg, 2000.0)
        _step(acc, CHANGE_DAY, cfg, 2000.0)
        assert acc.grid_equivalent_load_cost == pytest.approx((OLD_BASE + NEW_BASE) * BILLED)

    def test_with_no_change_the_effective_day_keeps_the_saved_rate(self):
        acc = EnergyAccumulator()
        data = _step(acc, CHANGE_DAY, _cfg(with_change=False), 2000.0)
        assert acc.import_cost_by_period == {"Day": pytest.approx(OLD_BASE * BILLED)}
        assert data.current_rate == pytest.approx(OLD_BASE)


class TestExportEarnings:
    def test_export_is_credited_at_the_old_rate_before_the_date(self):
        acc = EnergyAccumulator()
        _step(acc, date(2026, 10, 31), _cfg(), -2000.0)
        assert acc.export_earnings == pytest.approx(OLD_EXPORT)

    def test_export_is_credited_at_the_new_rate_from_the_date(self):
        acc = EnergyAccumulator()
        _step(acc, CHANGE_DAY, _cfg(), -2000.0)
        assert acc.export_earnings == pytest.approx(NEW_EXPORT)

    def test_earnings_already_stored_keep_the_old_rate(self):
        acc = EnergyAccumulator()
        cfg = _cfg()
        _step(acc, date(2026, 10, 31), cfg, -2000.0)
        _step(acc, CHANGE_DAY, cfg, -2000.0)
        assert acc.export_earnings == pytest.approx(OLD_EXPORT + NEW_EXPORT)
