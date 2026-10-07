"""The write log: who wrote the charge target, the charge window and the schedule switches."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from conftest import CHARGE_START, ENABLE_TARGET, MIDDAY, TARGET_SOC
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.givenergy_inverter_manager.accumulation import _STORAGE_KEY
from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.core.tariff import build_tariff

pytestmark = pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)


def _register_inverter_like_services(hass) -> None:
    """Make number, switch and select writes change the entity state, as GivTCP does."""

    async def set_number(call) -> None:
        hass.states.async_set(call.data["entity_id"], str(call.data["value"]), context=call.context)

    async def set_select(call) -> None:
        hass.states.async_set(call.data["entity_id"], call.data["option"], context=call.context)

    def set_switch(state: str):
        async def handler(call) -> None:
            hass.states.async_set(call.data["entity_id"], state, context=call.context)

        return handler

    hass.services.async_register("number", "set_value", set_number)
    hass.services.async_register("select", "select_option", set_select)
    hass.services.async_register("switch", "turn_on", set_switch("on"))
    hass.services.async_register("switch", "turn_off", set_switch("off"))


async def _write_target(entry, target_soc: int) -> None:
    coordinator = entry.runtime_data
    coordinator._writer.last_write_time.clear()
    cfg = coordinator._effective_cfg()
    cheap = min(build_tariff(cfg).rate_periods, key=lambda p: p.rate)
    await coordinator._async_apply_charge_target(cfg, target_soc, cheap)


async def _recent_writes(hass, entry) -> list[dict]:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_register_write_count"
    )
    return hass.states.get(entity_id).attributes["recent_writes"]


async def test_manager_writes_are_listed_newest_first_with_a_reason(hass, loaded_entry):
    _register_inverter_like_services(hass)

    await _write_target(loaded_entry, 62)

    writes = await _recent_writes(hass, loaded_entry)
    by_reason = {w["reason"]: w for w in writes}
    assert by_reason["charge target"]["entity_id"] == TARGET_SOC
    assert by_reason["charge target"]["value"] == "62"
    assert by_reason["charge window start"]["entity_id"] == CHARGE_START
    assert by_reason["enable charge target"]["entity_id"] == ENABLE_TARGET
    assert writes[0]["reason"] == "enable charge target"
    assert all(w["time"] for w in writes)


async def test_the_managers_own_writes_are_not_reported_as_external(hass, loaded_entry):
    _register_inverter_like_services(hass)

    await _write_target(loaded_entry, 62)

    reasons = {w["reason"] for w in await _recent_writes(hass, loaded_entry)}
    assert "charge target" in reasons
    assert "external" not in reasons


async def test_a_change_made_by_a_user_is_logged_with_its_context(hass, loaded_entry, caplog):
    caplog.set_level(logging.INFO)

    hass.states.async_set(
        TARGET_SOC, "55", context=Context(user_id="user-1", parent_id="parent-1")
    )

    newest = (await _recent_writes(hass, loaded_entry))[0]
    assert newest["reason"] == "external"
    assert (newest["entity_id"], newest["value"]) == (TARGET_SOC, "55")
    assert (newest["user_id"], newest["parent_id"]) == ("user-1", "parent-1")
    assert f"{TARGET_SOC} changed from 80 to 55 outside the manager" in caplog.text


async def test_a_change_with_no_user_is_logged_without_context_fields(hass, loaded_entry):
    hass.states.async_set(CHARGE_START, "01:00:00")

    newest = (await _recent_writes(hass, loaded_entry))[0]
    assert newest["reason"] == "external"
    assert "user_id" not in newest
    assert "parent_id" not in newest


async def test_the_same_value_set_again_later_by_someone_else_is_external(hass, loaded_entry):
    _register_inverter_like_services(hass)
    await _write_target(loaded_entry, 62)
    hass.states.async_set(TARGET_SOC, "70")

    hass.states.async_set(TARGET_SOC, "62")

    newest = (await _recent_writes(hass, loaded_entry))[0]
    assert (newest["reason"], newest["value"]) == ("external", "62")


async def test_going_unavailable_and_coming_back_is_not_a_change(hass, loaded_entry):
    before = await _recent_writes(hass, loaded_entry)

    hass.states.async_set(TARGET_SOC, "unavailable")
    hass.states.async_set(TARGET_SOC, "80")

    assert await _recent_writes(hass, loaded_entry) == before


async def test_an_entity_the_manager_does_not_watch_is_ignored(hass, loaded_entry):
    before = await _recent_writes(hass, loaded_entry)

    hass.states.async_set(ENABLE_TARGET, "on")

    assert await _recent_writes(hass, loaded_entry) == before


async def test_the_log_and_count_are_saved_soon_after_a_write(
    hass, loaded_entry, hass_storage, freezer
):
    """A crash right after a write must not lose it. No unload and no tenth cycle here."""
    _register_inverter_like_services(hass)

    await _write_target(loaded_entry, 62)
    freezer.tick(timedelta(seconds=20))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    saved = hass_storage[_STORAGE_KEY]["data"]
    assert saved["register_write_count"] == loaded_entry.runtime_data._writer.write_count > 0
    assert {e["reason"] for e in saved["register_write_log"]} >= {"charge target"}


async def test_the_log_survives_a_reload(hass, loaded_entry, hass_storage):
    _register_inverter_like_services(hass)
    await _write_target(loaded_entry, 62)
    count = loaded_entry.runtime_data._writer.write_count

    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert loaded_entry.state is ConfigEntryState.LOADED
    assert loaded_entry.runtime_data._writer.write_count == count
    reasons = {w["reason"] for w in await _recent_writes(hass, loaded_entry)}
    assert "charge target" in reasons
