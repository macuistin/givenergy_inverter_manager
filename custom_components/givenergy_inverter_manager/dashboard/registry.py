"""
registry.py - finds our entities in the Home Assistant entity registry.

Also reads what the dashboard needs to know about the config entry and the external EV charger.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..const import DOMAIN


@dataclass(frozen=True)
class HostFacts:
    """What Home Assistant tells the generator that is not in the config entry.

    resources are the Lovelace resource URLs, or None when they could not be read.
    admin_ids are the IDs of the administrators who may see the Settings view. With none,
    the Settings view and its button are left out, so no one sees them.
    """

    resources: list[str] | None = None
    admin_ids: tuple[str, ...] = ()


class Registry:
    """Looks up our entities and skips those that are missing or disabled.

    A card that points at a disabled entity shows "Entity not available", so the
    generator leaves such rows out and remembers what it dropped.
    """

    def __init__(self, registry, entry_id: str) -> None:
        self._reg = registry
        self._entry_id = entry_id
        self.disabled: dict[str, str] = {}

    def get(self, unique_id_suffix: str) -> str | None:
        """Return the entity_id for one of our entities, or None if unusable."""
        uid = f"{self._entry_id}_{unique_id_suffix}"
        entity_id = None
        for domain in ("sensor", "switch", "number"):
            entity_id = self._reg.async_get_entity_id(domain, DOMAIN, uid)
            if entity_id:
                break
        if not entity_id:
            return None
        registered = self._reg.async_get(entity_id)
        if registered is not None and registered.disabled_by is not None:
            label = registered.name or registered.original_name or entity_id
            self.disabled.setdefault(entity_id, label)
            return None
        return entity_id


_EV_CHARGER_CANDIDATES = [
    "sensor.myenergi_zappi_power_ct_internal_load",
    "sensor.myenergi_zappi_power_ct_internal_load_2",
    "sensor.myenergi_zappi2_power_ct_internal_load",
    "sensor.wallbox_charging_power",
    "sensor.ohme_current_power",
]


def external_ev_power(hass: HomeAssistant) -> str | None:
    """Return the first known external EV charger power entity that exists.

    These integrations report the charger's power directly. The integration's own
    sensor reads from GivTCP and may show 0W.
    """
    for candidate in _EV_CHARGER_CANDIDATES:
        if hass.states.get(candidate) is not None:
            return candidate
    return None


def entry_config(entry: ConfigEntry) -> dict:
    """Return the config entry's data with options layered over it."""
    return {**entry.data, **entry.options}


async def async_admin_user_ids(hass: HomeAssistant) -> tuple[str, ...]:
    """The IDs of the active administrators, as the dashboard's user conditions name them.

    System users, such as the Supervisor, never open a dashboard, so they are left out.
    """
    users = await hass.auth.async_get_users()
    return tuple(user.id for user in users if user.is_admin and not user.system_generated)
