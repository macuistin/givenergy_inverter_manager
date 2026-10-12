"""A daily counter that steps a thousand times is not booked, in a real Home Assistant."""

from __future__ import annotations

import logging

import pytest
from conftest import MIDDAY, PREFIX

pytestmark = pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)

IMPORT_COUNTER = f"sensor.{PREFIX}_import_energy_today_kwh"
AC_CHARGE_COUNTER = f"sensor.{PREFIX}_ac_charge_energy_today_kwh"
ENERGY = {"unit_of_measurement": "kWh", "device_class": "energy"}


async def _refresh(hass, coordinator, freezer, seconds: float = 30) -> None:
    freezer.tick(seconds)
    await coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_a_counter_that_steps_a_thousand_times_books_nothing(
    hass, loaded_entry, freezer, caplog
):
    coordinator = loaded_entry.runtime_data
    before_import = coordinator.data.today.import_kwh
    before_week = coordinator.data.week.grid_to_battery_kwh
    assert before_import > 0

    hass.states.async_set(IMPORT_COUNTER, before_import * 1000, ENERGY)
    hass.states.async_set(AC_CHARGE_COUNTER, 1400.0, ENERGY)
    with caplog.at_level(logging.WARNING):
        await _refresh(hass, coordinator, freezer)

    assert coordinator.data.today.import_kwh == pytest.approx(before_import)
    assert coordinator.data.week.grid_to_battery_kwh == pytest.approx(before_week)
    lines = [r.getMessage() for r in caplog.records if "energy counter" in r.getMessage()]
    assert any("import energy counter" in line and "probable unit change" in line for line in lines)


async def test_a_normal_rise_is_booked(hass, loaded_entry, freezer, caplog):
    coordinator = loaded_entry.runtime_data
    before_import = coordinator.data.today.import_kwh

    hass.states.async_set(IMPORT_COUNTER, before_import + 0.02, ENERGY)
    with caplog.at_level(logging.WARNING):
        await _refresh(hass, coordinator, freezer)

    assert coordinator.data.today.import_kwh == pytest.approx(before_import + 0.02)
    assert not [r for r in caplog.records if "energy counter" in r.getMessage()]
