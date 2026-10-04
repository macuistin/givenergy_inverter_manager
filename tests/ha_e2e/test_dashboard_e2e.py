"""Check the dashboard generator against a real entity registry."""

from __future__ import annotations

from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import DOMAIN
from tests.dashboard_support import default_entity_ids


def _registered_id(registry, entry_id: str, key: str) -> str | None:
    for domain in ("sensor", "switch", "number"):
        entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{entry_id}_{key}")
        if entity_id:
            return entity_id
    return None


async def test_default_entity_ids_match_the_live_registry(hass, loaded_entry):
    """The IDs in docs/dashboard-example.yaml are the ones Home Assistant really assigns."""
    registry = er.async_get(hass)
    wrong = {}
    for key, expected in default_entity_ids().items():
        actual = _registered_id(registry, loaded_entry.entry_id, key)
        if actual != expected:
            wrong[key] = (expected, actual)
    assert wrong == {}
