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

  other_charge_slots_active
    A charge slot other than the one the integration writes has a charge
    window set (start differs from end). The inverter charges in every
    active slot, so a leftover slot can charge the battery at a dearer rate
    than the cheapest period. Fixable: the repair clears each such slot to
    00:00 to 00:00 through the coordinator's verified writer.

  battery_cost_not_set
    Battery cost is 0 after the integration has run for a while, so battery wear is
    0 and Net Saving Today equals Saving vs Grid Today. Fixable: the repair asks for
    the cost and saves it to the options, keeping every other saved option. Dismiss it
    if the battery has no cost to count.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)

from .const import DOMAIN
from .discovery import ActiveChargeSlot, describe_charge_slots

if TYPE_CHECKING:
    from homeassistant.components.repairs import RepairsFlow

ISSUE_GIVTCP_ENTITIES_MISSING = "givtcp_entities_missing"
ISSUE_MIN_SOC_TOO_HIGH = "min_soc_too_high"
ISSUE_OTHER_CHARGE_SLOTS_ACTIVE = "other_charge_slots_active"
ISSUE_BATTERY_COST_NOT_SET = "battery_cost_not_set"

TROUBLESHOOTING_URL = (
    "https://github.com/macuistin/givenergy_inverter_manager/blob/main/docs/troubleshooting.md"
)
LEARN_MORE_URLS: dict[str, str] = {
    ISSUE_GIVTCP_ENTITIES_MISSING: f"{TROUBLESHOOTING_URL}#givtcp-entities-not-found",
    ISSUE_MIN_SOC_TOO_HIGH: f"{TROUBLESHOOTING_URL}#battery-minimum-soc-is-set-too-high",
    ISSUE_OTHER_CHARGE_SLOTS_ACTIVE: f"{TROUBLESHOOTING_URL}#other-charge-slots-are-active",
    ISSUE_BATTERY_COST_NOT_SET: f"{TROUBLESHOOTING_URL}#battery-cost-is-not-set",
}

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
        learn_more_url=LEARN_MORE_URLS[ISSUE_GIVTCP_ENTITIES_MISSING],
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
        learn_more_url=LEARN_MORE_URLS[ISSUE_MIN_SOC_TOO_HIGH],
        severity=IssueSeverity.WARNING,
        translation_key=ISSUE_MIN_SOC_TOO_HIGH,
        translation_placeholders={"min_soc": str(min_soc)},
    )


def async_delete_min_soc_issue(hass: HomeAssistant) -> None:
    """Clear the min-SoC-too-high repair issue once the value is within range."""
    async_delete_issue(hass, DOMAIN, ISSUE_MIN_SOC_TOO_HIGH)


class ClearOutcome(StrEnum):
    """How an attempt to clear the other charge slots ended."""

    CLEARED = "cleared"
    DRY_RUN = "dry_run"
    FAILED = "write_failed"


def async_create_other_charge_slots_issue(
    hass: HomeAssistant, slots: Sequence[ActiveChargeSlot]
) -> None:
    """Surface a fixable repair issue naming each other charge slot that is active."""
    async_create_issue(
        hass,
        DOMAIN,
        ISSUE_OTHER_CHARGE_SLOTS_ACTIVE,
        is_fixable=True,
        learn_more_url=LEARN_MORE_URLS[ISSUE_OTHER_CHARGE_SLOTS_ACTIVE],
        severity=IssueSeverity.WARNING,
        translation_key=ISSUE_OTHER_CHARGE_SLOTS_ACTIVE,
        translation_placeholders={"slots": describe_charge_slots(slots)},
    )


def async_delete_other_charge_slots_issue(hass: HomeAssistant) -> None:
    """Clear the other-charge-slots repair issue once no other slot is active."""
    async_delete_issue(hass, DOMAIN, ISSUE_OTHER_CHARGE_SLOTS_ACTIVE)


def async_create_battery_cost_issue(hass: HomeAssistant) -> None:
    """Surface a fixable repair issue asking for the battery cost."""
    async_create_issue(
        hass,
        DOMAIN,
        ISSUE_BATTERY_COST_NOT_SET,
        is_fixable=True,
        learn_more_url=LEARN_MORE_URLS[ISSUE_BATTERY_COST_NOT_SET],
        severity=IssueSeverity.WARNING,
        translation_key=ISSUE_BATTERY_COST_NOT_SET,
    )


def async_delete_battery_cost_issue(hass: HomeAssistant) -> None:
    """Clear the battery-cost repair issue once a cost is set."""
    async_delete_issue(hass, DOMAIN, ISSUE_BATTERY_COST_NOT_SET)


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    """Home Assistant calls this to fix a fixable issue."""
    # Imported here because the repairs integration is not available to the unit test stub.
    from .repair_flows import ClearOtherChargeSlotsFlow, SetBatteryCostFlow

    if issue_id == ISSUE_BATTERY_COST_NOT_SET:
        return SetBatteryCostFlow()
    return ClearOtherChargeSlotsFlow()
