"""Each cycle's readings as slot energy: counter rises first, power when there is no rise."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.core.engine import RawSensorValues
from custom_components.givenergy_inverter_manager.core.slot_sampler import SlotSampler

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(seconds=30)
T2 = T1 + timedelta(seconds=30)


def _raw(**fields) -> RawSensorValues:
    return RawSensorValues(**fields)


def test_the_first_cycle_has_no_interval_but_notes_the_counters():
    sampler = SlotSampler()
    sampler.sample(_raw(import_energy_today_kwh=5.0), None, T0)
    assert sampler.latest is None

    sampler.sample(_raw(import_energy_today_kwh=5.1), T0, T1)
    assert sampler.latest.energy.flows["import"] == pytest.approx(0.1)


def test_a_counter_rise_wins_over_the_power_reading():
    sampler = SlotSampler()
    sampler.sample(_raw(import_energy_today_kwh=5.0, grid_power_w=3000.0), None, T0)
    sampler.sample(_raw(import_energy_today_kwh=5.0, grid_power_w=3000.0), T0, T1)
    assert sampler.latest.energy.flows["import"] == 0.0  # the meter has not moved yet


def test_power_is_integrated_where_there_is_no_counter():
    sampler = SlotSampler()
    sampler.sample(_raw(grid_power_w=3600.0), None, T0)
    sampler.sample(_raw(grid_power_w=3600.0, solar_power_w=1200.0), T0, T1)
    flows = sampler.latest.energy.flows
    assert flows["import"] == pytest.approx(0.03)  # 3.6 kW for 30 seconds
    assert flows["export"] == 0.0
    assert flows["solar"] == pytest.approx(0.01)
    assert flows["grid_to_battery"] == 0.0  # no power reading stands in for this counter


def test_export_and_battery_directions_follow_the_signs_inside_the_integration():
    sampler = SlotSampler()
    sampler.sample(_raw(), None, T0)
    sampler.sample(_raw(grid_power_w=-3600.0, battery_power_w=-7200.0), T0, T1)
    flows = sampler.latest.energy.flows
    assert flows["export"] == pytest.approx(0.03)
    assert flows["battery_discharge"] == pytest.approx(0.06)
    assert flows["import"] == 0.0 and flows["battery_charge"] == 0.0


def test_the_ev_and_the_immersion_always_use_power_and_the_house_is_the_load_reading():
    sampler = SlotSampler()
    sampler.sample(_raw(load_energy_today_kwh=10.0), None, T0)
    raw = _raw(
        load_energy_today_kwh=10.05,
        house_load_w=9999.0,
        ev_power_w=7200.0,
        immersion_on=True,
        immersion_wattage_w=3600.0,
    )
    sampler.sample(raw, T0, T1)
    loads = sampler.latest.energy.loads
    assert loads["house"] == pytest.approx(0.05)  # the counter's rise, not 9.999 kW
    assert loads["ev"] == pytest.approx(0.06)
    assert loads["immersion"] == pytest.approx(0.03)


def test_an_immersion_that_is_off_uses_nothing():
    sampler = SlotSampler()
    sampler.sample(_raw(), None, T0)
    sampler.sample(_raw(immersion_on=False, immersion_wattage_w=3000.0), T0, T1)
    assert sampler.latest.energy.loads["immersion"] == 0.0


def test_a_counter_that_drops_out_gives_power_and_no_rise_across_the_hole():
    sampler = SlotSampler()
    sampler.sample(_raw(import_energy_today_kwh=5.0), None, T0)
    sampler.sample(_raw(import_energy_today_kwh=None, grid_power_w=3600.0), T0, T1)
    assert sampler.latest.energy.flows["import"] == pytest.approx(0.03)

    # It comes back 20 kWh higher: that is not this cycle's energy, so power is used again.
    sampler.sample(_raw(import_energy_today_kwh=25.0, grid_power_w=3600.0), T1, T2)
    assert sampler.latest.energy.flows["import"] == pytest.approx(0.03)

    sampler.sample(_raw(import_energy_today_kwh=25.1), T2, T2 + timedelta(seconds=30))
    assert sampler.latest.energy.flows["import"] == pytest.approx(0.1)


def test_a_counter_that_reset_at_midnight_gives_power_for_that_cycle():
    sampler = SlotSampler()
    before = datetime(2026, 6, 1, 23, 59, 40, tzinfo=timezone.utc)
    after = datetime(2026, 6, 2, 0, 0, 10, tzinfo=timezone.utc)
    sampler.sample(_raw(import_energy_today_kwh=12.0), None, before)
    sampler.sample(_raw(import_energy_today_kwh=0.0, grid_power_w=3600.0), before, after)
    assert sampler.latest.energy.flows["import"] == pytest.approx(0.03)


def test_a_clock_that_did_not_move_forward_gives_no_sample():
    sampler = SlotSampler()
    sampler.sample(_raw(), T1, T1)
    assert sampler.latest is None
    sampler.sample(_raw(), T1, T0)
    assert sampler.latest is None


def test_a_negative_power_is_never_booked():
    sampler = SlotSampler()
    sampler.sample(_raw(), None, T0)
    sampler.sample(_raw(solar_power_w=-50.0, house_load_w=-10.0, ev_power_w=-5.0), T0, T1)
    energy = sampler.latest.energy
    assert energy.flows["solar"] == 0.0
    assert energy.loads["house"] == 0.0 and energy.loads["ev"] == 0.0
    energy.check()  # nothing the store would refuse
