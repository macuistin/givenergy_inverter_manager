"""The car: its plug status, charge, charging power and whether it is at home.

These sensors need a car set up in the options (Device.CAR). They read the car's own entities
and only report. Nothing here changes what the charge plan does.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfPower

from .. import sensor_values as values
from ..core.devices import Device
from .base import GivEnergyManagerSensorDescription

DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
    GivEnergyManagerSensorDescription(
        key="car_plug_status",
        requires=Device.CAR,
        translation_key="car_plug_status",
        value_fn=values.car_plug_status,
        attrs_fn=values.car_plug_attributes,
    ),
    GivEnergyManagerSensorDescription(
        key="car_battery_level",
        requires=Device.CAR,
        translation_key="car_battery_level",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=values.car_battery_level,
    ),
    GivEnergyManagerSensorDescription(
        key="car_charging_power",
        requires=Device.CAR,
        translation_key="car_charging_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=values.car_charging_power,
    ),
    GivEnergyManagerSensorDescription(
        key="car_at_home",
        requires=Device.CAR,
        translation_key="car_at_home",
        value_fn=values.car_at_home,
    ),
)
