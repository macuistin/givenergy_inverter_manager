"""The backend contract against the GivTCP adapter over tools/mock_givtcp.py.

A real Home Assistant holds the states, the mock device follows every write, and the adapter
reads and writes through the real state machine and service registry.
"""

from __future__ import annotations

import pytest
from conftest import SERIAL, full_config_data
from homeassistant.util import dt as dt_util

from custom_components.givenergy_inverter_manager.const import (
    CONF_CHARGE_END_TIME_ENTITY,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_ENABLE_CHARGE_TARGET,
    CONF_TARGET_SOC_ENTITY,
)
from custom_components.givenergy_inverter_manager.inverter.givtcp import GivTCPPorts, make_backend
from custom_components.givenergy_inverter_manager.lib.givtcp.writer import GivTCPWriter
from tests.backend_contract import BackendContract
from tools.mock_givtcp import MockGivTCP, Readings


@pytest.fixture(autouse=True)
def _no_write_retry_sleep(monkeypatch):
    monkeypatch.setitem(GivTCPWriter.write_verified.__globals__, "GIVTCP_WRITE_RETRY_SLEEP_S", 0)


class MockHarness:
    def __init__(self, hass) -> None:
        self.hass = hass
        self.cfg = full_config_data()
        self.mock = MockGivTCP(hass, serial=SERIAL)
        self.mock.publish(Readings(battery_soc=50, load_w=300))
        self.mock.install()
        self.backend = make_backend(
            self.cfg,
            GivTCPPorts(
                get_state=hass.states.get,
                call_service=lambda domain, service, data: hass.services.async_call(
                    domain, service, data, blocking=True
                ),
                on_count_change=lambda count: None,
            ),
        )

    @property
    def now(self):
        return dt_util.utcnow()

    def _state(self, entity_id: str) -> str:
        return self.hass.states.get(entity_id).state

    # The mock publishes in GivTCP's convention: grid positive is export, battery positive is
    # discharging.
    def publish(self, *, solar_w, soc, charging_w, import_w, load_w):
        self.mock.publish(
            Readings(
                solar_w=solar_w, battery_soc=soc, battery_w=-charging_w, grid_w=-import_w,
                load_w=load_w,
            ),
            reset_controls=False,
        )

    def go_silent(self):
        for key in ("solar_power", "battery_soc"):
            self.hass.states.async_set(self.mock.entities[key], "unavailable")

    def pause(self):
        self.hass.states.async_set(self.mock.entity("sensor", "status"), "paused")

    def set_target(self, soc):
        self.hass.states.async_set(self.mock.entities["target_soc"], soc)

    def set_other_slot(self, number, start, end):
        for edge, value in (("start", start), ("end", end)):
            entity_id = self.mock.entity("select", f"charge_{edge}_time_slot_{number}")
            self.hass.states.async_set(entity_id, value)
            self.mock._owned.add(entity_id)

    def fail_target_writes(self):
        self.mock.fail_on(self.mock.entities["target_soc"])

    def target(self):
        return int(self._state(self.cfg[CONF_TARGET_SOC_ENTITY]))

    def enable_target(self):
        return self._state(self.cfg[CONF_ENABLE_CHARGE_TARGET]) == "on"

    def window(self):
        return (
            self._state(self.cfg[CONF_CHARGE_START_TIME_ENTITY]),
            self._state(self.cfg[CONF_CHARGE_END_TIME_ENTITY]),
        )

    def other_slot(self, number):
        return (
            self._state(self.mock.entity("select", f"charge_start_time_slot_{number}")),
            self._state(self.mock.entity("select", f"charge_end_time_slot_{number}")),
        )

    def device_writes(self):
        return len(self.mock.writes)


class TestGivTCPAdapterOverTheMock(BackendContract):
    @pytest.fixture
    def harness(self, hass):
        return MockHarness(hass)
