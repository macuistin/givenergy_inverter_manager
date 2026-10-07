"""
sensor_values.py — Pure value functions behind the sensor descriptions.

Each function takes a CoordinatorData snapshot (or one of its energy accumulators) and
returns the value a sensor reports. Nothing here imports Home Assistant, so every
rule can be unit tested directly. The sensor_descriptions package holds the description
table and references these functions by name.
"""

from __future__ import annotations

from typing import Any

from .const import (
    BATTERY_FULL_SOC_PCT,
    BATTERY_RATED_CYCLES,
    NIGHT_SURVIVAL_WARNING_MARGIN_PCT,
)
from .core.battery import SurvivalReport, survival_attributes
from .core.engine import CoordinatorData
from .core.tariff import EnergyAccumulator

# Power inside this band either side of zero counts as no flow.
POWER_DIRECTION_BAND_W = 50

GRID_IMPORTING = "Importing"
GRID_EXPORTING = "Exporting"
GRID_BALANCED = "Balanced"

BATTERY_CHARGING = "Charging"
BATTERY_DISCHARGING = "Discharging"
BATTERY_IDLE = "Idle"
BATTERY_FULL = "Full"

NIGHT_CRITICAL = "Critical"
NIGHT_WARNING = "Warning"
NIGHT_SAFE = "Safe"

RATE_NOW = "Now"

YES = "yes"
NO = "no"


def _round_or_none(value: float | None, places: int) -> float | None:
    """Round a value, passing None through."""
    return None if value is None else round(value, places)


def _percentage(part: float, whole: float, places: int) -> float | None:
    """Return part as a percentage of whole, or None when whole is not positive."""
    if whole > 0:
        return round(part / whole * 100, places)
    return None


# ── Power and grid ───────────────────────────────────────────────────────────


def grid_power_direction(data: CoordinatorData) -> str:
    """Say whether the house is importing from, exporting to, or balanced with the grid."""
    if data.grid_power_w > POWER_DIRECTION_BAND_W:
        return GRID_IMPORTING
    if data.grid_power_w < -POWER_DIRECTION_BAND_W:
        return GRID_EXPORTING
    return GRID_BALANCED


def solar_power_pct_of_max(data: CoordinatorData) -> float | None:
    """Return solar output as a percentage of the inverter limit, None without a limit."""
    return _percentage(data.solar_power_w, data.inverter_max_w, 1)


# ── Battery ──────────────────────────────────────────────────────────────────


def battery_power_direction(data: CoordinatorData) -> str:
    """Say whether the battery is charging, discharging or idle, ignoring small flows."""
    if data.battery_power_w > POWER_DIRECTION_BAND_W:
        return BATTERY_CHARGING
    if data.battery_power_w < -POWER_DIRECTION_BAND_W:
        return BATTERY_DISCHARGING
    return BATTERY_IDLE


def battery_state(data: CoordinatorData) -> str:
    """Return Discharging, Full, Charging or Idle. Discharging wins over Full."""
    direction = battery_power_direction(data)
    if direction == BATTERY_DISCHARGING:
        return direction
    if data.battery_soc >= BATTERY_FULL_SOC_PCT:
        return BATTERY_FULL
    return direction


def battery_kwh_available(data: CoordinatorData) -> float | None:
    """Return the energy held in the battery now, None when the capacity is unknown."""
    if data.battery_capacity_kwh > 0:
        return round(data.battery_soc / 100 * data.battery_capacity_kwh, 2)
    return None


def battery_usable_capacity_kwh(data: CoordinatorData) -> float | None:
    """Return the capacity left after wear, None when the capacity is unknown."""
    if data.battery_capacity_kwh > 0:
        remaining_pct = data.battery_stats.estimated_remaining_life_pct
        return round(data.battery_capacity_kwh * remaining_pct / 100, 2)
    return None


def battery_life_consumed_today_pct(data: CoordinatorData) -> float:
    """Return the share of rated battery life used today.

    One rated cycle is a full charge plus a full discharge, so it takes
    2 x capacity of throughput.
    """
    capacity = data.battery_capacity_kwh
    if capacity > 0:
        throughput = data.today.battery_throughput_kwh
        return round(throughput / (2 * capacity * BATTERY_RATED_CYCLES) * 100, 6)
    return 0.0


def battery_cycle_cost_per_kwh(data: CoordinatorData) -> float | None:
    """Return the wear cost of each kWh of battery throughput, None when it is zero."""
    cost = data.battery_cycle_cost_per_kwh
    return round(cost, 5) if cost else None


def battery_years_remaining(data: CoordinatorData) -> float | None:
    """Return the estimated years of battery life left, None until it can be estimated."""
    return _round_or_none(data.battery_years_remaining, 1)


def battery_throughput_budget_pct(data: CoordinatorData) -> float | None:
    """Return the share of the throughput budget used, None when no budget applies."""
    return _round_or_none(data.battery_throughput_budget_pct, 1)


def battery_roundtrip_efficiency_today(data: CoordinatorData) -> float | None:
    """Return today's discharge as a percentage of charge, None before any charging."""
    return _percentage(data.today.battery_discharge_kwh, data.today.battery_charge_kwh, 1)


# ── Tariff ───────────────────────────────────────────────────────────────────


def next_cheap_rate_start(data: CoordinatorData) -> str | None:
    """Return when the next cheap rate starts, "Now" while one is active, else None."""
    if data.next_cheap_rate_start is not None:
        return data.next_cheap_rate_start
    return RATE_NOW if data.hours_to_cheap_rate == 0.0 else None


def average_import_rate(accumulator: EnergyAccumulator) -> float | None:
    """Return the average price paid per imported kWh, None when nothing was imported."""
    if accumulator.import_kwh > 0:
        return round(accumulator.total_import_cost / accumulator.import_kwh, 4)
    return None


def cheap_import_percentage(accumulator: EnergyAccumulator) -> float | None:
    """Return the share of imported energy bought at a cheap rate, None without imports."""
    if accumulator.import_kwh > 0:
        return round(accumulator.cheap_import_fraction * 100, 1)
    return None


# ── Overnight charge and night survival ──────────────────────────────────────


def overnight_charge_cost(data: CoordinatorData) -> float | None:
    """Return the cost of tonight's planned charge, None before the first decision."""
    if data.charge_decision:
        return round(data.charge_decision.cost_to_charge, 3)
    return None


def overnight_charge_window(data: CoordinatorData) -> str | None:
    """Return the charge window to write, for example "02:00 to 06:30", None before a decision."""
    return data.charge_window.text if data.charge_window else None


def overnight_charge_window_attributes(data: CoordinatorData) -> dict[str, Any] | None:
    """Return what the window is sized for, None when there is no window."""
    window = data.charge_window
    if window is None:
        return None
    finish = window.finish_time
    return {
        "window_start": window.start.strftime("%H:%M"),
        "window_end": window.end.strftime("%H:%M"),
        "window_extended": window.extended,
        "expected_kwh": window.expected_kwh,
        "expected_finish": finish.strftime("%H:%M") if finish else None,
    }


def night_survival_confidence(data: CoordinatorData) -> str | None:
    """Return Critical, Warning or Safe for tonight, None before the first cycle.

    Warning means the battery lasts but ends within the warning margin of the minimum SoC.
    """
    if not data.survival_reason:
        return None
    if not data.will_survive_night:
        return NIGHT_CRITICAL
    if data.estimated_soc_at_sunrise < data.battery_min_soc + NIGHT_SURVIVAL_WARNING_MARGIN_PCT:
        return NIGHT_WARNING
    return NIGHT_SAFE


def night_survival_attributes(data: CoordinatorData) -> dict[str, Any] | None:
    """Return the attributes that explain the night survival level, None before a cycle."""
    if not data.survival_reason:
        return None
    return survival_attributes(
        SurvivalReport(
            data.will_survive_night,
            data.estimated_soc_at_sunrise,
            data.battery_min_soc,
            data.battery_soc,
            data.survival_reason,
        )
    )


# ── Inverter and carbon ──────────────────────────────────────────────────────


def inverter_temperature(data: CoordinatorData) -> float | None:
    """Return the inverter temperature in degrees Celsius, None when not configured."""
    return _round_or_none(data.inverter_temperature, 1)


def carbon_intensity(data: CoordinatorData) -> float | None:
    """Return the grid carbon intensity in g CO2/kWh, None when not configured."""
    return _round_or_none(data.carbon_intensity_gco2, 1)


def carbon_intensity_status(data: CoordinatorData) -> str | None:
    """Return the carbon intensity band, None when the intensity is unknown."""
    if data.carbon_intensity_gco2 is not None:
        return data.carbon_intensity_status
    return None


# ── Solar ────────────────────────────────────────────────────────────────────


def solar_capture_efficiency_today(data: CoordinatorData) -> float | None:
    """Return the share of today's solar that was not curtailed, None without solar."""
    captured = max(0.0, data.today.solar_kwh - data.today.missed_solar_kwh)
    return _percentage(captured, data.today.solar_kwh, 1)


def solar_actual_vs_forecast_pct(data: CoordinatorData) -> float | None:
    """Return today's solar as a percentage of the forecast, None without a forecast."""
    return _percentage(data.today.solar_kwh, data.solar_forecast_kwh_today, 1)
