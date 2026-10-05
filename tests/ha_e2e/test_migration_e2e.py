"""Config entry migration inside a real Home Assistant instance."""

from __future__ import annotations

from conftest import SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager import async_migrate_entry
from custom_components.givenergy_inverter_manager.config_flow import (
    GivEnergyInverterManagerConfigFlow,
)
from custom_components.givenergy_inverter_manager.const import DOMAIN


def _entry(version: int, minor_version: int = 1) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data=full_config_data(),
        unique_id=SERIAL,
        version=version,
        minor_version=minor_version,
    )


async def test_flow_version_is_unchanged():
    assert GivEnergyInverterManagerConfigFlow.VERSION == 1


async def test_version_1_migration_returns_true_and_keeps_data(hass):
    entry = _entry(version=1)
    entry.add_to_hass(hass)
    before = dict(entry.data)

    assert await async_migrate_entry(hass, entry) is True
    assert dict(entry.data) == before
    assert entry.version == 1


async def test_unknown_version_is_not_migrated(hass):
    entry = _entry(version=2)
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is False


async def test_home_assistant_runs_the_migration_hook_on_a_minor_version_mismatch(
    hass, hass_in_scenario, service_calls, monkeypatch
):
    """A stored minor version that differs from the flow's sends the entry through the hook."""
    import custom_components.givenergy_inverter_manager as integration

    calls = []

    async def _spy(hass_, entry_):
        calls.append(entry_.entry_id)
        return await real(hass_, entry_)

    real = integration.async_migrate_entry
    monkeypatch.setattr(integration, "async_migrate_entry", _spy)
    entry = _entry(version=1, minor_version=2)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert calls == [entry.entry_id]
    assert entry.state is ConfigEntryState.LOADED
    await hass.config_entries.async_unload(entry.entry_id)
