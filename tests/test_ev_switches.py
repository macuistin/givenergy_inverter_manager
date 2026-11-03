"""Charge Now and Pause Charging: two switches that exclude each other."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from custom_components.givenergy_inverter_manager import switch
from tests.test_coordinator import FakeCoordinator, _cfg


def _switches():
    coordinator = FakeCoordinator(cfg=_cfg())
    coordinator.entry.entry_id = "entry-123"
    coordinator.async_request_refresh = AsyncMock()
    charge_now = switch.GivEnergyEVChargeNowSwitch(coordinator)
    pause = switch.GivEnergyEVPauseSwitch(coordinator)
    for entity in (charge_now, pause):
        entity.async_write_ha_state = lambda: None
    return coordinator, charge_now, pause


def test_both_start_off_and_have_their_own_unique_ids():
    _, charge_now, pause = _switches()
    assert not charge_now.is_on and not pause.is_on
    assert charge_now._attr_unique_id == "entry-123_ev_charge_now"
    assert pause._attr_unique_id == "entry-123_ev_pause"


def test_turning_charge_now_on_and_off_asks_for_a_refresh_each_time():
    coordinator, charge_now, _ = _switches()
    asyncio.run(charge_now.async_turn_on())
    assert charge_now.is_on and coordinator.override_ev_charge_now
    asyncio.run(charge_now.async_turn_off())
    assert not charge_now.is_on
    assert coordinator.async_request_refresh.await_count == 2


def test_pause_wins_and_clears_charge_now():
    coordinator, charge_now, pause = _switches()
    asyncio.run(charge_now.async_turn_on())
    asyncio.run(pause.async_turn_on())
    assert pause.is_on and not charge_now.is_on
    asyncio.run(pause.async_turn_off())
    assert not pause.is_on


def test_charge_now_clears_pause():
    _, charge_now, pause = _switches()
    asyncio.run(pause.async_turn_on())
    asyncio.run(charge_now.async_turn_on())
    assert charge_now.is_on and not pause.is_on
