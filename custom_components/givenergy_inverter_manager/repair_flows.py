"""
repair_flows.py: the fix flows of the fixable repair issues.

  other_charge_slots_active -> ClearOtherChargeSlotsFlow
  battery_cost_not_set      -> SetBatteryCostFlow
  tariff_review_due         -> ConfirmTariffReviewedFlow

Imported lazily by repairs.async_create_fix_flow, because it needs the
`repairs` integration, which the unit test stub of Home Assistant lacks.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.util import dt as dt_util

from .config_flow import battery_cost_selector
from .config_helpers import effective_config
from .const import (
    CONF_BATTERY_COST,
    CONF_CURRENCY,
    CONF_TARIFF_REVIEWED_ON,
    DEFAULT_CURRENCY,
    DOMAIN,
)
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


class ConfirmTariffReviewedFlow(ConfirmRepairFlow):
    """Ask once, then record today as the day the tariff was last reviewed."""

    async def async_step_confirm(self, user_input: dict[str, str] | None = None) -> Any:
        """Record the review when confirmed. The options change does not reload the entry."""
        if user_input is None:
            return await super().async_step_confirm()
        entries = self.hass.config_entries.async_entries(DOMAIN)
        loaded = [e for e in entries if e.state is ConfigEntryState.LOADED]
        if not loaded:
            return self.async_abort(reason="not_loaded")
        today = dt_util.now().date().isoformat()
        for entry in loaded:
            options = {**entry.options, CONF_TARIFF_REVIEWED_ON: today}
            self.hass.config_entries.async_update_entry(entry, options=options)
        return self.async_create_entry(data={})


class SetBatteryCostFlow(RepairsFlow):
    """Ask for the battery cost and save it to the options."""

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> Any:
        """Home Assistant starts every repair flow here, with the issue data as the input."""
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> Any:
        """Show the cost field, and save a cost above zero."""
        entry = self._loaded_entry()
        if entry is None:
            return self.async_abort(reason="not_loaded")
        errors: dict[str, str] = {}
        if user_input is not None:
            cost = float(user_input[CONF_BATTERY_COST])
            if cost > 0:
                self._save_cost(entry, cost)
                return self.async_create_entry(data={})
            errors["base"] = "cost_required"
        currency = effective_config(entry).get(CONF_CURRENCY, DEFAULT_CURRENCY)
        schema = vol.Schema({vol.Required(CONF_BATTERY_COST): battery_cost_selector(currency)})
        return self.async_show_form(step_id="confirm", data_schema=schema, errors=errors)

    def _save_cost(self, entry: ConfigEntry, cost: float) -> None:
        """Add the cost to the saved options and leave every other option as it is.

        Saving reloads the integration, as saving the options form does. A section the
        options form sends and this flow does not (rate periods, forecast, devices) is
        never rewritten here, so nothing the user saved is lost.
        """
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_BATTERY_COST: cost}
        )

    def _loaded_entry(self) -> ConfigEntry | None:
        entries = self.hass.config_entries.async_entries(DOMAIN)
        return next((e for e in entries if e.state is ConfigEntryState.LOADED), None)
