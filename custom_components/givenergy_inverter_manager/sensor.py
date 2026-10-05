"""
sensor.py — Sensor platform for GivEnergy Inverter Manager.

Exposes all calculated and tracked values as Home Assistant sensor entities.
Every sensor reads from the shared GivEnergyCoordinator data snapshot —
no direct polling of GivTCP or any external source.

The description table lives in the sensor_descriptions package, one module per theme
(power, tariff, today, bill, battery, decisions, loads, diagnostics, forecast, week,
month and year, reports, and so on). The value rules live in sensor_values.py. This
module holds the entity class and the platform setup.

All sensors use the CoordinatorEntity mixin so they update automatically
whenever the coordinator refreshes, and become unavailable if the coordinator
fails (e.g. GivTCP goes offline).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_CURRENCY_SYMBOL
from .coordinator import GivEnergyConfigEntry, GivEnergyCoordinator
from .entity import GivEnergyEntity
from .sensor_descriptions import SENSOR_DESCRIPTIONS
from .sensor_descriptions.base import (
    CURRENCY_UNIT,
    GivEnergyManagerSensorDescription,
    reset_period_of,
)

_RESET_FIELDS = {
    "day": "last_reset_time",
    "week": "week_start_time",
    "month": "month_start_time",
    "year": "year_start_time",
}

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
        self._reset_period = reset_period_of(description)
        self._value_error_logged = False

    @property
    def native_unit_of_measurement(self) -> str | None:
        """
        Return the unit of measurement.

        For monetary sensors the unit is the configured currency symbol,
        read from coordinator data so it updates when the user changes
        their currency in the options flow without restarting HA.
        """
        declared = self.entity_description.native_unit_of_measurement
        if declared == CURRENCY_UNIT:
            if self.coordinator.data is not None:
                return self.coordinator.data.currency_symbol
            return DEFAULT_CURRENCY_SYMBOL  # safe fallback before first update
        return declared

    @property
    def last_reset(self) -> datetime | None:
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
    def native_value(self) -> Any:
        """Return sensor value from coordinator data."""
        if self.coordinator.data is None:
            return None
        try:
            return self.entity_description.value_fn(self.coordinator.data)
        except Exception as exc:  # noqa: BLE001
            self._warn_once_value_fn_raised(exc)
            return None

    def _warn_once_value_fn_raised(self, exc: Exception) -> None:
        """Log the first value_fn failure of this sensor, then stay quiet."""
        if not self._value_error_logged:
            self._value_error_logged = True
            _LOG.warning("Sensor %s value_fn raised: %s", self.entity_description.key, exc)

    @property
    def available(self) -> bool:
        """Return True if coordinator has data and the entity is applicable."""
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return False
        return self.entity_description.available_fn(self.coordinator.data)
