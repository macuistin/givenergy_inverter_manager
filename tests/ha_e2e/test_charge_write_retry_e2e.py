"""A nightly charge write the inverter refuses is retried, in a real Home Assistant."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from conftest import MIDDAY, TARGET_SOC
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.givenergy_inverter_manager.const import (
    CONF_BATTERY_MIN_SOC,
    DEFAULT_BATTERY_MIN_SOC,
    DOMAIN,
)

pytestmark = pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)


def _trigger() -> datetime:
    """One minute before the 02:00 start of the cheapest period, in Home Assistant's zone."""
    return datetime(2026, 6, 15, 1, 59, tzinfo=dt_util.get_default_time_zone())


def _accept_writes(hass) -> None:
    async def set_number(call) -> None:
        hass.states.async_set(call.data["entity_id"], str(call.data["value"]), context=call.context)

    async def set_select(call) -> None:
        hass.states.async_set(call.data["entity_id"], call.data["option"], context=call.context)

    def switch(state: str):
        async def handler(call) -> None:
            hass.states.async_set(call.data["entity_id"], state, context=call.context)

        return handler

    hass.services.async_register("number", "set_value", set_number)
    hass.services.async_register("select", "select_option", set_select)
    hass.services.async_register("switch", "turn_on", switch("on"))
    hass.services.async_register("switch", "turn_off", switch("off"))


def _refuse_number_writes(hass) -> None:
    async def refuse(call) -> None:
        raise HomeAssistantError("write rejected")

    hass.services.async_register("number", "set_value", refuse)


async def _recent_writes(hass, entry) -> list[dict]:
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_register_write_count"
    )
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    return hass.states.get(entity_id).attributes["recent_writes"]


def _expected_target(coordinator) -> int:
    decision = coordinator.data.charge_decision
    if decision.skip_charge:
        cfg = coordinator._effective_cfg()
        return int(cfg.get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC))
    return decision.target_soc


async def test_a_refused_write_is_retried_two_minutes_later_and_both_show_in_the_log(
    hass, loaded_entry, freezer
):
    coordinator = loaded_entry.runtime_data
    coordinator._backend.writer.last_write_time.clear()
    freezer.move_to(_trigger())
    _accept_writes(hass)
    _refuse_number_writes(hass)

    coordinator._write_charge_target_to_inverter(_trigger())
    await hass.async_block_till_done()
    first = await _recent_writes(hass, loaded_entry)
    assert hass.states.get(TARGET_SOC).state != str(_expected_target(coordinator))
    assert [w for w in first if w["reason"] == "retry"][0]["value"].startswith("attempt 1 failed")

    _accept_writes(hass)
    retry_at = _trigger() + timedelta(minutes=2)
    freezer.move_to(retry_at)
    async_fire_time_changed(hass, retry_at)
    after = await _recent_writes(hass, loaded_entry)

    assert hass.states.get(TARGET_SOC).state == str(_expected_target(coordinator))
    retry_notes = [w for w in after if w["reason"] == "retry"]
    assert len(retry_notes) == 1
    assert any(w["reason"] == "charge target" for w in after)
    assert all(w["reason"] != "external" for w in after)


async def test_unloading_cancels_a_pending_retry(hass, loaded_entry, freezer):
    coordinator = loaded_entry.runtime_data
    coordinator._backend.writer.last_write_time.clear()
    freezer.move_to(_trigger())
    _refuse_number_writes(hass)
    coordinator._write_charge_target_to_inverter(_trigger())
    await hass.async_block_till_done()
    assert coordinator._unsub_charge_retry is not None

    await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert coordinator._unsub_charge_retry is None
