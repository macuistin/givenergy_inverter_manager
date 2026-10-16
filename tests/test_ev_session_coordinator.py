"""The coordinator passes the stored EV session log to the engine and saves when a session changes."""

from __future__ import annotations

from datetime import timedelta

import pytest

from custom_components.givenergy_inverter_manager.discovery import (
    EVCharger,
    EVChargerBrand,
)
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states

PLUG = "sensor.myenergi_zappi_plug_status"
POWER = "sensor.myenergi_zappi_internal_load_ct1"


def _coordinator_with_a_zappi() -> FakeCoordinator:
    coord = FakeCoordinator(cfg=_cfg())
    coord.set_states(_default_states())
    coord._ev_charger = EVCharger(
        brand=EVChargerBrand.ZAPPI,
        name="Zappi",
        serial="1",
        display_name="Zappi",
        status_entity=PLUG,
        power_entity=POWER,
    )
    return coord


@pytest.mark.asyncio
async def test_plugging_in_starts_a_stored_session_and_queues_a_save():
    coord = _coordinator_with_a_zappi()
    coord.set_states({PLUG: "EV Connected", POWER: "0"})
    data = await coord.run_cycle()
    assert coord._acc.ev_sessions.current is not None
    assert data.ev_sessions is coord._acc.ev_sessions
    assert coord._acc.scheduled_saves == 1


@pytest.mark.asyncio
async def test_a_cycle_inside_a_session_queues_no_extra_save():
    coord = _coordinator_with_a_zappi()
    coord.set_states({PLUG: "EV Connected", POWER: "7000"})
    await coord.run_cycle()
    await coord.run_cycle()
    assert coord._acc.scheduled_saves == 1


@pytest.mark.asyncio
async def test_unplugging_ends_the_session_and_queues_a_save():
    coord = _coordinator_with_a_zappi()
    coord.set_states({PLUG: "EV Connected", POWER: "7000"})
    await coord.run_cycle()
    coord._last_update -= timedelta(seconds=30)  # a cycle's worth of charging to count
    await coord.run_cycle()
    coord.set_states({PLUG: "EV Disconnected", POWER: "0"})
    await coord.run_cycle()
    log = coord._acc.ev_sessions
    assert log.current is None
    assert log.recent[0].energy_kwh > 0
    assert coord._acc.scheduled_saves == 2


@pytest.mark.asyncio
async def test_no_charger_leaves_the_log_empty():
    coord = FakeCoordinator(cfg=_cfg())
    coord.set_states(_default_states())
    data = await coord.run_cycle()
    assert data.ev_sessions is None
    assert coord._acc.ev_sessions.is_empty
    assert coord._acc.scheduled_saves == 0
