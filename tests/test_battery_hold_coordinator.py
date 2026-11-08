"""The coordinator holds the house battery back while the car draws from it, and puts it back."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_DRY_RUN,
    CONF_EV_HOLD_BATTERY,
    CONF_INVERTER_SERIAL,
)
from custom_components.givenergy_inverter_manager.core.ev_battery_hold import HoldRecord
from custom_components.givenergy_inverter_manager.discovery import EVCharger, EVChargerBrand
from custom_components.givenergy_inverter_manager.lib.givtcp.model import (
    BatteryPause,
    PauseSetting,
)
from custom_components.givenergy_inverter_manager.lib.givtcp.writer import GivTCPWriter
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states

PLUG = "sensor.myenergi_zappi_plug_status"
POWER = "sensor.myenergi_zappi_internal_load_ct1"
PREFIX = "givtcp_fd2309f069"
MODE = f"select.{PREFIX}_battery_pause_mode"
START = f"select.{PREFIX}_battery_pause_start_time_slot"
END = f"select.{PREFIX}_battery_pause_end_time_slot"
TIMES = [f"{h:02d}:{m:02d}:00" for h in range(24) for m in range(60)]
MORNING = datetime(2031, 3, 4, 10, 17, tzinfo=timezone.utc)

# GivTCP reports a discharging battery as positive power.
DISCHARGING_3KW = "3000"


@pytest.fixture(autouse=True)
def _no_write_retry_sleep(monkeypatch):
    """Skip the real read-back delay in the inverter write helpers."""
    monkeypatch.setitem(GivTCPWriter.write_verified.__globals__, "GIVTCP_WRITE_RETRY_SLEEP_S", 0)


def _keep_select_options(coord: FakeCoordinator) -> None:
    """A real select keeps its options when it takes a value. The fake's write-back drops them."""
    written = coord._call_service

    async def call_service(domain, service, data):
        before = coord._states.get(data["entity_id"])
        await written(domain, service, data)
        if before is not None and service == "select_option":
            coord._states[data["entity_id"]].attributes = before.attributes

    coord._call_service = call_service


def _coordinator(**cfg) -> FakeCoordinator:
    coord = FakeCoordinator(cfg=_cfg(**{CONF_INVERTER_SERIAL: "fd2309f069", **cfg}))
    coord.set_states(_default_states())
    coord.set_state(MODE, "PauseDischarge", {"options": ["Disabled", "PauseCharge", "PauseDischarge", "PauseBoth"]})
    coord.set_state(START, "23:00:00", {"options": TIMES})
    coord.set_state(END, "08:00:00", {"options": TIMES})
    coord._ev_charger = EVCharger(
        brand=EVChargerBrand.ZAPPI,
        name="Zappi",
        serial="1",
        display_name="Zappi",
        status_entity=PLUG,
        power_entity=POWER,
    )
    _keep_select_options(coord)
    coord._now = lambda: coord.clock
    coord.clock = MORNING
    return coord


def _car(coord: FakeCoordinator, *, charging: bool, battery_w: str = DISCHARGING_3KW) -> None:
    coord.set_states(
        {
            PLUG: "Charging" if charging else "EV Connected",
            POWER: "7000" if charging else "0",
            "sensor.battery_power": battery_w if charging else "0",
        }
    )


async def _cycle(coord: FakeCoordinator, minutes: float = 0.5) -> None:
    coord.clock += timedelta(minutes=minutes)
    await coord._async_update_data()


def _pause(coord: FakeCoordinator) -> tuple[str, str, str]:
    return (
        coord._states[MODE].state,
        coord._states[START].state,
        coord._states[END].state,
    )


async def test_a_car_draining_the_battery_gets_a_hold_with_the_switch_on():
    coord = _coordinator(**{CONF_EV_HOLD_BATTERY: True})
    _car(coord, charging=True)

    await _cycle(coord)

    assert _pause(coord) == ("PauseDischarge", "10:15:00", "10:45:00")
    assert coord._battery_hold.record.prior == PauseSetting(
        BatteryPause.DISCHARGE, (datetime(2031, 1, 1, 23).time(), datetime(2031, 1, 1, 8).time())
    )
    assert coord._hold_store.saved[0] is not None


async def test_the_night_pause_comes_back_after_the_car_stops():
    coord = _coordinator(**{CONF_EV_HOLD_BATTERY: True})
    _car(coord, charging=True)
    await _cycle(coord)

    _car(coord, charging=False)
    await _cycle(coord, 1)
    assert _pause(coord)[1] == "10:15:00"
    await _cycle(coord, 6)

    assert _pause(coord) == ("PauseDischarge", "23:00:00", "08:00:00")
    assert coord._hold_store.saved[-1] is None


async def test_a_car_draining_the_battery_gets_a_hold_with_no_setting_saved():
    coord = _coordinator()
    _car(coord, charging=True)

    await _cycle(coord)

    assert _pause(coord) == ("PauseDischarge", "10:15:00", "10:45:00")


async def test_nothing_is_written_with_the_switch_off():
    coord = _coordinator(**{CONF_EV_HOLD_BATTERY: False})
    _car(coord, charging=True)

    await _cycle(coord)

    assert _pause(coord) == ("PauseDischarge", "23:00:00", "08:00:00")
    assert coord.service_calls_for("select", "select_option") == []


async def test_dry_run_sends_nothing_and_says_what_it_would_do():
    coord = _coordinator(**{CONF_EV_HOLD_BATTERY: True, CONF_DRY_RUN: True})
    _car(coord, charging=True)

    await _cycle(coord)

    assert _pause(coord) == ("PauseDischarge", "23:00:00", "08:00:00")
    assert coord.service_calls_for("select", "select_option") == []
    assert coord._hold_store.saved == []


async def test_a_car_charging_without_draining_the_battery_gets_no_hold():
    coord = _coordinator(**{CONF_EV_HOLD_BATTERY: True})
    _car(coord, charging=True, battery_w="0")

    await _cycle(coord)

    assert _pause(coord) == ("PauseDischarge", "23:00:00", "08:00:00")


async def test_a_hold_saved_before_a_restart_is_ended_once_the_car_has_stopped():
    coord = _coordinator(**{CONF_EV_HOLD_BATTERY: True})
    coord.set_state(START, "10:15:00", {"options": TIMES})
    coord.set_state(END, "10:45:00", {"options": TIMES})
    coord._battery_hold.restore(
        HoldRecord(
            PauseSetting(BatteryPause.DISCHARGE, (datetime(2031, 1, 1, 23).time(), datetime(2031, 1, 1, 8).time())),
            MORNING + timedelta(minutes=30),
        )
    )
    _car(coord, charging=False)

    await _cycle(coord, 0)
    await _cycle(coord, 6)

    assert _pause(coord) == ("PauseDischarge", "23:00:00", "08:00:00")


async def test_a_charger_that_goes_away_ends_the_hold():
    coord = _coordinator(**{CONF_EV_HOLD_BATTERY: True})
    _car(coord, charging=True)
    await _cycle(coord)

    coord._ev_charger = None
    await _cycle(coord)

    assert _pause(coord) == ("PauseDischarge", "23:00:00", "08:00:00")
    assert not coord._battery_hold.holding
