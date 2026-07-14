"""
repairs.py — Home Assistant repair issues for GivEnergy Inverter Manager.

Creates repair issues in Settings → System → Repairs for problems that
require user action to fix. Transient GivTCP outages are handled by
UpdateFailed (marking entities unavailable); repair issues are raised for
configuration problems that won't resolve on their own.

Issues raised:
  givtcp_entities_missing
    One or more configured GivTCP entity IDs are not registered in HA at all.
    This usually means GivTCP was reinstalled (changing entity IDs) or the
    inverter serial changed. Fix: run Reconfigure in the integration settings.

  min_soc_too_high
    CONF_BATTERY_MIN_SOC is set above the selector maximum (30%). On
    skip-charge nights the integration writes this value as the inverter's
    charge target, so a high value causes the inverter to hold the battery
    at that level all night and import from the grid.
    Fix: lower Battery minimum SoC in the integration options.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)

from .const import DOMAIN

ISSUE_GIVTCP_ENTITIES_MISSING = "givtcp_entities_missing"
ISSUE_MIN_SOC_TOO_HIGH = "min_soc_too_high"

# Matches the selector max in config_flow.py. Values above this are legacy
# configs that were saved before the selector enforced the upper bound.
MIN_SOC_HIGH_THRESHOLD = 30


def async_create_givtcp_missing_issue(hass: HomeAssistant) -> None:
    """Surface a repair issue when configured GivTCP entities are absent from HA."""
    async_create_issue(
        hass,
        DOMAIN,
        ISSUE_GIVTCP_ENTITIES_MISSING,
        is_fixable=False,
        severity=IssueSeverity.WARNING,
        translation_key=ISSUE_GIVTCP_ENTITIES_MISSING,
    )


def async_delete_givtcp_missing_issue(hass: HomeAssistant) -> None:
    """Clear the missing-entities repair issue once the entities are found again."""
    async_delete_issue(hass, DOMAIN, ISSUE_GIVTCP_ENTITIES_MISSING)


def async_create_min_soc_issue(hass: HomeAssistant, min_soc: int) -> None:
    """Surface a repair issue when Battery minimum SoC is configured too high."""
    async_create_issue(
        hass,
        DOMAIN,
        ISSUE_MIN_SOC_TOO_HIGH,
        is_fixable=False,
        severity=IssueSeverity.WARNING,
        translation_key=ISSUE_MIN_SOC_TOO_HIGH,
        translation_placeholders={"min_soc": str(min_soc)},
    )


def async_delete_min_soc_issue(hass: HomeAssistant) -> None:
    """Clear the min-SoC-too-high repair issue once the value is within range."""
    async_delete_issue(hass, DOMAIN, ISSUE_MIN_SOC_TOO_HIGH)
