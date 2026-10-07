"""Solar forecast and forecast accuracy sensors."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfEnergy

from .. import sensor_values as values
from .base import GivEnergyManagerSensorDescription

DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
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
        key="solar_forecast_raw_today",
        translation_key="solar_forecast_raw_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=None,
        icon="mdi:weather-sunny",
        entity_registry_enabled_default=True,
        value_fn=values.solar_forecast_raw_today,
    ),
    GivEnergyManagerSensorDescription(
        key="solar_actual_vs_forecast_pct",
        translation_key="solar_actual_vs_forecast_pct",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-sunny-alert",
        entity_registry_enabled_default=True,
        value_fn=values.solar_actual_vs_forecast_pct,
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
)
