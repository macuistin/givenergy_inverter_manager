"""The half-hourly history priced under a tariff agrees with what the accumulator charged."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.core.engine import (
    AccumulationWindow,
    RawSensorValues,
    accumulate_energy,
)
from custom_components.givenergy_inverter_manager.lib.tariff import (
    EnergyAccumulator,
    TariffConfig,
)
from custom_components.givenergy_inverter_manager.lib.tariff.reprice import BillPeriod, reprice
from custom_components.givenergy_inverter_manager.lib.tariff.slot_history import SlotHistory
from custom_components.givenergy_inverter_manager.lib.tariff.slots import SlotDay, SlotEnergy
from tests.lib.tariff.test_reprice import _tariff

UTC = timezone.utc


def _simulate_day(tariff: TariffConfig, import_w) -> tuple[EnergyAccumulator, SlotDay]:
    """The same day of 30 second cycles fed to the accumulator and to the slot history."""
    acc, history = EnergyAccumulator(), SlotHistory(UTC)
    start = datetime(2026, 6, 1, tzinfo=UTC)
    previous = None
    for tick in range(2880):
        now = start + timedelta(seconds=30 * tick)
        raw = RawSensorValues(grid_power_w=import_w(now))
        period = tariff.get_current_rate(now)
        accumulate_energy(acc, raw, AccumulationWindow(tariff, period.name, now, previous))
        if previous is not None:
            history.record(
                SlotEnergy(flows={"import": raw.grid_power_w / 1000 * 30 / 3600}), previous, now
            )
        previous = now
    return acc, history.get(date(2026, 6, 1))


def test_pricing_the_slots_matches_what_the_accumulator_charged():
    tariff = _tariff()

    def watts(now: datetime) -> float:
        return 3000.0 if now.hour in (2, 3) else 800.0 + 50 * now.hour

    acc, day = _simulate_day(tariff, watts)
    result = reprice([day], tariff, BillPeriod(1, 30))
    charged = tariff.energy_cost_from_import_cost(acc.total_import_cost)
    # The accumulator prices each 30 second interval at the rate in force when it ends. The
    # slots are priced by when each half hour starts. They differ by the one interval at each
    # rate change, a few hundredths of a percent of the day's cost.
    assert result.energy_cost == pytest.approx(charged, rel=1e-3)
    # In kWh that is one interval's energy a boundary, here under 0.02 kWh a band.
    assert result.import_kwh_by_band == pytest.approx(acc.import_kwh_by_period, abs=0.03)
