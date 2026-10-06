"""Live power and flow sensors: solar, battery, grid, house load and power direction."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower

from .. import sensor_values as values
from .base import GivEnergyManagerSensorDescription

DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
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
        value_fn=values.grid_power_direction,
    ),
    GivEnergyManagerSensorDescription(
        key="solar_power_pct_of_max",
        translation_key="solar_power_pct_of_max",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power-variant",
        entity_registry_enabled_default=False,
        value_fn=values.solar_power_pct_of_max,
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
        value_fn=values.battery_kwh_available,
    ),
)
