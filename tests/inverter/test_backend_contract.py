"""The backend contract against the fake backend and the GivTCP adapter over plain states."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_CHARGE_END_TIME_ENTITY,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_ENABLE_CHARGE_SCHEDULE,
    CONF_ENABLE_CHARGE_TARGET,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_INVERTER_SERIAL,
    CONF_SOLAR_POWER,
    CONF_TARGET_SOC_ENTITY,
)
from custom_components.givenergy_inverter_manager.core.inverter_values import (
    FeedState,
    FeedStatus,
    InverterValues,
)
from custom_components.givenergy_inverter_manager.inverter.givtcp import GivTCPPorts, make_backend
from custom_components.givenergy_inverter_manager.lib.givtcp.writer import GivTCPWriter
from tests.backend_contract import UNUSED, BackendContract
from tests.fakes.fake_inverter import FakeInverter, FakeSlot

NOW = datetime(2031, 3, 4, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_write_retry_sleep(monkeypatch):
    monkeypatch.setitem(GivTCPWriter.write_verified.__globals__, "GIVTCP_WRITE_RETRY_SLEEP_S", 0)


class FakeHarness:
    cfg: dict = {}
    now = NOW

    def __init__(self) -> None:
        self.backend = FakeInverter(watched=("fake.target",))

    def publish(self, *, solar_w, soc, charging_w, import_w, load_w):
        self.backend.values = InverterValues(
            solar_power_w=solar_w,
            battery_soc=soc,
            battery_power_w=charging_w,
            grid_power_w=import_w,
            house_load_w=load_w,
        )

    def go_silent(self):
        self.backend.status = FeedStatus(FeedState.SILENT)
        self.backend.values = InverterValues(unavailable_inputs=("solar_power", "battery_soc"))

    def pause(self):
        self.backend.status = FeedStatus(FeedState.PAUSED)

    def set_target(self, soc):
        self.backend.target_soc = soc

    def set_other_slot(self, number, start, end):
        self.backend.slots.append(FakeSlot(number, start, end))

    def fail_target_writes(self):
        self.backend.fail_target = True

    def target(self):
        return self.backend.target_soc

    def enable_target(self):
        return self.backend.enable_target

    def window(self):
        return self.backend.window

    def other_slot(self, number):
        return next(((s.start, s.end) for s in self.backend.slots if s.number == number), (UNUSED, UNUSED))

    def device_writes(self):
        return self.backend.device_writes


class GivTCPHarness:
    """The GivTCP adapter over a dict of states that follows every write, like the real device."""

    now = NOW
    serial = "ab1234c567"

    def __init__(self) -> None:
        self.prefix = f"givtcp_{self.serial}"
        e = self.entity
        self.cfg = {
            CONF_INVERTER_SERIAL: self.serial,
            CONF_SOLAR_POWER: e("sensor", "pv_power"),
            CONF_BATTERY_SOC: e("sensor", "soc"),
            CONF_BATTERY_POWER: e("sensor", "battery_power"),
            CONF_GRID_POWER: e("sensor", "grid_power"),
            CONF_HOUSE_LOAD: e("sensor", "load_power"),
            CONF_TARGET_SOC_ENTITY: e("number", "target_soc"),
            CONF_ENABLE_CHARGE_TARGET: e("switch", "enable_charge_target"),
            CONF_ENABLE_CHARGE_SCHEDULE: e("switch", "enable_charge_schedule"),
            CONF_CHARGE_START_TIME_ENTITY: e("select", "charge_start_time_slot_1"),
            CONF_CHARGE_END_TIME_ENTITY: e("select", "charge_end_time_slot_1"),
        }
        self.states: dict[str, SimpleNamespace] = {}
        self.writes: list[tuple[str, str, object]] = []
        self.failing: set[str] = set()
        self._set(self.cfg[CONF_TARGET_SOC_ENTITY], "50")
        for key in (CONF_ENABLE_CHARGE_TARGET, CONF_ENABLE_CHARGE_SCHEDULE):
            self._set(self.cfg[key], "off")
        for key in (CONF_CHARGE_START_TIME_ENTITY, CONF_CHARGE_END_TIME_ENTITY):
            self._set(self.cfg[key], UNUSED)
        self.publish(solar_w=0, soc=50, charging_w=0, import_w=0, load_w=300)
        self.backend = make_backend(
            self.cfg,
            GivTCPPorts(
                get_state=self.states.get,
                call_service=self._call_service,
                on_count_change=lambda count: None,
            ),
        )

    def entity(self, domain: str, suffix: str) -> str:
        return f"{domain}.{self.prefix}_{suffix}"

    def _set(self, entity_id: str, value: object) -> None:
        self.states[entity_id] = SimpleNamespace(state=str(value), last_reported=NOW)

    async def _call_service(self, domain, service, data):
        entity_id = data["entity_id"]
        if entity_id in self.failing:
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError("write rejected")
        value = {"turn_on": "on", "turn_off": "off"}.get(service)
        value = data.get("value", data.get("option")) if value is None else value
        self.writes.append((service, entity_id, value))
        self._set(entity_id, value)

    # GivTCP publishes grid as positive for export and battery as positive for discharging.
    def publish(self, *, solar_w, soc, charging_w, import_w, load_w):
        self._set(self.cfg[CONF_SOLAR_POWER], solar_w)
        self._set(self.cfg[CONF_BATTERY_SOC], soc)
        self._set(self.cfg[CONF_BATTERY_POWER], -charging_w)
        self._set(self.cfg[CONF_GRID_POWER], -import_w)
        self._set(self.cfg[CONF_HOUSE_LOAD], load_w)

    def go_silent(self):
        self._set(self.cfg[CONF_SOLAR_POWER], "unavailable")
        self._set(self.cfg[CONF_BATTERY_SOC], "unavailable")

    def pause(self):
        self._set(self.entity("sensor", "status"), "paused")

    def set_target(self, soc):
        self._set(self.cfg[CONF_TARGET_SOC_ENTITY], soc)

    def set_other_slot(self, number, start, end):
        self._set(self.entity("select", f"charge_start_time_slot_{number}"), start)
        self._set(self.entity("select", f"charge_end_time_slot_{number}"), end)

    def fail_target_writes(self):
        self.failing.add(self.cfg[CONF_TARGET_SOC_ENTITY])

    def target(self):
        return int(self.states[self.cfg[CONF_TARGET_SOC_ENTITY]].state)

    def enable_target(self):
        return self.states[self.cfg[CONF_ENABLE_CHARGE_TARGET]].state == "on"

    def window(self):
        return (
            self.states[self.cfg[CONF_CHARGE_START_TIME_ENTITY]].state,
            self.states[self.cfg[CONF_CHARGE_END_TIME_ENTITY]].state,
        )

    def other_slot(self, number):
        return (
            self.states[self.entity("select", f"charge_start_time_slot_{number}")].state,
            self.states[self.entity("select", f"charge_end_time_slot_{number}")].state,
        )

    def device_writes(self):
        return len(self.writes)


class TestFakeBackend(BackendContract):
    @pytest.fixture
    def harness(self):
        return FakeHarness()


class TestGivTCPAdapter(BackendContract):
    @pytest.fixture
    def harness(self):
        return GivTCPHarness()
