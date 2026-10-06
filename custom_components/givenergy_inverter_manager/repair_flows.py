"""
repair_flows.py: the one-click fix for the other_charge_slots_active repair issue.

Imported lazily by repairs.async_create_fix_flow, because it needs the
`repairs` integration, which the unit test stub of Home Assistant lacks.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.config_entries import ConfigEntryState

from .const import DOMAIN
from .repairs import ClearOutcome


class ClearOtherChargeSlotsFlow(ConfirmRepairFlow):
    """Ask once, then set every other active charge slot back to 00:00 to 00:00."""

    async def async_step_confirm(self, user_input: dict[str, str] | None = None) -> Any:
        """Show the slots that will be cleared, and clear them once confirmed."""
        if user_input is None:
            return await super().async_step_confirm()
        coordinator = self._loaded_coordinator()
        if coordinator is None:
            return self.async_abort(reason="not_loaded")
        outcome = await coordinator.async_clear_other_charge_slots()
        if outcome is ClearOutcome.CLEARED:
            return self.async_create_entry(data={})
        return self.async_abort(reason=outcome.value)

    def _loaded_coordinator(self) -> Any | None:
        entries = self.hass.config_entries.async_entries(DOMAIN)
        return next(
            (e.runtime_data for e in entries if e.state is ConfigEntryState.LOADED), None
        )
