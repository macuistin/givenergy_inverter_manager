"""Setup enables the sensors that became enabled by default, once, and only where the integration disabled them."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import RELOAD_AFTER_UPDATE_DELAY, ConfigEntryState
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

import custom_components.givenergy_inverter_manager as integration
from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.core.default_enabled import (
    NEWLY_ENABLED_SENSOR_KEYS,
)

DISABLER = er.RegistryEntryDisabler


def _register(hass, entry, key: str, disabled_by: er.RegistryEntryDisabler | None) -> str:
    return (
        er.async_get(hass)
        .async_get_or_create(
            "sensor",
            DOMAIN,
            f"{entry.entry_id}_{key}",
            config_entry=entry,
            disabled_by=disabled_by,
        )
        .entity_id
    )


def _register_all(hass, entry, disabled_by: er.RegistryEntryDisabler | None) -> list[str]:
    return [_register(hass, entry, key, disabled_by) for key in NEWLY_ENABLED_SENSOR_KEYS]


def _disabled_by(hass, entity_ids: list[str]) -> list[er.RegistryEntryDisabler | None]:
    registry = er.async_get(hass)
    return [registry.async_get(entity_id).disabled_by for entity_id in entity_ids]


async def _setup(hass, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def _unload(hass, entry) -> None:
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def _wait_for_the_scheduled_reload(hass) -> None:
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=RELOAD_AFTER_UPDATE_DELAY + 1)
    )
    await hass.async_block_till_done()


@pytest.fixture
def enabled_events(hass) -> list[dict]:
    """The registry updates that changed disabled_by."""
    events: list[dict] = []

    @callback
    def _only_disabled_by_changes(data) -> bool:
        return data["action"] == "update" and "disabled_by" in data["changes"]

    hass.bus.async_listen(
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        lambda event: events.append(event.data),
        event_filter=_only_disabled_by_changes,
    )
    return events


@pytest.fixture
def setup_calls(monkeypatch) -> list[str]:
    calls: list[str] = []
    real = integration.async_setup_entry

    async def _spy(hass, entry):
        calls.append(entry.entry_id)
        return await real(hass, entry)

    monkeypatch.setattr(integration, "async_setup_entry", _spy)
    return calls


async def test_the_four_sensors_are_enabled_after_the_upgrade(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    entity_ids = _register_all(hass, config_entry, DISABLER.INTEGRATION)

    await _setup(hass, config_entry)

    assert _disabled_by(hass, entity_ids) == [None] * 4
    assert all(hass.states.get(entity_id) is not None for entity_id in entity_ids)
    await _unload(hass, config_entry)


async def test_a_sensor_the_user_disabled_stays_disabled(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    user_disabled = _register(hass, config_entry, "net_saving_today", DISABLER.USER)
    by_default = _register(hass, config_entry, "saving_vs_grid_today", DISABLER.INTEGRATION)

    await _setup(hass, config_entry)

    assert _disabled_by(hass, [user_disabled, by_default]) == [DISABLER.USER, None]
    assert hass.states.get(user_disabled) is None
    await _unload(hass, config_entry)


@pytest.mark.parametrize("disabler", [DISABLER.CONFIG_ENTRY, DISABLER.DEVICE])
async def test_a_sensor_the_config_entry_or_device_disabled_is_left_alone(
    hass, config_entry, disabler
):
    """Home Assistant clears these itself when it adds the entity, so call the step directly."""
    config_entry.add_to_hass(hass)
    entity_ids = _register_all(hass, config_entry, disabler)

    integration._enable_newly_default_sensors(hass, config_entry)

    assert _disabled_by(hass, entity_ids) == [disabler] * 4


async def test_other_sensors_the_integration_disabled_stay_disabled(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    other = _register(hass, config_entry, "hours_to_cheap_rate", DISABLER.INTEGRATION)

    await _setup(hass, config_entry)

    assert _disabled_by(hass, [other]) == [DISABLER.INTEGRATION]
    await _unload(hass, config_entry)


async def test_an_entity_of_another_config_entry_is_left_alone(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    other = registry.async_get_or_create(
        "sensor", DOMAIN, "another_entry_id_net_saving_today", disabled_by=DISABLER.INTEGRATION
    )

    await _setup(hass, config_entry)

    assert registry.async_get(other.entity_id).disabled_by is DISABLER.INTEGRATION
    await _unload(hass, config_entry)


async def test_a_fresh_install_has_the_four_enabled_and_changes_nothing(
    hass, hass_in_scenario, service_calls, config_entry, enabled_events
):
    config_entry.add_to_hass(hass)

    await _setup(hass, config_entry)

    registry = er.async_get(hass)
    for key in NEWLY_ENABLED_SENSOR_KEYS:
        unique_id = f"{config_entry.entry_id}_{key}"
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        assert registry.async_get(entity_id).disabled_by is None
    assert enabled_events == []
    await _unload(hass, config_entry)


async def test_the_first_start_enables_once_and_reloads_once_without_a_loop(
    hass, hass_in_scenario, service_calls, config_entry, enabled_events, setup_calls
):
    """Home Assistant reloads an entry 30 seconds after an entity of it is enabled."""
    config_entry.add_to_hass(hass)
    entity_ids = _register_all(hass, config_entry, DISABLER.INTEGRATION)

    await _setup(hass, config_entry)
    assert len(enabled_events) == 4
    assert len(setup_calls) == 1

    await _wait_for_the_scheduled_reload(hass)
    assert config_entry.state is ConfigEntryState.LOADED
    assert len(setup_calls) == 2
    assert len(enabled_events) == 4

    await _wait_for_the_scheduled_reload(hass)
    assert len(setup_calls) == 2
    assert _disabled_by(hass, entity_ids) == [None] * 4
    await _unload(hass, config_entry)


async def test_a_second_start_does_nothing(
    hass, hass_in_scenario, service_calls, config_entry, enabled_events, setup_calls
):
    config_entry.add_to_hass(hass)
    _register_all(hass, config_entry, DISABLER.INTEGRATION)
    await _setup(hass, config_entry)
    await _wait_for_the_scheduled_reload(hass)
    await _unload(hass, config_entry)
    enabled_events.clear()
    setup_calls.clear()

    await _setup(hass, config_entry)
    await _wait_for_the_scheduled_reload(hass)

    assert enabled_events == []
    assert setup_calls == [config_entry.entry_id]
    await _unload(hass, config_entry)


async def test_a_user_who_disables_one_again_is_not_overridden_on_the_next_start(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    entity_ids = _register_all(hass, config_entry, DISABLER.INTEGRATION)
    await _setup(hass, config_entry)
    await _wait_for_the_scheduled_reload(hass)
    await _unload(hass, config_entry)
    er.async_get(hass).async_update_entity(entity_ids[0], disabled_by=DISABLER.USER)

    await _setup(hass, config_entry)

    assert _disabled_by(hass, entity_ids) == [DISABLER.USER, None, None, None]
    await _unload(hass, config_entry)
