"""The value of the energy the battery gained or lost since the day began.

The saving is the cost of the load at the rate in force, less what was paid. Energy bought
to fill the battery is paid for on the day it is bought but only earns its keep on the day
the battery gives it back. Without a correction the saving reads negative after a cheap
overnight charge and recovers through the day. The correction adds the value of the change
in stored energy, so the energy bought and the energy still held balance.

The change is (SoC now minus SoC at the start of the day) times the battery capacity. Each kWh
is valued at the average cost of the grid energy that went into the battery today, or at the
cheapest rate in the tariff when none did. A fall in stored energy is valued the same way, so
it is the negative of what the same rise would have been.

Why this rule: the grid energy stored today is the only energy the battery was bought with,
so its average cost is what a kWh of stored energy cost. Solar stored has no purchase price
and a rate of 0 would pull the average down, so it is left out. With no grid charge there is
no cost to average, and the cheapest rate is the lowest price the battery could have been
filled at, which keeps the figure steady from day to day.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass

from .tariff import EnergyAccumulator, TariffConfig


@dataclass(frozen=True)
class StoredEnergy:
    """The kWh the battery gained (positive) or lost today and the value of each kWh."""

    change_kwh: float = 0.0
    value_per_kwh: float = 0.0

    @property
    def value(self) -> float:
        return self.change_kwh * self.value_per_kwh


def value_per_stored_kwh(acc: EnergyAccumulator, tariff: TariffConfig) -> float:
    """Average cost of the grid energy stored today, else the cheapest rate.

    Both are after the supplier discount and VAT, like every cost the accumulators hold.
    """
    if acc.grid_to_battery_priced_kwh > 0:
        return acc.grid_to_battery_cost / acc.grid_to_battery_priced_kwh
    return tariff.effective_import_rate(tariff.get_cheapest_rate().rate)


def stored_energy_change(
    acc: EnergyAccumulator, soc_pct: float | None, capacity_kwh: float, tariff: TariffConfig
) -> StoredEnergy:
    """The change in stored energy since acc began, nothing without a SoC or a capacity.

    soc_pct is None while the SoC reading is unavailable. A capacity of 0 or less means it
    is unknown. Without the SoC the period began at, there is no change to value yet.
    """
    if soc_pct is None or acc.soc_at_start_pct is None or capacity_kwh <= 0:
        return StoredEnergy()
    change_kwh = (soc_pct - acc.soc_at_start_pct) / 100 * capacity_kwh
    return StoredEnergy(change_kwh, value_per_stored_kwh(acc, tariff))
