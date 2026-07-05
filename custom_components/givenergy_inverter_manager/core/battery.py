"""
battery.py — Battery health, cycle tracking, and night-survival estimation.

Provides:
  BatteryStats        — aggregated lifetime stats: cycle count, charge history,
                        last full-charge date, estimated remaining life, and
                        projected years remaining based on average daily usage.
                        Rated cycles default to BATTERY_RATED_CYCLES (const.py).

  calculate_cycle_increment()
    Converts an SoC delta (%) into a fractional cycle count. A 100% swing
    equals 1.0 cycle; partial swings are proportional.

  estimate_will_survive_night()
    Predicts whether the battery will last until solar generation starts
    tomorrow morning, given current SoC, capacity, minimum SoC floor,
    average hourly consumption, and hours until sunrise.

Note: BatterySession tracking (per-session energy, depth-of-discharge,
round-trip efficiency) is planned for v0.2.0 when energy accumulation is
persisted across HA restarts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# GivEnergy battery typical rated cycles
from ..const import BATTERY_RATED_CYCLES as TYPICAL_RATED_CYCLES


@dataclass
class BatteryStats:
    """Aggregated battery statistics."""
    total_cycles: float = 0.0
    last_full_charge_date: date | None = None

    @property
    def estimated_remaining_life_pct(self) -> float:
        """Estimate remaining battery life as percentage of rated cycles."""
        return max(0.0, (1 - self.total_cycles / TYPICAL_RATED_CYCLES) * 100)

    @property
    def days_since_full_charge(self) -> int | None:
        if self.last_full_charge_date is None:
            return None
        return (date.today() - self.last_full_charge_date).days

    @property
    def average_daily_cycles(self) -> float:
        """
        Average cycles per day.

        Currently returns 0.0 — daily cycle history is not yet persisted
        across HA restarts (planned for v0.2.0). When persistence lands,
        this will be derived from the stored rolling cycle log.
        """
        return 0.0

    @property
    def estimated_years_remaining(self) -> float:
        """Estimated years of life remaining based on average daily cycle rate."""
        if self.average_daily_cycles == 0:
            return 0.0
        remaining_cycles = TYPICAL_RATED_CYCLES - self.total_cycles
        return remaining_cycles / (self.average_daily_cycles * 365)


def calculate_cycle_increment(soc_delta: float) -> float:
    """
    Calculate the cycle increment for a given SoC change.

    A full 100% discharge = 1.0 cycle; a 50% discharge = 0.5 cycles.
    Sign is ignored — charging and discharging both count toward wear.
    """
    return abs(soc_delta) / 100.0



def estimate_will_survive_night(
    current_soc: float,
    battery_capacity_kwh: float,
    min_soc: float,
    hours_until_solar: float,
    average_hourly_consumption_kwh: float,
) -> tuple[bool, float, str]:
    """
    Estimate whether the battery will last until solar starts tomorrow.

    Returns (will_survive, estimated_soc_at_sunrise, reason)
    """
    usable_kwh = battery_capacity_kwh * ((current_soc - min_soc) / 100)
    expected_consumption = hours_until_solar * average_hourly_consumption_kwh
    remaining_kwh = usable_kwh - expected_consumption
    remaining_soc = (remaining_kwh / battery_capacity_kwh * 100) + min_soc

    if remaining_kwh >= 0:
        return (
            True,
            max(min_soc, remaining_soc),
            f"Battery should last until solar. Estimated SoC at sunrise: {remaining_soc:.0f}%"
        )
    shortfall_kwh = abs(remaining_kwh)
    return (
        False,
        min_soc,
        f"Battery may run low. Estimated shortfall: {shortfall_kwh:.1f}kWh before solar starts."
    )
