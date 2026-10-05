"""
dashboard_support.py - shared fixtures for the dashboard generator tests.

The generator asks the entity registry which of our entities exist and are
enabled. FakeRegistry answers that from the real sensor descriptions, so a
"fresh install" registry has the same entities disabled that Home Assistant
disables on a new install. Entity IDs follow Home Assistant's naming rule for
entities with has_entity_name (device name slug + entity name slug), taken from
strings.json, so the example dashboard uses IDs a user would really see. The
real Home Assistant suite checks these IDs against a live registry.
"""

from __future__ import annotations

import importlib.util
import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.givenergy_inverter_manager.const import (
    CONF_FORECAST_ENTITY,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    CONF_INVERTER_TEMP_ENTITY,
)

ENTRY_ID = "test_entry_123"
_SCRIPT = Path(__file__).parent.parent / "scripts" / "gen_sensor_docs.py"
_DEVICE_SLUG = "givenergy_inverter_manager"

# Switch and number entities set _attr_name on the class, so the name is in code.
_OTHER_ENTITIES = {
    "auto_immersion": ("switch", "Auto Immersion Divert"),
    "immersion_managed": ("switch", "Immersion Heater (Managed)"),
    "skip_charge_override": ("switch", "Force Skip Overnight Charge"),
    "charge_target_override_enabled": ("switch", "Enable Charge Target Override"),
    "charge_target_override": ("number", "Overnight Charge Target Override"),
    "immersion_target_temp": ("number", "Immersion Target Temperature"),
    "immersion_min_temp": ("number", "Immersion Minimum Temperature"),
    "immersion_hysteresis": ("number", "Immersion Restart Gap"),
}

MINIMAL_CONFIG: dict = {}

FULL_CONFIG: dict = {
    CONF_IMMERSION_SWITCH: "switch.immersion_heater",
    CONF_IMMERSION_TEMP_SENSOR: "sensor.hot_water_cylinder_temperature",
    CONF_INVERTER_TEMP_ENTITY: "sensor.givtcp_ab1234g567_invertor_temperature",
    CONF_FORECAST_ENTITY: "sensor.energy_production_tomorrow",
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _sensors() -> list[dict]:
    """Sensor facts read from sensor.py by the docs generator (sensor.py cannot be imported)."""
    spec = importlib.util.spec_from_file_location("gen_sensor_docs", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_sensors()


def default_entity_ids() -> dict[str, str]:
    """Return {unique id suffix: entity id} as Home Assistant would name them."""
    ids = {s["key"]: f"sensor.{_DEVICE_SLUG}_{_slug(s['name'])}" for s in _sensors()}
    for key, (domain, name) in _OTHER_ENTITIES.items():
        ids[key] = f"{domain}.{_DEVICE_SLUG}_{_slug(name)}"
    return ids


def midnight_reset_ids() -> set[str]:
    """Entity IDs of the sensors that fall back to zero at midnight."""
    ids = default_entity_ids()
    return {ids[s["key"]] for s in _sensors() if s["last_reset"] == "day"}


def disabled_by_default() -> set[str]:
    return {s["key"] for s in _sensors() if not s["enabled"]}


class FakeRegistry:
    """The two entity registry calls the dashboard generator makes."""

    def __init__(
        self,
        *,
        entry_id: str = ENTRY_ID,
        enable_all: bool = False,
        enabled: set[str] = frozenset(),
        absent: set[str] = frozenset(),
    ) -> None:
        disabled = set() if enable_all else disabled_by_default() - set(enabled)
        names = {s["key"]: s["name"] for s in _sensors()} | {
            key: name for key, (_, name) in _OTHER_ENTITIES.items()
        }
        self._by_uid: dict[tuple[str, str], str] = {}
        self._entries: dict[str, SimpleNamespace] = {}
        for key, entity_id in default_entity_ids().items():
            if key in absent:
                continue
            domain = entity_id.split(".", 1)[0]
            self._by_uid[(domain, f"{entry_id}_{key}")] = entity_id
            self._entries[entity_id] = SimpleNamespace(
                entity_id=entity_id,
                name=None,
                original_name=names.get(key, key),
                disabled_by="integration" if key in disabled else None,
            )

    def async_get_entity_id(self, domain, platform, unique_id):
        return self._by_uid.get((domain, unique_id))

    def async_get(self, entity_id):
        return self._entries.get(entity_id)


@contextmanager
def fake_hass(
    config: dict | None = None,
    registry: FakeRegistry | None = None,
    states: tuple[str, ...] = (),
    ev_brand: str | None = None,
):
    """Yield a hass double wired to a fake registry, config entry and state machine."""
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.data = dict(config or {})
    entry.options = {}
    entry.runtime_data = SimpleNamespace(ev_charger_brand=ev_brand)

    hass = MagicMock()
    hass.config_entries.async_entries.return_value = [entry]
    hass.states.get = lambda entity_id: MagicMock() if entity_id in states else None
    hass.states.async_all.return_value = []

    with patch("custom_components.givenergy_inverter_manager.dashboard_builder.er") as er_mock:
        er_mock.async_get.return_value = registry or FakeRegistry()
        yield hass
