"""
diagnostics.py — Download diagnostics for GivEnergy Inverter Manager.

Exposes a "Download Diagnostics" button in Settings → Devices & Services.
Provides the config entry data in redacted form for filing bug reports.
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_INVERTER_SERIAL

_REDACT_KEYS: set[str] = {CONF_INVERTER_SERIAL}
_REDACTED = "**REDACTED**"


def _redact_serial(value: Any, serial: str | None) -> Any:
    """Replace the inverter serial wherever it appears inside a value (entity IDs)."""
    if not serial:
        return value
    if isinstance(value, str):
        return re.sub(re.escape(serial), _REDACTED, value, flags=re.IGNORECASE)
    if isinstance(value, dict):
        return {k: _redact_serial(v, serial) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_serial(v, serial) for v in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data: dict[str, Any] = dict(entry.data)
    data.update(entry.options)
    serial = data.get(CONF_INVERTER_SERIAL)
    data = _redact_serial(async_redact_data(data, _REDACT_KEYS), serial)

    result: dict[str, Any] = {
        "config": data,
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_cycle": coordinator.update_cycle,
            "solar_fractions": coordinator.solar_fractions,
            "has_ev_charger": coordinator.ev_charger_brand is not None,
            "ev_charger_brand": coordinator.ev_charger_brand,
        },
    }

    if coordinator.data is not None:
        result["current_data"] = {
            "battery_soc": coordinator.data.battery_soc,
            "solar_power_w": coordinator.data.solar_power_w,
            "grid_power_w": coordinator.data.grid_power_w,
            "current_rate": coordinator.data.current_rate,
            "current_rate_period": coordinator.data.current_rate_name,
            "dry_run": coordinator.data.dry_run,
            "charge_target": (
                coordinator.data.charge_decision.target_soc
                if coordinator.data.charge_decision
                else None
            ),
        }

    return result
