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
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import GivEnergyCoordinator
from .core.engine import CoordinatorData
from .core.reporting import (
    build_charge_plan_html,
    build_charge_plan_state,
    build_today_summary_html,
    build_today_summary_state,
    build_week_summary_html,
    build_week_summary_state,
)

# Sentinel for monetary sensors — actual symbol (€, £, $) resolved at runtime.
_CURRENCY_UNIT = "DYNAMIC_CURRENCY"


@dataclass(frozen=True, kw_only=True)
class GivEnergyManagerSensorDescription(SensorEntityDescription):
    """Describes a GivEnergy Manager sensor."""

    value_fn: Callable[[CoordinatorData], Any] = lambda d: None
    available_fn: Callable[[CoordinatorData], bool] = lambda d: True
    entity_category: EntityCategory | None = None
    is_daily_total: bool = False
    entity_registry_enabled_default: bool = True
    html_fn: object = (
        None  # Callable[[CoordinatorData], str] | None  # True → expose last_reset_time for HA LTS
    )


SENSOR_DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
    # --- Power sensors ---
    GivEnergyManagerSensorDescription(
        key="solar_power",
        translation_key="solar_power",
        name="Solar Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.solar_power_w, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="battery_soc",
        translation_key="battery_soc",
        name="Battery State of Charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.battery_soc, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="battery_power",
        translation_key="battery_power",
        name="Battery Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.battery_power_w, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_power",
        translation_key="immersion_power",
        name="Immersion Heater Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.immersion_load_w, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="grid_power",
        translation_key="grid_power",
        name="Grid Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.grid_power_w, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="house_load",
        translation_key="house_load",
        name="House Load",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.house_load_w, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="rest_of_house_load",
        translation_key="rest_of_house_load",
        name="Rest of House Load",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.rest_of_house_w, 1),
    ),
    # --- Current tariff ---
    GivEnergyManagerSensorDescription(
        key="current_rate",
        translation_key="current_rate",
        name="Current Rate",
        native_unit_of_measurement=_CURRENCY_UNIT,  # unit resolved dynamically
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.current_rate, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="current_rate_period",
        translation_key="current_rate_period",
        name="Current Rate Period",
        value_fn=lambda d: d.current_rate_name,
    ),
    GivEnergyManagerSensorDescription(
        key="live_grid_cost_rate",
        translation_key="live_grid_cost_rate",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.live_grid_cost_rate,
    ),
    # --- Today energy ---
    GivEnergyManagerSensorDescription(
        key="solar_today",
        is_daily_total=True,
        translation_key="solar_today",
        name="Solar Generation Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.solar_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_today",
        is_daily_total=True,
        translation_key="import_today",
        name="Grid Import Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.import_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="export_today",
        is_daily_total=True,
        translation_key="export_today",
        name="Grid Export Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.export_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="zappi_today",
        is_daily_total=True,
        translation_key="zappi_today",
        name="EV Charging Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.zappi_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_today",
        is_daily_total=True,
        translation_key="immersion_today",
        name="Immersion Heater Today",
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
        name="Import Cost Today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.total_import_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="export_earnings_today",
        is_daily_total=True,
        translation_key="export_earnings_today",
        name="Export Earnings Today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.export_earnings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="saving_vs_grid_today",
        is_daily_total=True,
        translation_key="saving_vs_grid_today",
        name="Saving vs Grid Today",
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
        name="Net Saving Today (inc. battery wear)",
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
        name="EV Charging Cost Today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.zappi_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="house_cost_today",
        is_daily_total=True,
        translation_key="house_cost_today",
        name="House Cost Today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.house_cost, 4),
    ),
    # --- Self-sufficiency ---
    GivEnergyManagerSensorDescription(
        key="self_sufficiency",
        translation_key="self_sufficiency",
        name="Self Sufficiency",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.today.self_sufficiency_pct, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="self_consumption",
        translation_key="self_consumption",
        name="Self Consumption",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.today.self_consumption_pct, 1),
    ),
    # --- Bill prediction ---
    GivEnergyManagerSensorDescription(
        key="accrued_bill",
        translation_key="accrued_bill",
        name="Accrued Bill This Period",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.accrued_bill, 2),
    ),
    GivEnergyManagerSensorDescription(
        key="projected_bill",
        translation_key="projected_bill",
        name="Projected Bill This Period",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=None,
        value_fn=lambda d: round(d.projected_bill, 2),
    ),
    GivEnergyManagerSensorDescription(
        key="days_remaining_in_period",
        translation_key="days_remaining_in_period",
        name="Days Remaining in Bill Period",
        native_unit_of_measurement="days",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.days_remaining,
    ),
    # --- Battery health ---
    GivEnergyManagerSensorDescription(
        key="battery_cycles",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_cycles",
        name="Battery Total Cycles",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.battery_stats.total_cycles, 2),
    ),
    GivEnergyManagerSensorDescription(
        key="register_write_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="register_write_count",
        name="GivTCP Register Write Count",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: d.register_write_count,
    ),
    GivEnergyManagerSensorDescription(
        key="battery_cycle_cost_per_kwh",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="battery_cycle_cost_per_kwh",
        name="Battery Cycle Cost per kWh",
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
        name="Battery Remaining Life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.battery_stats.estimated_remaining_life_pct, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="days_since_full_charge",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="days_since_full_charge",
        name="Days Since Full Charge",
        native_unit_of_measurement="days",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.battery_stats.days_since_full_charge,
    ),
    # --- Overnight charge decision ---
    GivEnergyManagerSensorDescription(
        key="overnight_charge_target",
        translation_key="overnight_charge_target",
        name="Recommended Overnight Charge Target",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.charge_decision.target_soc if d.charge_decision else None,
    ),
    GivEnergyManagerSensorDescription(
        key="overnight_charge_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="overnight_charge_reason",
        name="Overnight Charge Reason",
        value_fn=lambda d: d.charge_decision.reason if d.charge_decision else None,
    ),
    GivEnergyManagerSensorDescription(
        key="overnight_charge_cost",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="overnight_charge_cost",
        name="Estimated Overnight Charge Cost",
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
        name="Immersion Divert Reason",
        value_fn=lambda d: d.divert_reason,
    ),
    # --- Night survival ---
    GivEnergyManagerSensorDescription(
        key="estimated_soc_at_sunrise",
        translation_key="estimated_soc_at_sunrise",
        name="Estimated SoC at Sunrise",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.estimated_soc_at_sunrise, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="night_survival_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="night_survival_reason",
        name="Battery Night Survival Status",
        value_fn=lambda d: d.survival_reason,
    ),
    # --- Clipping ---
    GivEnergyManagerSensorDescription(
        key="is_clipping",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="is_clipping",
        name="Inverter Clipping",
        value_fn=lambda d: "clipping" if d.is_clipping else "normal",
    ),
    # --- EV charger ---
    GivEnergyManagerSensorDescription(
        key="ev_charger_state",
        translation_key="ev_charger_state",
        name="EV Charger State",
        value_fn=lambda d: d.ev_charger_state.value if d.ev_charger_state else None,
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_power",
        translation_key="ev_power",
        name="EV Charging Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.ev_power_w, 1),
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_session_energy",
        translation_key="ev_session_energy",
        name="EV Session Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.ev_session_kwh, 3),
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_draining_battery",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="ev_draining_battery",
        name="EV Draining Battery",
        value_fn=lambda d: "yes" if d.ev_draining_battery else "no",
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_protection_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="ev_protection_reason",
        name="EV Battery Protection Status",
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
        name="Immersion Cost Today",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.immersion_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="dry_run_active",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="dry_run_active",
        name="Dry Run Mode Active",
        icon="mdi:test-tube",
        value_fn=lambda d: d.dry_run,
    ),
    GivEnergyManagerSensorDescription(
        key="cheap_rate_floor_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="cheap_rate_floor_status",
        name="Cheap Rate Floor",
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
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_daily_total=True,
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.today.inverter_derating_minutes, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="dry_run_last_skipped",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="dry_run_last_skipped",
        name="Last Skipped Action (Dry Run)",
        icon="mdi:skip-next-circle-outline",
        value_fn=lambda d: d.dry_run_last_skipped or "No actions skipped yet",
    ),
    # ── Today — rate-tier breakdown and savings ───────────────────────────────
    GivEnergyManagerSensorDescription(
        key="import_kwh_cheap_today",
        translation_key="import_kwh_cheap_today",
        name="Import at cheap rate",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:lightning-bolt-circle",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.import_kwh_cheap, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_kwh_peak_today",
        translation_key="import_kwh_peak_today",
        name="Import at peak rate",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:lightning-bolt",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.import_kwh_peak, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_cost_cheap_today",
        translation_key="import_cost_cheap_today",
        name="Import cost at cheap rate",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:cash-minus",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.import_cost_cheap, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="import_cost_peak_today",
        translation_key="import_cost_peak_today",
        name="Import cost at peak rate",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:cash",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.import_cost_peak, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="peak_import_fraction_today",
        translation_key="peak_import_fraction_today",
        name="Peak rate import fraction",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-pie",
        value_fn=lambda d: round(d.today.peak_import_fraction * 100, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_savings_today",
        translation_key="immersion_savings_today",
        name="Immersion solar savings",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:water-boiler",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.immersion_savings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_solar_kwh_today",
        translation_key="immersion_solar_kwh_today",
        name="Immersion solar diverted",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:water-boiler-auto",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.immersion_solar_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="battery_throughput_kwh_today",
        translation_key="battery_throughput_kwh_today",
        name="Battery throughput",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-sync",
        is_daily_total=True,
        value_fn=lambda d: round(d.today.battery_throughput_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="missed_solar_today",
        translation_key="missed_solar_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        is_daily_total=True,
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.today.missed_solar_kwh, 3),
    ),
    # ── Solar forecast and accuracy ───────────────────────────────────────────
    GivEnergyManagerSensorDescription(
        key="solar_forecast_kwh_today",
        translation_key="solar_forecast_kwh_today",
        name="Solar forecast today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:weather-sunny-alert",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.solar_forecast_kwh_today, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="solar_actual_vs_forecast_pct",
        translation_key="solar_actual_vs_forecast_pct",
        name="Solar actual vs forecast",
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
        name="Forecast accuracy yesterday",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-timeline-variant-shimmer",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.yesterday_forecast_accuracy_pct, 1),
    ),
    GivEnergyManagerSensorDescription(
        key="forecast_accuracy_7day_avg_pct",
        translation_key="forecast_accuracy_7day_avg_pct",
        name="Forecast accuracy 7-day average",
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
        name="Solar generated yesterday",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:solar-power",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.solar_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_yesterday",
        translation_key="import_yesterday",
        name="Grid import yesterday",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:transmission-tower-import",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.import_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="export_yesterday",
        translation_key="export_yesterday",
        name="Grid export yesterday",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:transmission-tower-export",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.export_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_cost_yesterday",
        translation_key="import_cost_yesterday",
        name="Import cost yesterday",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash-minus",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.total_import_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="import_kwh_cheap_yesterday",
        translation_key="import_kwh_cheap_yesterday",
        name="Import at cheap rate yesterday",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:lightning-bolt-circle",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.import_kwh_cheap, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_kwh_peak_yesterday",
        translation_key="import_kwh_peak_yesterday",
        name="Import at peak rate yesterday",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:lightning-bolt",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.import_kwh_peak, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_savings_yesterday",
        translation_key="immersion_savings_yesterday",
        name="Immersion savings yesterday",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:water-boiler",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.yesterday.immersion_savings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="self_sufficiency_yesterday",
        translation_key="self_sufficiency_yesterday",
        name="Self-sufficiency yesterday",
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
        name="Solar generated this week",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:solar-power",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.solar_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_this_week",
        translation_key="import_this_week",
        name="Grid import this week",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:transmission-tower-import",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.import_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="export_this_week",
        translation_key="export_this_week",
        name="Grid export this week",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:transmission-tower-export",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.export_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_cost_this_week",
        translation_key="import_cost_this_week",
        name="Import cost this week",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash-minus",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.total_import_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="export_earnings_this_week",
        translation_key="export_earnings_this_week",
        name="Export earnings this week",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash-plus",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.export_earnings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="import_kwh_cheap_this_week",
        translation_key="import_kwh_cheap_this_week",
        name="Import at cheap rate this week",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:lightning-bolt-circle",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.import_kwh_cheap, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_kwh_peak_this_week",
        translation_key="import_kwh_peak_this_week",
        name="Import at peak rate this week",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:lightning-bolt",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.import_kwh_peak, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_savings_this_week",
        translation_key="immersion_savings_this_week",
        name="Immersion savings this week",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:water-boiler",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.immersion_savings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="self_sufficiency_this_week",
        translation_key="self_sufficiency_this_week",
        name="Self-sufficiency this week",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-battery",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.week.self_sufficiency_pct, 1),
    ),
    # ── Monthly accumulations (disabled by default) ───────────────────────────
    GivEnergyManagerSensorDescription(
        key="solar_this_month",
        translation_key="solar_this_month",
        name="Solar generated this month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:solar-power",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.solar_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_this_month",
        translation_key="import_this_month",
        name="Grid import this month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:transmission-tower-import",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.import_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="export_this_month",
        translation_key="export_this_month",
        name="Grid export this month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:transmission-tower-export",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.export_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_cost_this_month",
        translation_key="import_cost_this_month",
        name="Import cost this month",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash-minus",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.total_import_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="export_earnings_this_month",
        translation_key="export_earnings_this_month",
        name="Export earnings this month",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
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
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.year.export_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="export_earnings_this_year",
        translation_key="export_earnings_this_year",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.year.export_earnings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="export_trailing_12m",
        translation_key="export_trailing_12m",
        name="Export — trailing 12 months",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
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
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.year.solar_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_kwh_cheap_this_month",
        translation_key="import_kwh_cheap_this_month",
        name="Import at cheap rate this month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:lightning-bolt-circle",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.import_kwh_cheap, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="import_kwh_peak_this_month",
        translation_key="import_kwh_peak_this_month",
        name="Import at peak rate this month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:lightning-bolt",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.import_kwh_peak, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_savings_this_month",
        translation_key="immersion_savings_this_month",
        name="Immersion savings this month",
        native_unit_of_measurement=_CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:water-boiler",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.immersion_savings, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="self_sufficiency_this_month",
        translation_key="self_sufficiency_this_month",
        name="Self-sufficiency this month",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-battery",
        entity_registry_enabled_default=True,
        value_fn=lambda d: round(d.month.self_sufficiency_pct, 1),
    ),
    # ── HTML report sensors (disabled by default) ─────────────────────────────
    GivEnergyManagerSensorDescription(
        key="today_summary",
        translation_key="today_summary",
        name="Today's energy summary",
        icon="mdi:newspaper-variant-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: build_today_summary_state(d),
        html_fn=build_today_summary_html,
    ),
    GivEnergyManagerSensorDescription(
        key="charge_plan",
        translation_key="charge_plan",
        name="Tonight's charge plan",
        icon="mdi:battery-clock-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: build_charge_plan_state(d),
        html_fn=build_charge_plan_html,
    ),
    GivEnergyManagerSensorDescription(
        key="week_summary",
        translation_key="week_summary",
        name="This week's energy summary",
        icon="mdi:calendar-week-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda d: build_week_summary_state(d),
        html_fn=build_week_summary_html,
    ),
    GivEnergyManagerSensorDescription(
        key="pre_boost_export_recommended",
        translation_key="pre_boost_export_recommended",
        name="Pre-boost export recommended",
        icon="mdi:transmission-tower-export",
        entity_registry_enabled_default=False,
        value_fn=lambda d: "yes" if d.pre_boost_export_recommended else "no",
    ),
    GivEnergyManagerSensorDescription(
        key="pre_boost_export_kwh",
        translation_key="pre_boost_export_kwh",
        name="Pre-boost exportable kWh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-arrow-up",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.pre_boost_export_kwh, 3),
    ),
    GivEnergyManagerSensorDescription(
        key="pre_boost_export_net_gain",
        translation_key="pre_boost_export_net_gain",
        name="Pre-boost export net gain",
        native_unit_of_measurement=_CURRENCY_UNIT,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-plus",
        entity_registry_enabled_default=False,
        value_fn=lambda d: round(d.pre_boost_export_net_gain, 4),
    ),
)

_LOG = logging.getLogger(__name__)


# Coordinator-driven — no parallel updates needed
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GivEnergy Manager sensors."""
    coordinator: GivEnergyCoordinator = entry.runtime_data
    async_add_entities(
        GivEnergyManagerSensor(coordinator, description) for description in SENSOR_DESCRIPTIONS
    )


class GivEnergyManagerSensor(CoordinatorEntity[GivEnergyCoordinator], SensorEntity):
    """A sensor entity for GivEnergy Inverter Manager."""

    entity_description: GivEnergyManagerSensorDescription
    _attr_has_entity_name = True

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
        self._is_daily_total = description.is_daily_total
        self._attr_entity_registry_enabled_default = description.entity_registry_enabled_default
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "GivEnergy Inverter Manager",
            "manufacturer": "GivEnergy",
            "model": "Inverter Manager",
            "sw_version": INTEGRATION_VERSION,
        }

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
        """Return the last reset time for daily total sensors (enables HA long-term stats)."""
        if not self._is_daily_total:
            return None
        coordinator = self.coordinator
        if coordinator.data and coordinator.data.last_reset_time:
            from datetime import datetime, timezone

            try:
                dt = datetime.fromisoformat(coordinator.data.last_reset_time)
                # Stored as local timezone since coordinator fix; old UTC values
                # have no tzinfo so fall back to UTC for backwards compatibility.
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, AttributeError):
                pass
        return None

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return html attribute for report sensors (rendered in Markdown/HTML template cards)."""
        if self.entity_description.html_fn is None:
            return None
        if self.coordinator.data is None:
            return None
        return {"html": self.entity_description.html_fn(self.coordinator.data)}

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
