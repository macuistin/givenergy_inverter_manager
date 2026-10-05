"""Keyword-argument adapters over the parameter-object API in core/battery.py and engine.py.

FROZEN_TODAY is the date battery tests run on, so none of them depends on the wall clock.
"""

from __future__ import annotations

from datetime import date

from custom_components.givenergy_inverter_manager.core import battery, engine
from custom_components.givenergy_inverter_manager.core.battery import BatteryStats

FROZEN_TODAY = date(2026, 6, 15)


def update_battery_stats(
    stats: BatteryStats,
    current_soc: float | None,
    last_soc: float | None,
    lifetime_cycles: float | None = None,
    today: date = FROZEN_TODAY,
) -> None:
    engine.update_battery_stats(
        stats, engine.BatteryReading(current_soc, last_soc, lifetime_cycles), today
    )


def estimate_will_survive_night(
    current_soc: float,
    battery_capacity_kwh: float,
    min_soc: float,
    hours_until_solar: float,
    average_hourly_consumption_kwh: float,
) -> tuple[bool, float, str]:
    return battery.estimate_will_survive_night(
        battery.NightEstimateInputs(
            current_soc,
            battery_capacity_kwh,
            min_soc,
            hours_until_solar,
            average_hourly_consumption_kwh,
        )
    )
