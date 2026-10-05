"""Battery dates come from the cycle's `now`, not the wall clock.

Every date here is in 2031, so a leftover date.today() call would fail these tests.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
from tests.conftest import _raw, _run
from tests.core.flat_battery import update_battery_stats

NOW = datetime(2031, 3, 12, 14, 0)


def test_full_charge_date_is_the_cycle_date():
    stats = BatteryStats()
    _run(raw=_raw(battery_soc=99.5), now=NOW, last_soc=90.0, battery_stats=stats)
    assert stats.last_full_charge_date == date(2031, 3, 12)


def test_tracking_starts_on_the_cycle_date():
    stats = BatteryStats(total_cycles=40.0)
    _run(raw=_raw(battery_soc=60.0), now=NOW, last_soc=61.0, battery_stats=stats)
    assert stats.tracking_start_date == date(2031, 3, 12)
    assert stats.tracking_start_cycles == pytest.approx(40.0)


def test_bms_counter_starts_tracking_on_the_cycle_date():
    stats = BatteryStats()
    _run(
        raw=_raw(battery_soc=60.0, battery_lifetime_cycles=120.0),
        now=NOW,
        last_soc=60.0,
        battery_stats=stats,
    )
    assert stats.tracking_start_date == date(2031, 3, 12)
    assert stats.tracking_start_cycles == pytest.approx(120.0)


def test_years_remaining_counts_days_to_the_cycle_date():
    stats = BatteryStats(
        total_cycles=100.0,
        tracking_start_date=date(2031, 1, 1),
        tracking_start_cycles=0.0,
    )
    data, _ = _run(raw=_raw(battery_soc=60.0), now=NOW, last_soc=60.0, battery_stats=stats)
    assert data.battery_years_remaining == pytest.approx((6000 - 100) / ((100 / 70) * 365))


def test_years_remaining_is_unknown_before_the_minimum_tracked_days():
    stats = BatteryStats(
        total_cycles=100.0,
        tracking_start_date=date(2031, 3, 10),
        tracking_start_cycles=0.0,
    )
    data, _ = _run(raw=_raw(battery_soc=60.0), now=NOW, last_soc=60.0, battery_stats=stats)
    assert data.battery_years_remaining is None


def test_update_battery_stats_uses_the_date_it_is_given():
    stats = BatteryStats()
    update_battery_stats(stats, 99.0, 98.0, today=date(2040, 12, 31))
    assert stats.last_full_charge_date == date(2040, 12, 31)
    assert stats.tracking_start_date == date(2040, 12, 31)
