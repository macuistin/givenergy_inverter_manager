"""
reconfigure_flow.py - reconfigure is the inverter connection.

  reconfigure         the current mapping next to what discovery finds for the same inverter,
                      and a choice: use what was found, or pick the entities by hand
  reconfigure_manual  the entity selectors, filled with the mapping in force

Both check that the five required entities exist and are not unavailable, and that the inverter
is the one the entry was created for (the serial in the entity ids against the unique id). The
mapping is saved with async_update_and_abort. The entry's update listener sees the wiring change
and reloads once, so this flow never reloads itself. The tariff is edited in the options wizard.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.helpers import selector

from ..core.wizard_pages import WIRING_REQUIRED, missing_wiring, unavailable_wiring
from .detect import detect
from .flow_base import bullet_lines, states_by_id
from .selectors import entity_selector
from .wiring import (
    WIRING_KEYS,
    WIRING_OPTIONAL,
    serials_in_wiring,
    serials_match,
    wiring_from,
)

SOURCE_KEY = "source"
SOURCE_FOUND = "found"
SOURCE_MANUAL = "manual"


class ReconfigureSteps:
    """The reconfigure steps. Mixed in before ConfigFlow."""

    hass: Any

    def _entry_now(self) -> Any:
        return self._get_reconfigure_entry()  # type: ignore[attr-defined]

    def _mapping_text(self, mapping: dict[str, str]) -> str:
        lines = [f"{key}: {mapping.get(key) or 'not set'}" for key in WIRING_KEYS]
        return bullet_lines(lines)

    def _found_for(self, entry: Any) -> Any:
        """The discovered inverter with this entry's serial, when it has all its sensors."""
        detected = detect(states_by_id(self.hass))
        serial = str(entry.unique_id or "").lower()
        for inverter in detected.inverters:
            if inverter.is_fully_configured and inverter.serial.lower() == serial:
                return inverter
        return None

    def _check_wiring(self, mapping: dict[str, str]) -> dict[str, str]:
        """Errors for a mapping: a required entity is missing or unavailable."""
        return missing_wiring(mapping) or unavailable_wiring(mapping, states_by_id(self.hass))

    @staticmethod
    def _is_another_inverter(entry: Any, mapping: dict[str, str]) -> bool:
        """True when the entities carry a serial other than the one the entry was created for."""
        return not serials_match(serials_in_wiring(mapping), entry.unique_id)

    def _save_wiring(self, entry: Any, mapping: dict[str, str]) -> Any:
        """Save the mapping. An optional entity left empty is removed from the entry."""
        data = {k: v for k, v in entry.data.items() if k not in WIRING_OPTIONAL}
        data.update({k: v for k, v in mapping.items() if v})
        return self.async_update_and_abort(entry, data=data)  # type: ignore[attr-defined]

    def _reconfigure_schema(self, found: Any) -> vol.Schema:
        options = [SOURCE_MANUAL] if found is None else [SOURCE_FOUND, SOURCE_MANUAL]
        default = SOURCE_MANUAL if found is None else SOURCE_FOUND
        return vol.Schema(
            {
                vol.Required(SOURCE_KEY, default=default): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        translation_key=SOURCE_KEY,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> Any:
        """Show the mapping in force and what discovery finds, and take the user's choice."""
        entry = self._entry_now()
        found = self._found_for(entry)
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get(SOURCE_KEY) == SOURCE_MANUAL or found is None:
                return await self.async_step_reconfigure_manual()
            mapping = wiring_from(found)
            errors = self._check_wiring(mapping)
            if not errors:
                return self._save_wiring(entry, mapping)
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="reconfigure",
            data_schema=self._reconfigure_schema(found),
            errors=errors,
            description_placeholders={
                "current": self._mapping_text(dict(entry.data)),
                "found": (
                    self._mapping_text(wiring_from(found))
                    if found
                    else "Nothing was found for this inverter's serial."
                ),
            },
        )

    def _manual_schema(self, entry: Any, mapping: dict[str, str]) -> vol.Schema:
        fields: dict[Any, Any] = {}
        for key in WIRING_KEYS:
            current = mapping.get(key) or entry.data.get(key)
            required = key in WIRING_REQUIRED
            marker = vol.Required if required else vol.Optional
            fields[
                marker(key, description={"suggested_value": current}) if current else marker(key)
            ] = entity_selector(_domain_of(key))
        return vol.Schema(fields)

    async def async_step_reconfigure_manual(self, user_input: dict[str, Any] | None = None) -> Any:
        """The entity selectors, filled with the mapping in force."""
        entry = self._entry_now()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._check_wiring(user_input)
            if not errors and self._is_another_inverter(entry, user_input):
                return self.async_abort(reason="wrong_inverter")  # type: ignore[attr-defined]
            if not errors:
                return self._save_wiring(entry, user_input)
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="reconfigure_manual",
            data_schema=self._manual_schema(entry, user_input or {}),
            errors=errors,
        )


def _domain_of(key: str) -> str | list[str]:
    """The entity domain each wiring key takes."""
    return _DOMAINS.get(key, "sensor")


_DOMAINS: dict[str, str] = {
    "target_soc_entity": "number",
    "enable_charge_target_entity": "switch",
    "enable_charge_schedule_entity": "switch",
    "charge_start_time_entity": "select",
    "charge_end_time_entity": "select",
}
