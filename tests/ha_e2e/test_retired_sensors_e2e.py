"""Setup deletes the registry entries of the retired pre-boost export sensors."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager import _RETIRED_SENSOR_KEYS
from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.core.devices import Device
from custom_components.givenergy_inverter_manager.sensor import SENSOR_DESCRIPTIONS

RETIRED_KEYS = (
    "pre_boost_export_recommended",
    "pre_boost_export_kwh",
    "pre_boost_export_net_gain",
)


def _register_retired_entries(hass, entry) -> list[str]:
    registry = er.async_get(hass)
    return [
        registry.async_get_or_create(
            "sensor", DOMAIN, f"{entry.entry_id}_{key}", config_entry=entry
        ).entity_id
        for key in RETIRED_KEYS
    ]


def _entity_ids(registry, entry) -> list[str]:
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    return sorted(e.entity_id for e in entries)


async def _setup(hass, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def _unload(hass, entry) -> None:
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _docs_generator():
    path = Path(__file__).resolve().parents[2] / "scripts" / "gen_sensor_docs.py"
    spec = importlib.util.spec_from_file_location("gen_sensor_docs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cleanup_list_matches_the_removed_sensors():
    assert set(_RETIRED_SENSOR_KEYS) == set(RETIRED_KEYS)


def test_sensor_docs_list_the_same_removed_sensors():
    documented = {key for key, _ in _docs_generator().RETIRED_SENSORS}
    assert documented == set(_RETIRED_SENSOR_KEYS)


async def test_fresh_install_never_creates_the_sensors(hass, loaded_entry):
    registry = er.async_get(hass)
    for key in RETIRED_KEYS:
        unique_id = f"{loaded_entry.entry_id}_{key}"
        assert registry.async_get_entity_id("sensor", DOMAIN, unique_id) is None


async def test_setup_removes_an_existing_entry_for_each_retired_sensor(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    stale_ids = _register_retired_entries(hass, config_entry)
    registry = er.async_get(hass)
    assert all(registry.async_get(entity_id) for entity_id in stale_ids)

    await _setup(hass, config_entry)

    assert [registry.async_get(entity_id) for entity_id in stale_ids] == [None, None, None]
    sensors = [
        e
        for e in er.async_entries_for_config_entry(registry, config_entry.entry_id)
        if e.domain == "sensor"
    ]
    # No EV charger is discoverable and no oil price is set, so those sensors are not created.
    assert len(sensors) == len(
        [d for d in SENSOR_DESCRIPTIONS if d.requires not in (Device.EV_CHARGER, Device.OIL_ADVICE)]
    )
    await _unload(hass, config_entry)


async def test_setup_removes_a_disabled_entry_too(
    hass, hass_in_scenario, service_calls, config_entry
):
    """The sensors were disabled by default, so most installs hold a disabled entry."""
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    entity_id = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{config_entry.entry_id}_pre_boost_export_kwh",
        config_entry=config_entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    ).entity_id

    await _setup(hass, config_entry)

    assert registry.async_get(entity_id) is None
    await _unload(hass, config_entry)


async def test_setup_leaves_other_entities_alone(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    same_key_other_integration = registry.async_get_or_create(
        "sensor", "some_other_integration", f"{config_entry.entry_id}_pre_boost_export_kwh"
    ).entity_id
    same_key_other_entry = registry.async_get_or_create(
        "sensor", DOMAIN, "another_entry_id_pre_boost_export_kwh"
    ).entity_id
    live_sensor = registry.async_get_or_create(
        "sensor", DOMAIN, f"{config_entry.entry_id}_solar_power", config_entry=config_entry
    ).entity_id

    await _setup(hass, config_entry)

    assert registry.async_get(same_key_other_integration) is not None
    assert registry.async_get(same_key_other_entry) is not None
    assert registry.async_get(live_sensor) is not None
    await _unload(hass, config_entry)


async def test_cleanup_is_idempotent_across_reloads(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    _register_retired_entries(hass, config_entry)
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    before = _entity_ids(registry, config_entry)

    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    after = _entity_ids(registry, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert after == before
    await _unload(hass, config_entry)
