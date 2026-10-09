"""Set up and unload the integration inside a real Home Assistant instance."""

from __future__ import annotations

import asyncio
import logging

from conftest import SOLAR, TARGET_SOC
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.coordinator import GivEnergyCoordinator
from custom_components.givenergy_inverter_manager.core.devices import Device
from custom_components.givenergy_inverter_manager.sensor import SENSOR_DESCRIPTIONS

PLATFORMS = ("sensor", "switch", "number", "button")


async def test_entry_loads_with_givtcp_inputs(hass, loaded_entry):
    """(a) Full valid config plus GivTCP-style states gives a LOADED entry."""
    assert loaded_entry.state is ConfigEntryState.LOADED
    coordinator = loaded_entry.runtime_data
    assert isinstance(coordinator, GivEnergyCoordinator)
    assert coordinator.last_update_success
    assert coordinator.data is not None


async def test_platforms_register_expected_entities(hass, loaded_entry):
    """Every platform adds entities and the dashboard service is registered."""
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    by_domain = {d: [e for e in entries if e.domain == d] for d in PLATFORMS}

    # The full config has an immersion switch and sensor but no EV charger to discover.
    assert len(by_domain["sensor"]) == len(
        [d for d in SENSOR_DESCRIPTIONS if d.requires is not Device.EV_CHARGER]
    )
    assert len(by_domain["switch"]) == 5  # includes the immersion switches
    assert len(by_domain["number"]) == 4
    assert len(by_domain["button"]) == 1
    assert hass.services.has_service(DOMAIN, "get_dashboard_yaml")


async def test_every_entity_exists_once_a_charger_is_discovered(hass, loaded_entry_with_charger):
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, loaded_entry_with_charger.entry_id)
    assert len([e for e in entries if e.domain == "sensor"]) == len(SENSOR_DESCRIPTIONS)


async def test_unique_ids_are_unique(hass, loaded_entry):
    """Every entity of the entry has its own unique ID, and descriptions have unique keys."""
    keys = [d.key for d in SENSOR_DESCRIPTIONS]
    assert len(keys) == len(set(keys)), "duplicate SensorEntityDescription keys"

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    unique_ids = [(e.domain, e.unique_id) for e in entries]
    assert len(unique_ids) == len(set(unique_ids))


async def test_grid_sign_convention_end_to_end(hass, loaded_entry, scenario):
    """GivTCP publishes export as positive. The sensors must report import as positive."""
    registry = er.async_get(hass)

    def state_of(key: str) -> float:
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{loaded_entry.entry_id}_{key}")
        assert entity_id is not None, key
        return float(hass.states.get(entity_id).state)

    assert state_of("solar_power") == scenario.solar_w
    assert state_of("battery_soc") == scenario.battery_soc
    assert state_of("grid_power") == -scenario.grid_w
    assert state_of("house_load") == scenario.load_w


async def test_unload_is_clean(hass, loaded_entry, caplog):
    """(f) Unloading removes the services, marks entities unavailable and can be repeated."""
    caplog.set_level(logging.WARNING)
    registry = er.async_get(hass)
    entity_ids = [
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
        if not e.disabled
    ]
    assert entity_ids

    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert loaded_entry.state is ConfigEntryState.NOT_LOADED
    assert not hass.services.has_service(DOMAIN, "get_dashboard_yaml")
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        assert state is not None and state.state == STATE_UNAVAILABLE, entity_id

    # The entry can be set up again after an unload.
    assert await hass.config_entries.async_setup(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.LOADED
    assert hass.services.has_service(DOMAIN, "get_dashboard_yaml")

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not errors, [r.getMessage() for r in errors]


async def test_remove_entry_cleans_up(hass, loaded_entry):
    """Removing the entry drops its registry entries and services."""
    entry_id = loaded_entry.entry_id
    assert await hass.config_entries.async_remove(entry_id) is not None
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert er.async_entries_for_config_entry(registry, entry_id) == []
    assert not hass.services.has_service(DOMAIN, "get_dashboard_yaml")


async def test_setup_retries_when_givtcp_is_absent(
    hass, hass_in_scenario, service_calls, config_entry
):
    """No GivTCP states at all puts the entry in SETUP_RETRY instead of crashing."""
    for entity_id in (SOLAR, TARGET_SOC):
        hass.states.async_remove(entity_id)
    for state in list(hass.states.async_all()):
        hass.states.async_remove(state.entity_id)

    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_bill_start_day_comes_from_options_over_data(hass_in_scenario, service_calls):
    """The accumulation reset day follows the options flow, which writes entry.options."""
    from conftest import SERIAL, full_config_data
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.givenergy_inverter_manager.const import CONF_BILL_START_DAY

    hass = hass_in_scenario
    data = full_config_data()
    data[CONF_BILL_START_DAY] = 16
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=data,
        options={CONF_BILL_START_DAY: 5},
        unique_id=SERIAL,
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data._acc._bill_start_day == 5

    hass.config_entries.async_update_entry(entry, options={CONF_BILL_START_DAY: 20})
    await hass.async_block_till_done()
    assert entry.runtime_data._acc._bill_start_day == 20

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_compare_tariff_service_returns_a_like_for_like_bill(hass, loaded_entry):
    response = await hass.services.async_call(
        DOMAIN,
        "compare_tariff",
        {"rate": 0.25, "standing_charge": 0.6, "vat_rate": 13.5},
        blocking=True,
        return_response=True,
    )
    assert response["entry_id"] == loaded_entry.entry_id
    assert response["entries"][0]["entry_id"] == loaded_entry.entry_id
    assert set(response["current_tariff"]["bill"]) == set(response["comparison_tariff"]["bill"])
    assert response["comparison_tariff"]["vat_rate"] == 13.5
    assert response["current_tariff"]["vat_rate"] == 9.0


async def test_every_entity_reports_this_project_as_the_manufacturer(hass, loaded_entry):
    """The device page must not say GivEnergy made the integration."""
    from homeassistant.helpers import device_registry as dr

    from custom_components.givenergy_inverter_manager.const import DEVICE_MANUFACTURER

    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    assert devices
    assert {device.manufacturer for device in devices} == {DEVICE_MANUFACTURER}


async def test_all_entities_share_one_device_with_the_original_identifiers(hass, loaded_entry):
    """The shared entity base must keep the device identifiers and name existing installs use."""
    from homeassistant.helpers import device_registry as dr

    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, loaded_entry.entry_id)}
    assert device.name == "GivEnergy Inverter Manager"
    assert device.model == "Inverter Manager"

    entity_registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_registry, loaded_entry.entry_id)
    assert {e.device_id for e in entities} == {device.id}


async def test_unload_waits_for_pending_background_tasks(hass, loaded_entry):
    """Fire-and-forget tasks belong to the entry. Unload waits for them to finish."""
    coordinator = loaded_entry.runtime_data
    release = asyncio.Event()
    finished = asyncio.Event()

    async def short_write() -> None:
        await release.wait()
        finished.set()

    coordinator._create_task(short_write())
    assert loaded_entry._tasks, "the task must be tracked on the config entry"

    # The clock is frozen, so yield to the loop instead of sleeping.
    unload = hass.async_create_task(hass.config_entries.async_unload(loaded_entry.entry_id))
    for _ in range(10):
        await asyncio.sleep(0)
    assert not unload.done(), "unload must wait for the pending task"

    release.set()
    assert await unload
    assert finished.is_set()
    assert not loaded_entry._tasks


async def test_failed_background_task_is_logged_not_raised(hass, loaded_entry, caplog):
    """A failing fire-and-forget service call logs a warning and raises nothing."""
    caplog.set_level(logging.WARNING)
    coordinator = loaded_entry.runtime_data

    coordinator._create_task(
        coordinator._call_service("switch", "no_such_service", {"entity_id": "switch.nothing"})
    )
    await hass.async_block_till_done()

    assert any("Background task" in r.getMessage() for r in caplog.records)
