"""Shut Home Assistant down with the accumulators pending, inside a real instance.

HA's Store registers its own one-time final-write listener for a delayed save. The
integration must not cancel that listener from inside its own final-write listener, or HA logs
"Unable to remove unknown job listener" at ERROR on every restart that lands in the window.
"""

from __future__ import annotations

import logging

import pytest
from conftest import MIDDAY
from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE, EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers.storage import Store

from custom_components.givenergy_inverter_manager.accumulation import _STORAGE_KEY

pytestmark = pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)


async def _loaded_coordinator(hass, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry.runtime_data


async def _shut_down(hass) -> None:
    """Run the same stages as hass.async_stop: STOP, then FINAL_WRITE."""
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()


def _core_errors(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "homeassistant.core" and record.levelno >= logging.ERROR
    ]


async def test_shutdown_with_a_pending_delayed_save_logs_no_error(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage, caplog
):
    coordinator = await _loaded_coordinator(hass, config_entry)
    coordinator._acc.schedule_save()
    coordinator._acc.state.week.solar_kwh = 31.5

    await _shut_down(hass)

    assert _core_errors(caplog) == []
    assert hass_storage[_STORAGE_KEY]["data"]["week"]["solar_kwh"] == pytest.approx(31.5)


async def test_shutdown_with_a_pending_delayed_save_writes_battery_stats(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage, caplog
):
    coordinator = await _loaded_coordinator(hass, config_entry)
    coordinator._acc.schedule_save()
    coordinator._battery_stats.total_cycles = 6.5

    await _shut_down(hass)

    assert hass_storage[_STORAGE_KEY]["data"]["battery_cycles"] == pytest.approx(6.5)


async def test_shutdown_with_nothing_pending_still_writes_everything(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage, caplog
):
    coordinator = await _loaded_coordinator(hass, config_entry)
    coordinator._acc.state.month.solar_kwh = 77.7
    coordinator._battery_stats.total_cycles = 4.25
    assert hass_storage[_STORAGE_KEY]["data"]["month"]["solar_kwh"] != pytest.approx(77.7)

    await _shut_down(hass)

    saved = hass_storage[_STORAGE_KEY]["data"]
    assert _core_errors(caplog) == []
    assert saved["month"]["solar_kwh"] == pytest.approx(77.7)
    assert saved["battery_cycles"] == pytest.approx(4.25)


async def test_full_home_assistant_stop_logs_no_error_and_keeps_the_data(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage, caplog
):
    coordinator = await _loaded_coordinator(hass, config_entry)
    coordinator._acc.schedule_save()
    coordinator._acc.state.year.solar_kwh = 1500.5

    await hass.async_stop()

    assert _core_errors(caplog) == []
    assert hass_storage[_STORAGE_KEY]["data"]["year"]["solar_kwh"] == pytest.approx(1500.5)


async def test_entry_unload_flushes_a_pending_delayed_save(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage, caplog
):
    coordinator = await _loaded_coordinator(hass, config_entry)
    coordinator._acc.schedule_save()
    coordinator._acc.state.month.solar_kwh = 12.5
    coordinator._battery_stats.total_cycles = 2.5

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    saved = hass_storage[_STORAGE_KEY]["data"]
    assert _core_errors(caplog) == []
    assert saved["month"]["solar_kwh"] == pytest.approx(12.5)
    assert saved["battery_cycles"] == pytest.approx(2.5)


async def test_entry_reload_flushes_before_the_new_setup_reads(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage, caplog
):
    coordinator = await _loaded_coordinator(hass, config_entry)
    coordinator._acc.state.week.solar_kwh = 8.5

    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert _core_errors(caplog) == []
    assert hass_storage[_STORAGE_KEY]["data"]["week"]["solar_kwh"] == pytest.approx(8.5)
    assert config_entry.runtime_data._acc.week.solar_kwh == pytest.approx(8.5)


async def test_the_integration_adds_no_final_write_listener_of_its_own(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage
):
    """The store owns the final write. A second listener races it, which is the bug."""
    await _loaded_coordinator(hass, config_entry)

    owners = [
        getattr(job.target, "__module__", "") or ""
        for job, _filter in hass.bus._listeners.get(EVENT_HOMEASSISTANT_FINAL_WRITE, [])
    ]
    assert not [o for o in owners if o.startswith("custom_components.")]


async def test_final_write_never_calls_store_async_save(
    hass, hass_in_scenario, service_calls, config_entry, hass_storage, monkeypatch
):
    coordinator = await _loaded_coordinator(hass, config_entry)
    coordinator._acc.schedule_save()
    calls = []
    original = Store.async_save

    async def spy(self, data):
        calls.append(data)
        await original(self, data)

    monkeypatch.setattr(Store, "async_save", spy)

    await _shut_down(hass)

    assert calls == []
