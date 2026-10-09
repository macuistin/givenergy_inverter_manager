"""Controllable loads: the EV charger, the immersion heater and the oil water heating advice."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower, UnitOfTemperature

from .. import sensor_values as values
from ..core.devices import Device
from .base import CURRENCY_UNIT, GivEnergyManagerSensorDescription

DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
    # --- EV charger ---
    GivEnergyManagerSensorDescription(
        key="ev_charger_state",
        requires=Device.EV_CHARGER,
        translation_key="ev_charger_state",
        value_fn=lambda d: d.ev_charger_state.value if d.ev_charger_state else None,
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_power",
        requires=Device.EV_CHARGER,
        translation_key="ev_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: round(d.ev_power_w, 1),
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_session_energy",
        requires=Device.EV_CHARGER,
        translation_key="ev_session_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: round(d.ev_session_kwh, 3),
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_km_charged_today",
        requires=Device.EV_CHARGER,
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
        requires=Device.EV_CHARGER,
        translation_key="ev_cost_per_km_today",
        native_unit_of_measurement=CURRENCY_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:car-electric",
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.ev_cost_per_km_today,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_draining_battery",
        requires=Device.EV_CHARGER,
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="ev_draining_battery",
        value_fn=lambda d: values.YES if d.ev_draining_battery else values.NO,
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_protection_reason",
        requires=Device.EV_CHARGER,
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="ev_protection_reason",
        value_fn=lambda d: d.ev_protection_reason,
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_charging_source",
        requires=Device.EV_CHARGER,
        translation_key="ev_charging_source",
        value_fn=lambda d: d.ev_charging_source,
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="ev_solar_surplus_available",
        requires=Device.EV_CHARGER,
        translation_key="ev_solar_surplus_available",
        value_fn=lambda d: "Available" if d.ev_solar_surplus_available else "Not available",
        available_fn=lambda d: d.ev_available,
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_cost_today",
        requires=Device.IMMERSION_SWITCH,
        is_daily_total=True,
        translation_key="immersion_cost_today",
        native_unit_of_measurement=CURRENCY_UNIT,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: round(d.today.immersion_cost, 4),
    ),
    GivEnergyManagerSensorDescription(
        key="immersion_water_temperature",
        requires=Device.IMMERSION_SENSOR,
        translation_key="immersion_water_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: None if d.immersion_temp is None else round(d.immersion_temp, 1),
        attrs_fn=values.immersion_ready_attributes,
    ),
    GivEnergyManagerSensorDescription(
        key="water_heating_cheapest_source",
        requires=Device.OIL_ADVICE,
        translation_key="water_heating_cheapest_source",
        value_fn=values.water_heating_source,
        available_fn=lambda d: d.water_heating_advice is not None,
        attrs_fn=values.water_heating_attributes,
    ),
)
