"""
sensor.py — Sensor platform for GivEnergy Inverter Manager.

Exposes all calculated and tracked values as Home Assistant sensor entities.
Every sensor reads from the shared GivEnergyCoordinator data snapshot —
no direct polling of GivTCP or any external source.

Sensor categories:
  Power         — solar, battery SoC, grid, house load, rest-of-house load
  Tariff        — current rate (€/kWh) and rate period name
  Energy today  — solar generation, grid import/export, Zappi, immersion (kWh)
  Cost today    — import cost, export earnings, Zappi cost, house cost (€)
  Efficiency    — self-sufficiency %, self-consumption %
  Bill          — accrued bill, projected bill, days remaining in period
  Battery       — cycle count, remaining life %, days since full charge
  Decisions     — overnight charge target %, charge reason, estimated charge cost
  Immersion     — divert reason string
  Night         — estimated SoC at sunrise, survival status string
  Clipping      — inverter clipping status

All sensors use the CoordinatorEntity mixin so they update automatically
whenever the coordinator refreshes, and become unavailable if the coordinator
fails (e.g. GivTCP goes offline).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BATTERY_RATED_CYCLES,
    INTEGRATION_VERSION,
    NIGHT_SURVIVAL_WARNING_MARGIN_PCT,
)
from .coordinator import GivEnergyConfigEntry, GivEnergyCoordinator
from .core.battery import SurvivalReport, survival_attributes
from .core.engine import CoordinatorData
from .core.reporting import (
    build_charge_plan_html,
    build_charge_plan_state,
    build_today_summary_html,
    build_today_summary_state,
    build_week_summary_html,
    build_week_summary_state,
)
from .entity import GivEnergyEntity

# Sentinel for monetary sensors — actual symbol (€, £, $) resolved at runtime.
_CURRENCY_UNIT = "DYNAMIC_CURRENCY"


@dataclass(frozen=True, kw_only=True)
class GivEnergyManagerSensorDescription(SensorEntityDescription):
    """Describes a GivEnergy Manager sensor."""

    value_fn: Callable[[CoordinatorData], Any] = lambda d: None
    available_fn: Callable[[CoordinatorData], bool] = lambda d: True
    entity_category: EntityCategory | None = None
    is_daily_total: bool = False
    reset_period: str | None = None
    entity_registry_enabled_default: bool = True
    html_fn: object = (
        None  # Callable[[CoordinatorData], str] | None  # True → expose last_reset_time for HA LTS
    )
    attrs_fn: object = None  # Callable[[CoordinatorData], dict] | None, extra state attributes


_RESET_FIELDS = {
    "day": "last_reset_time",
    "week": "week_start_time",
    "month": "month_start_time",
    "year": "year_start_time",
}


def reset_period_of(description: GivEnergyManagerSensorDescription) -> str | None:
    """Return "day", "week", "month" or "year" for a sensor that resets, else None."""
    if description.reset_period is not None:
        return description.reset_period
    return "day" if description.is_daily_total else None


SENSOR_DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
    # --- Power sensors ---
    GivEnergyManagerSensorDescription(
        key="solar_power",
        translation_key="solar_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.solar_power_w, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="battery_soc",
        translation_key="battery_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.battery_soc, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="battery_power",
        translation_key="battery_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.battery_power_w, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_power",
        translation_key="immersion_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.immersion_load_w, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="grid_power",
        translation_key="grid_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.grid_power_w, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="house_load",
        translation_key="house_load",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.house_load_w, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="rest_of_house_load",
        translation_key="rest_of_house_load",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.rest_of_house_w, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="grid_power_direction",
        translation_key="grid_power_direction",
        icon="mdi:transmission-tower",
        entity_registry_enabled_default=False,
        value_fn=lambda d: "Importing"
        if d.grid_power_w > 50
        else ("Exporting" if d.grid_power_w < -50 else "Balanced"),
    ),
    GivEnergyManagerSensorDescription(
        key="solar_power_pct_of_max",
        translation_key="solar_power_pct_of_max",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power-variant",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.solar_power_w / d.inverter_max_w * 100, 1)
        if d.inverter_max_w > 0
        else None,
    ),
    GivEnergyManagerSensorDescription(
        key="net_solar_surplus_w",
        translation_key="net_solar_surplus_w",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power-variant",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.net_solar_surplus_w, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="battery_kwh_available",
        translation_key="battery_kwh_available",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.battery_soc / 100 * d.battery_capacity_kwh, 2)
        if d.battery_capacity_kwh > 0
        else None,
    ),
    # --- Current tariff ---
    GivEnergyManagerSensorDescription(
        key="current_rate",
        translation_key="current_rate",
        native_unit_of_measurement=_CURRENCY_UNIT,  # unit resolved dynamically
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.current_rate, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="current_rate_period",
        translation_key="current_rate_period",
        value_fn=lambda d: d.current_rate_name,
    ),
    GivEnergyManagerSensorDescription(
        key="live_grid_cost_rate",
        translation_key="live_grid_cost_rate",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.live_grid_cost_rate,
    ),
    GivEnergyManagerSensorDescription(
        key="next_cheap_rate_start",
        translation_key="next_cheap_rate_start",
        icon="mdi:clock-time-four-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.next_cheap_rate_start
        if d.next_cheap_rate_start is not None
        else ("Now" if d.hours_to_cheap_rate == 0.0 else None),
    ),
    GivEnergyManagerSensorDescription(
        key="hours_to_cheap_rate",
        translation_key="hours_to_cheap_rate",
        native_unit_of_measurement="h",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-countdown-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.hours_to_cheap_rate,
    ),
    GivEnergyManagerSensorDescription(
        key="cheapest_rate",
        translation_key="cheapest_rate",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-minus",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.cheapest_rate, 4) if d.cheapest_rate_name else None,
    ),
    GivEnergyManagerSensorDescription(
        key="cheapest_rate_period",
        translation_key="cheapest_rate_period",
        icon="mdi:clock-time-four-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.cheapest_rate_name if d.cheapest_rate_name else None,
    ),
    GivEnergyManagerSensorDescription(
        key="is_on_cheapest_rate",
        translation_key="is_on_cheapest_rate",
        icon="mdi:cash-check",
        entity_registry_enabled_default=False,
        value_fn=lambda d: "yes" if d.is_on_cheapest_rate else "no",
    ),
    GivEnergyManagerSensorDescription(
        key="is_on_base_rate",
        translation_key="is_on_base_rate",
        icon="mdi:cash",
        entity_registry_enabled_default=False,
        value_fn=lambda d: "yes" if d.is_on_base_rate else "no",
    ),
    GivEnergyManagerSensorDescription(
        key="minutes_remaining_in_period",
        translation_key="minutes_remaining_in_period",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-end",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.minutes_remaining_in_period,
    ),
    GivEnergyManagerSensorDescription(
        key="rate_savings_vs_daytime",
        translation_key="rate_savings_vs_daytime",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-fast",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.rate_savings_vs_daytime, 4),
    ),
    # --- Today energy ---
    GivEnergyManagerSensorDescription(
        key="solar_today",
        is_daily_total=True,
        translation_key="solar_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.solar_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_today",
        is_daily_total=True,
        translation_key="import_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.import_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="export_today",
        is_daily_total=True,
        translation_key="export_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.export_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="zappi_today",
        is_daily_total=True,
        translation_key="zappi_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.zappi_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_today",
        is_daily_total=True,
        translation_key="immersion_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.immersion_kwh, 3),
    ),
    # --- Today costs ---
    GivEnergyManagerSensorDescription(
        key="import_cost_today",
        is_daily_total=True,
        translation_key="import_cost_today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.total_import_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="export_earnings_today",
        is_daily_total=True,
        translation_key="export_earnings_today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.export_earnings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="saving_vs_grid_today",
        is_daily_total=True,
        translation_key="saving_vs_grid_today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.saving_vs_grid_today, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="net_saving_today",
        is_daily_total=True,
        translation_key="net_saving_today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.net_saving_today, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="zappi_cost_today",
        is_daily_total=True,
        translation_key="zappi_cost_today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.zappi_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="house_cost_today",
        is_daily_total=True,
        translation_key="house_cost_today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.house_cost, 4),
    ),
    # --- ROI metrics ---
    GivEnergyManagerSensorDescription(
        key="self_consumed_kwh_today",
        is_daily_total=True,
        translation_key="self_consumed_kwh_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:solar-panel",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(max(0.0, d.today.solar_kwh - d.today.export_kwh), 3),
    ),
    GivEnergyManagerSensorDescription(
        key="net_position_today",
        is_daily_total=True,
        translation_key="net_position_today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:scale-balance",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.today.net_position, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="battery_life_consumed_today",
        is_daily_total=True,
        translation_key="battery_life_consumed_today",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-minus",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(
            d.today.battery_throughput_kwh
            / (2 * d.battery_capacity_kwh * BATTERY_RATED_CYCLES)
            * 100,
            6,
        )
        if d.battery_capacity_kwh > 0
        else 0.0,
    ),
    # --- Self-sufficiency ---
    GivEnergyManagerSensorDescription(
        key="self_sufficiency",
        translation_key="self_sufficiency",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.today.self_sufficiency_pct, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="self_consumption",
        translation_key="self_consumption",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.today.self_consumption_pct, 1),
    ),
    # --- Bill prediction ---
    GivEnergyManagerSensorDescription(
        key="accrued_bill",
        translation_key="accrued_bill",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        reset_period="month",
        value_fn=lambda d: round(d.accrued_bill, 2),
    ),
    GivEnergyManagerSensorDescription(
        key="projected_bill",
        translation_key="projected_bill",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=None,
        value_fn=lambda d: round(d.projected_bill, 2),
    ),
    GivEnergyManagerSensorDescription(
        key="days_remaining_in_period",
        translation_key="days_remaining_in_period",
        native_unit_of_measurement="days",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.days_remaining,
    ),
    # --- Battery health ---
    GivEnergyManagerSensorDescription(
        key="battery_cycles",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_cycles",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.battery_stats.total_cycles, 2),
    ),
    GivEnergyManagerSensorDescription(
        key="register_write_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="register_write_count",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: d.register_write_count,
    ),
    GivEnergyManagerSensorDescription(
        key="battery_cycle_cost_per_kwh",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_cycle_cost_per_kwh",
        native_unit_of_measurement=_CURRENCY_UNIT,
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.battery_cycle_cost_per_kwh, 5)
        if d.battery_cycle_cost_per_kwh
        else None,
    ),
    GivEnergyManagerSensorDescription(
        key="battery_remaining_life",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_remaining_life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.battery_stats.estimated_remaining_life_pct, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="days_since_full_charge",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="days_since_full_charge",
        native_unit_of_measurement="days",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.battery_stats.days_since_full_charge,
    ),
    GivEnergyManagerSensorDescription(
        key="battery_years_remaining",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_years_remaining",
        native_unit_of_measurement="years",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-clock",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.battery_years_remaining, 1)
        if d.battery_years_remaining is not None
        else None,
    ),
    GivEnergyManagerSensorDescription(
        key="battery_usable_capacity_kwh",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_usable_capacity_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-heart-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(
            d.battery_capacity_kwh * d.battery_stats.estimated_remaining_life_pct / 100, 2
        )
        if d.battery_capacity_kwh > 0
        else None,
    ),
    GivEnergyManagerSensorDescription(
        key="battery_state",
        translation_key="battery_state",
        icon="mdi:battery-charging-80",
        entity_registry_enabled_default=False,
        value_fn=lambda d: "Discharging"
        if d.battery_power_w < -50
        else (
            "Full"
            if d.battery_soc >= 99
            else ("Charging" if d.battery_power_w > 50 else "Idle")
        ),
    ),
    # --- Overnight charge decision ---
    GivEnergyManagerSensorDescription(
        key="overnight_charge_target",
        translation_key="overnight_charge_target",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.charge_decision.target_soc if d.charge_decision else None,
    ),
    GivEnergyManagerSensorDescription(
        key="overnight_charge_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="overnight_charge_reason",
        value_fn=lambda d: d.charge_decision.reason if d.charge_decision else None,
    ),
    GivEnergyManagerSensorDescription(
        key="overnight_charge_cost",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="overnight_charge_cost",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=None,
        value_fn=lambda d: (
            round(d.charge_decision.cost_to_charge, 3) if d.charge_decision else None
        ),
    ),
    # --- Immersion divert ---
    GivEnergyManagerSensorDescription(
        key="immersion_divert_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="immersion_divert_reason",
        value_fn=lambda d: d.divert_reason,
    ),
    # --- Night survival ---
    GivEnergyManagerSensorDescription(
        key="estimated_soc_at_sunrise",
        translation_key="estimated_soc_at_sunrise",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.estimated_soc_at_sunrise, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="night_survival_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="night_survival_reason",
        value_fn=lambda d: d.survival_reason,
    ),
    GivEnergyManagerSensorDescription(
        key="night_survival_confidence",
        translation_key="night_survival_confidence",
        icon="mdi:moon-waning-crescent",
        entity_registry_enabled_default=False,
        attrs_fn=lambda d: survival_attributes(
            SurvivalReport(
                d.will_survive_night,
                d.estimated_soc_at_sunrise,
                d.battery_min_soc,
                d.battery_soc,
                d.survival_reason,
            )
        )
        if d.survival_reason
        else None,
        value_fn=lambda d: None
        if not d.survival_reason
        else (
            "Critical"
            if not d.will_survive_night
            else (
                "Warning"
                if d.estimated_soc_at_sunrise
                < d.battery_min_soc + NIGHT_SURVIVAL_WARNING_MARGIN_PCT
                else "Safe"
            )
        ),
    ),
    # --- Clipping ---
    GivEnergyManagerSensorDescription(
        key="is_clipping",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="is_clipping",
        value_fn=lambda d: "clipping" if d.is_clipping else "normal",
    ),
    # --- EV charger ---
    GivEnergyManagerSensorDescription(
        key="ev_charger_state",
        translation_key="ev_charger_state",
        value_fn=lambda d: d.ev_charger_state.value if d.ev_charger_state else None,
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_power",
        translation_key="ev_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.ev_power_w, 1),
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_session_energy",
        translation_key="ev_session_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: round(d.ev_session_kwh, 3),
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_km_charged_today",
        translation_key="ev_km_charged_today",
        native_unit_of_measurement="km",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:car-electric",
        is_daily_total=True,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.ev_km_charged_today,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_cost_per_km_today",
        translation_key="ev_cost_per_km_today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:car-electric",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.ev_cost_per_km_today,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_draining_battery",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="ev_draining_battery",
        value_fn=lambda d: "yes" if d.ev_draining_battery else "no",
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_protection_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="ev_protection_reason",
        value_fn=lambda d: d.ev_protection_reason,
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_charging_source",
        translation_key="ev_charging_source",
        value_fn=lambda d: d.ev_charging_source,
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_solar_surplus_available",
        translation_key="ev_solar_surplus_available",
        value_fn=lambda d: "Available" if d.ev_solar_surplus_available else "Not available",
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_cost_today",
        is_daily_total=True,
        translation_key="immersion_cost_today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.immersion_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="dry_run_active",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="dry_run_active",
        icon="mdi:test-tube",
        value_fn=lambda d: d.dry_run,
    ),
    GivEnergyManagerSensorDescription(
        key="cheap_rate_floor_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="cheap_rate_floor_status",
        icon="mdi:battery-arrow-up",
        value_fn=lambda d: d.cheap_rate_floor_status or "Inactive",
    ),
    GivEnergyManagerSensorDescription(
        key="inverter_temperature",
        translation_key="inverter_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: round(d.inverter_temperature, 1)
        if d.inverter_temperature is not None
        else None,
    ),
    GivEnergyManagerSensorDescription(
        key="inverter_temperature_status",
        translation_key="inverter_temperature_status",
        value_fn=lambda d: d.inverter_temperature_status,
    ),
    GivEnergyManagerSensorDescription(
        key="inverter_derating_today_minutes",
        translation_key="inverter_derating_today_minutes",
        state_class=SensorStateClass.TOTAL,
        is_daily_total=True,
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.today.inverter_derating_minutes, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="carbon_intensity",
        translation_key="carbon_intensity",
        native_unit_of_measurement="g CO2/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:molecule-co2",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.carbon_intensity_gco2, 1)
        if d.carbon_intensity_gco2 is not None
        else None,
    ),
    GivEnergyManagerSensorDescription(
        key="carbon_intensity_status",
        translation_key="carbon_intensity_status",
        icon="mdi:leaf",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.carbon_intensity_status
        if d.carbon_intensity_gco2 is not None
        else None,
    ),
    GivEnergyManagerSensorDescription(
        key="dry_run_last_skipped",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="dry_run_last_skipped",
        icon="mdi:skip-next-circle-outline",
        value_fn=lambda d: d.dry_run_last_skipped or "No actions skipped yet",
    ),
    # ── Today — rate-tier breakdown and savings ───────────────────────────────
    GivEnergyManagerSensorDescription(
        key="import_kwh_cheap_today",
        translation_key="import_kwh_cheap_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:lightning-bolt-circle",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.import_kwh_cheap, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_kwh_peak_today",
        translation_key="import_kwh_peak_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:lightning-bolt",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.import_kwh_peak, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_cost_cheap_today",
        translation_key="import_cost_cheap_today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash-minus",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.import_cost_cheap, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="import_cost_peak_today",
        translation_key="import_cost_peak_today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.import_cost_peak, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="peak_import_fraction_today",
        translation_key="peak_import_fraction_today",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-pie",
        value_fn=lambda d: round(d.today.peak_import_fraction * 100, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="avg_import_rate_today",
        translation_key="avg_import_rate_today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-clock",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.today.total_import_cost / d.today.import_kwh, 4)
        if d.today.import_kwh > 0
        else None,
    ),
    GivEnergyManagerSensorDescription(
        key="avg_import_rate_this_week",
        translation_key="avg_import_rate_this_week",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-clock",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.week.total_import_cost / d.week.import_kwh, 4)
        if d.week.import_kwh > 0
        else None,
    ),
    GivEnergyManagerSensorDescription(
        key="avg_import_rate_this_month",
        translation_key="avg_import_rate_this_month",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-clock",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.month.total_import_cost / d.month.import_kwh, 4)
        if d.month.import_kwh > 0
        else None,
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_savings_today",
        translation_key="immersion_savings_today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:water-boiler",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.immersion_savings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_solar_kwh_today",
        translation_key="immersion_solar_kwh_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:water-boiler-auto",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.immersion_solar_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="battery_throughput_kwh_today",
        translation_key="battery_throughput_kwh_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-sync",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.battery_throughput_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="battery_throughput_budget_pct",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_throughput_budget_pct",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-sync",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.battery_throughput_budget_pct, 1)
        if d.battery_throughput_budget_pct is not None
        else None,
    ),
    GivEnergyManagerSensorDescription(
        key="battery_throughput_budget_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_throughput_budget_status",
        icon="mdi:battery-heart-variant",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.battery_throughput_budget_status or None,
    ),
    GivEnergyManagerSensorDescription(
        key="battery_charge_kwh_today",
        translation_key="battery_charge_kwh_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-arrow-up",
        is_daily_total=True,
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.today.battery_charge_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="battery_discharge_kwh_today",
        translation_key="battery_discharge_kwh_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-arrow-down-outline",
        is_daily_total=True,
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.today.battery_discharge_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="house_kwh_today",
        translation_key="house_kwh_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:home-lightning-bolt",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.house_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="missed_solar_today",
        translation_key="missed_solar_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        is_daily_total=True,
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.today.missed_solar_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="solar_capture_efficiency_today",
        translation_key="solar_capture_efficiency_today",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power-variant",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(
            max(0.0, d.today.solar_kwh - d.today.missed_solar_kwh) / d.today.solar_kwh * 100, 1
        )
        if d.today.solar_kwh > 0
        else None,
    ),
    # ── Solar forecast and accuracy ───────────────────────────────────────────
    GivEnergyManagerSensorDescription(
        key="solar_forecast_kwh_today",
        translation_key="solar_forecast_kwh_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=None,
        icon="mdi:weather-sunny-alert",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.solar_forecast_kwh_today, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="solar_actual_vs_forecast_pct",
        translation_key="solar_actual_vs_forecast_pct",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-sunny-alert",
        entity_registry_enabled_default=True,
        value_fn=lambda d: (
            round(d.today.solar_kwh / d.solar_forecast_kwh_today * 100, 1)
            if d.solar_forecast_kwh_today > 0
            else None
        ),
    ),
    GivEnergyManagerSensorDescription(
        key="yesterday_forecast_accuracy_pct",
        translation_key="yesterday_forecast_accuracy_pct",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-timeline-variant-shimmer",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.yesterday_forecast_accuracy_pct, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="forecast_accuracy_7day_avg_pct",
        translation_key="forecast_accuracy_7day_avg_pct",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-bell-curve-cumulative",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.forecast_accuracy_7day_avg_pct, 1),
    ),
    # ── Yesterday comparisons (disabled by default) ───────────────────────────
    GivEnergyManagerSensorDescription(
        key="solar_yesterday",
        translation_key="solar_yesterday",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=None,
        icon="mdi:solar-power",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.solar_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_yesterday",
        translation_key="import_yesterday",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=None,
        icon="mdi:transmission-tower-import",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.import_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="export_yesterday",
        translation_key="export_yesterday",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=None,
        icon="mdi:transmission-tower-export",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.export_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_cost_yesterday",
        translation_key="import_cost_yesterday",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=None,
        icon="mdi:cash-minus",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.total_import_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="import_kwh_cheap_yesterday",
        translation_key="import_kwh_cheap_yesterday",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=None,
        icon="mdi:lightning-bolt-circle",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.import_kwh_cheap, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_kwh_peak_yesterday",
        translation_key="import_kwh_peak_yesterday",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=None,
        icon="mdi:lightning-bolt",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.import_kwh_peak, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_savings_yesterday",
        translation_key="immersion_savings_yesterday",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=None,
        icon="mdi:water-boiler",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.immersion_savings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="self_sufficiency_yesterday",
        translation_key="self_sufficiency_yesterday",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-battery",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.self_sufficiency_pct, 1),
    ),
    # ── Weekly accumulations (disabled by default) ────────────────────────────
    GivEnergyManagerSensorDescription(
        key="solar_this_week",
        translation_key="solar_this_week",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        reset_period="week",
        icon="mdi:solar-power",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.solar_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_this_week",
        translation_key="import_this_week",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        reset_period="week",
        icon="mdi:transmission-tower-import",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.import_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="export_this_week",
        translation_key="export_this_week",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        reset_period="week",
        icon="mdi:transmission-tower-export",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.export_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_cost_this_week",
        translation_key="import_cost_this_week",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        reset_period="week",
        icon="mdi:cash-minus",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.total_import_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="export_earnings_this_week",
        translation_key="export_earnings_this_week",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        reset_period="week",
        icon="mdi:cash-plus",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.export_earnings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="import_kwh_cheap_this_week",
        translation_key="import_kwh_cheap_this_week",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        reset_period="week",
        icon="mdi:lightning-bolt-circle",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.import_kwh_cheap, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_kwh_peak_this_week",
        translation_key="import_kwh_peak_this_week",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        reset_period="week",
        icon="mdi:lightning-bolt",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.import_kwh_peak, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_savings_this_week",
        translation_key="immersion_savings_this_week",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        reset_period="week",
        icon="mdi:water-boiler",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.immersion_savings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="self_sufficiency_this_week",
        translation_key="self_sufficiency_this_week",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-battery",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.self_sufficiency_pct, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="cheap_import_fraction_this_week",
        translation_key="cheap_import_fraction_this_week",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-pie",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.week.cheap_import_fraction * 100, 1)
        if d.week.import_kwh > 0
        else None,
    ),
    # ── Monthly accumulations (disabled by default) ───────────────────────────
    GivEnergyManagerSensorDescription(
        key="solar_this_month",
        translation_key="solar_this_month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        reset_period="month",
        icon="mdi:solar-power",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.solar_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_this_month",
        translation_key="import_this_month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        reset_period="month",
        icon="mdi:transmission-tower-import",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.import_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="export_this_month",
        translation_key="export_this_month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        reset_period="month",
        icon="mdi:transmission-tower-export",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.export_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_cost_this_month",
        translation_key="import_cost_this_month",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        reset_period="month",
        icon="mdi:cash-minus",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.total_import_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="export_earnings_this_month",
        translation_key="export_earnings_this_month",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        reset_period="month",
        icon="mdi:cash-plus",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.export_earnings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="export_this_year",
        translation_key="export_this_year",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        reset_period="year",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.year.export_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="export_earnings_this_year",
        translation_key="export_earnings_this_year",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        reset_period="year",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.year.export_earnings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="export_trailing_12m",
        translation_key="export_trailing_12m",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=None,
        icon="mdi:transmission-tower-export",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.trailing_12m_export_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="solar_this_year",
        translation_key="solar_this_year",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        reset_period="year",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.year.solar_kwh, 3),
    ),
    # --- Trailing 12-month sensors (complete billing month history) ---
    GivEnergyManagerSensorDescription(
        key="solar_trailing_12m",
        translation_key="solar_trailing_12m",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=None,
        icon="mdi:solar-power",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.trailing_12m_solar_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_trailing_12m",
        translation_key="import_trailing_12m",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=None,
        icon="mdi:transmission-tower-import",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.trailing_12m_import_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_cost_trailing_12m",
        translation_key="import_cost_trailing_12m",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=None,
        icon="mdi:cash-minus",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.trailing_12m_import_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="export_earnings_trailing_12m",
        translation_key="export_earnings_trailing_12m",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=None,
        icon="mdi:cash-plus",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.trailing_12m_export_earnings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="import_kwh_cheap_this_month",
        translation_key="import_kwh_cheap_this_month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        reset_period="month",
        icon="mdi:lightning-bolt-circle",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.import_kwh_cheap, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_kwh_peak_this_month",
        translation_key="import_kwh_peak_this_month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        reset_period="month",
        icon="mdi:lightning-bolt",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.import_kwh_peak, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_savings_this_month",
        translation_key="immersion_savings_this_month",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        reset_period="month",
        icon="mdi:water-boiler",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.immersion_savings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="self_sufficiency_this_month",
        translation_key="self_sufficiency_this_month",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-battery",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.self_sufficiency_pct, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="cheap_import_fraction_this_month",
        translation_key="cheap_import_fraction_this_month",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-pie",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.month.cheap_import_fraction * 100, 1)
        if d.month.import_kwh > 0
        else None,
    ),
    GivEnergyManagerSensorDescription(
        key="battery_roundtrip_efficiency_today",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_roundtrip_efficiency_today",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-sync",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(
            d.today.battery_discharge_kwh / d.today.battery_charge_kwh * 100, 1
        )
        if d.today.battery_charge_kwh > 0
        else None,
    ),
    GivEnergyManagerSensorDescription(
        key="net_position_this_month",
        translation_key="net_position_this_month",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        reset_period="month",
        icon="mdi:scale-balance",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.month.net_position, 4),
    ),
    # ── HTML report sensors (disabled by default) ─────────────────────────────
    GivEnergyManagerSensorDescription(
        key="today_summary",
        translation_key="today_summary",
        icon="mdi:newspaper-variant-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: build_today_summary_state(d),
        html_fn=build_today_summary_html,
    ),
    GivEnergyManagerSensorDescription(
        key="charge_plan",
        translation_key="charge_plan",
        icon="mdi:battery-clock-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: build_charge_plan_state(d),
        html_fn=build_charge_plan_html,
    ),
    GivEnergyManagerSensorDescription(
        key="week_summary",
        translation_key="week_summary",
        icon="mdi:calendar-week-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: build_week_summary_state(d),
        html_fn=build_week_summary_html,
    ),
    GivEnergyManagerSensorDescription(
        key="pre_boost_export_recommended",
        translation_key="pre_boost_export_recommended",
        icon="mdi:transmission-tower-export",
        entity_registry_enabled_default=False,
        value_fn=lambda d: "yes" if d.pre_boost_export_recommended else "no",
    ),
    GivEnergyManagerSensorDescription(
        key="pre_boost_export_kwh",
        translation_key="pre_boost_export_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        icon="mdi:battery-arrow-up",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.pre_boost_export_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="pre_boost_export_net_gain",
        translation_key="pre_boost_export_net_gain",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        icon="mdi:cash-plus",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.pre_boost_export_net_gain, 4),
    ),
    # --- Miscellaneous ---
    GivEnergyManagerSensorDescription(
        key="battery_power_direction",
        translation_key="battery_power_direction",
        icon="mdi:battery-charging",
        entity_registry_enabled_default=False,
        value_fn=lambda d: "Charging"
        if d.battery_power_w > 50
        else ("Discharging" if d.battery_power_w < -50 else "Idle"),
    ),
    GivEnergyManagerSensorDescription(
        key="integration_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="integration_version",
        icon="mdi:information-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: INTEGRATION_VERSION,
    ),
    GivEnergyManagerSensorDescription(
        key="days_in_period",
        translation_key="days_in_period",
        native_unit_of_measurement="days",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:calendar-start",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.days_in_period,
    ),
)

_LOG = logging.getLogger(__name__)


# Coordinator-driven — no parallel updates needed
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GivEnergyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GivEnergy Manager sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        GivEnergyManagerSensor(coordinator, description) for description in SENSOR_DESCRIPTIONS
    )


class GivEnergyManagerSensor(GivEnergyEntity, SensorEntity):
    """A sensor entity for GivEnergy Inverter Manager."""

    entity_description: GivEnergyManagerSensorDescription
    _unrecorded_attributes = frozenset({"html"})

    def __init__(
        self,
        coordinator: GivEnergyCoordinator,
        description: GivEnergyManagerSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        if description.entity_category is not None:
            self._attr_entity_category = description.entity_category
        self._reset_period = reset_period_of(description)
        self._attr_entity_registry_enabled_default = description.entity_registry_enabled_default

    @property
    def native_unit_of_measurement(self) -> str | None:
        """
        Return the unit of measurement.

        For monetary sensors the unit is the configured currency symbol,
        read from coordinator data so it updates when the user changes
        their currency in the options flow without restarting HA.
        """
        declared = self.entity_description.native_unit_of_measurement
        if declared == _CURRENCY_UNIT:
            if self.coordinator.data is not None:
                return self.coordinator.data.currency_symbol
            return "€"  # safe fallback before first update
        return declared

    @property
    def last_reset(self):
        """Return when the sensor's accumulation period started (enables HA long-term stats)."""
        if self._reset_period is None:
            return None
        if self.entity_description.state_class != SensorStateClass.TOTAL:
            return None
        data = self.coordinator.data
        if not data:
            return None
        iso = getattr(data, _RESET_FIELDS[self._reset_period], "")
        if not iso:
            return None
        from datetime import datetime, timezone

        try:
            dt = datetime.fromisoformat(iso)
            # Stored as local timezone since coordinator fix; old UTC values
            # have no tzinfo so fall back to UTC for backwards compatibility.
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError, AttributeError):
            return None

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return the html attribute of report sensors and any attributes that explain the state."""
        description = self.entity_description
        data = self.coordinator.data
        if data is None:
            return None
        attrs: dict = {}
        if description.html_fn is not None:
            attrs["html"] = description.html_fn(data)
        if description.attrs_fn is not None:
            attrs.update(description.attrs_fn(data) or {})
        return attrs or None

    @property
    def native_value(self):
        """Return sensor value from coordinator data."""
        if self.coordinator.data is None:
            return None
        try:
            return self.entity_description.value_fn(self.coordinator.data)
        except Exception as exc:  # noqa: BLE001
            _LOG.debug("Sensor %s value_fn raised: %s", self.entity_description.key, exc)
            return None

    @property
    def available(self) -> bool:
        """Return True if coordinator has data and the entity is applicable."""
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return False
        return self.entity_description.available_fn(self.coordinator.data)
