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
"""

from __future__ import annotations

import importlib

from homeassistant.core import HomeAssistant

from .const import DOMAIN

ISSUE_GIVTCP_ENTITIES_MISSING = "givtcp_entities_missing"


def async_create_givtcp_missing_issue(hass: HomeAssistant) -> None:
    """Surface a repair issue when configured GivTCP entities are absent from HA."""
    ir = importlib.import_module("homeassistant.components.repairs")
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_GIVTCP_ENTITIES_MISSING,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_GIVTCP_ENTITIES_MISSING,
    )


def async_delete_givtcp_missing_issue(hass: HomeAssistant) -> None:
    """Clear the missing-entities repair issue once the entities are found again."""
    ir = importlib.import_module("homeassistant.components.repairs")
    ir.async_delete_issue(hass, DOMAIN, ISSUE_GIVTCP_ENTITIES_MISSING)
