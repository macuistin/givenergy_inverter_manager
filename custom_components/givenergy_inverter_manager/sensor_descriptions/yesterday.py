"""Yesterday comparison sensors. They are not cumulative, so none is a total."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfEnergy

from .base import CURRENCY_UNIT, GivEnergyManagerSensorDescription

DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
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
        native_unit_of_measurement=CURRENCY_UNIT,
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
        native_unit_of_measurement=CURRENCY_UNIT,
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
)
