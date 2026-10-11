"""
forecast.py - find a solar forecast sensor and immersion switch candidates for the setup wizard.

Detection only looks at entity ids that exist in the state machine. It never reads a value, so
a forecast integration that is still starting up is found as soon as its entities exist.

  Solcast PV Forecast   sensor.solcast_pv_forecast_forecast_tomorrow
                        sensor.solcast_pv_forecast_forecast_day_3
  Forecast.Solar        sensor.energy_production_tomorrow

The main forecast sensor is the one for tomorrow. The day after tomorrow is offered too where
the integration has one.

An immersion switch is never picked for the user. The candidates are only listed, so the user
can choose one on the hot water page.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# provider name, tomorrow sensor, day after tomorrow sensor (None when the provider has none)
_FORECAST_SENSORS: tuple[tuple[str, str, str | None], ...] = (
    (
        "Solcast",
        "sensor.solcast_pv_forecast_forecast_tomorrow",
        "sensor.solcast_pv_forecast_forecast_day_3",
    ),
    ("Forecast.Solar", "sensor.energy_production_tomorrow", None),
)

_IMMERSION_WORD = "immersion"
MAX_IMMERSION_CANDIDATES = 5


@dataclass(frozen=True)
class ForecastSensors:
    """The forecast sensors found for one provider."""

    provider: str
    tomorrow: str
    day_after: str | None = None


def discover_forecast_sensors(all_states: Mapping[str, Any]) -> ForecastSensors | None:
    """The first provider whose tomorrow sensor exists, with its day after tomorrow sensor."""
    for provider, tomorrow, day_after in _FORECAST_SENSORS:
        if tomorrow in all_states:
            found = day_after if day_after in all_states else None
            return ForecastSensors(provider, tomorrow, found)
    return None


def _friendly_name(state: Any) -> str:
    attributes = getattr(state, "attributes", None) or {}
    return str(attributes.get("friendly_name") or "")


def discover_immersion_switch_candidates(all_states: Mapping[str, Any]) -> tuple[str, ...]:
    """Switches with "immersion" in the entity id or the friendly name, sorted, at most five."""
    found = sorted(
        entity_id
        for entity_id, state in all_states.items()
        if entity_id.startswith("switch.")
        and _IMMERSION_WORD in f"{entity_id} {_friendly_name(state)}".lower()
    )
    return tuple(found[:MAX_IMMERSION_CANDIDATES])
