"""
adapter.py: the GivTCP implementation of an inverter backend.

It is built once per host with the callables the host already has for reading a state and
calling a service, so a test drives it without Home Assistant. A failed service call is reported
by raising ServiceCallError from `call_service`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from . import controls, schedules, sequence
from .controls import BatteryPause
from .discovery import (
    GIVTCP_PREFIX,
    ActiveChargeSlot,
    clock_time,
    device_prefix,
    discover_battery_cycle_entities,
    find_other_active_charge_slots,
)
from .force import Force, GivTCPForce
from .keys import (
    KEY_CHARGE_END_TIME_ENTITY,
    KEY_CHARGE_START_TIME_ENTITY,
    KEY_INVERTER_SERIAL,
    KEY_TARGET_SOC_ENTITY,
)
from .reader import GivTCPReader
from .schedules import SlotKind, Window
from .values import (
    ChargePlan,
    FeedStatus,
    InverterIdentity,
    InverterValues,
    RateDefaults,
    WriteResult,
)
from .writer import CallService, CountListener, GetState, GivTCPWriter, WriteObserver


@dataclass(frozen=True)
class GivTCPPorts:
    """What the adapter needs from its host: read a state, call a service, hear the count."""

    get_state: GetState
    call_service: CallService
    on_count_change: CountListener
    observer: WriteObserver | None = None
    verbose: Callable[[], bool] | None = None


class GivTCPBackend:
    """Reads and writes one GivTCP inverter."""

    def __init__(self, cfg: Mapping[str, Any], ports: GivTCPPorts) -> None:
        get_state = ports.get_state
        self._get_state = get_state
        serial = str(cfg.get(KEY_INVERTER_SERIAL) or "")
        self._identity = InverterIdentity(
            serial=serial,
            prefix=device_prefix(cfg) or f"{GIVTCP_PREFIX}{serial}",
            display_name=f"GivTCP {serial}",
        )
        self._reader = GivTCPReader(get_state)
        self.writer = GivTCPWriter(
            get_state,
            ports.call_service,
            ports.on_count_change,
            ports.observer,
        )
        self._controls = controls.GivTCPControls(self.writer, get_state)
        self._schedules = schedules.GivTCPSchedules(self.writer, get_state)
        self._force = GivTCPForce(self.writer, get_state)
        if ports.verbose:
            self.writer.verbose = ports.verbose

    @property
    def identity(self) -> InverterIdentity:
        return self._identity

    def read(self, cfg: Mapping[str, Any]) -> InverterValues:
        return self._reader.read(cfg)

    def feed_status(self, cfg: Mapping[str, Any], now: datetime) -> FeedStatus:
        return self._reader.feed_status(cfg, now)

    async def apply_charge_plan(self, cfg: Mapping[str, Any], plan: ChargePlan) -> WriteResult:
        return await sequence.apply_charge_plan(self.writer, cfg, plan)

    async def apply_floor_target(self, cfg: Mapping[str, Any], soc: int) -> WriteResult:
        return await sequence.apply_floor_target(self.writer, cfg, soc, self._get_state)

    def read_charge_window(self, cfg: Mapping[str, Any]) -> tuple[str, str] | None:
        start_entity = cfg.get(KEY_CHARGE_START_TIME_ENTITY)
        end_entity = cfg.get(KEY_CHARGE_END_TIME_ENTITY)
        if not (start_entity and end_entity):
            return None
        start, end = (clock_time(self._get_state(e)) for e in (start_entity, end_entity))
        return (start, end) if start is not None and end is not None else None

    async def apply_charge_window(self, cfg: Mapping[str, Any], start: time, end: time) -> bool:
        return await sequence.apply_charge_window(self.writer, cfg, start, end)

    def other_active_charge_slots(self, cfg: Mapping[str, Any]) -> Sequence[ActiveChargeSlot]:
        start_entity = cfg.get(KEY_CHARGE_START_TIME_ENTITY)
        end_entity = cfg.get(KEY_CHARGE_END_TIME_ENTITY)
        if not (start_entity and end_entity):
            return []
        return find_other_active_charge_slots(start_entity, end_entity, self._get_state)

    async def clear_charge_slot(self, slot: ActiveChargeSlot) -> bool:
        return await sequence.clear_charge_slot(self.writer, slot)

    # ── Settings beside the charge write ──────────────────────────────────────

    def read_battery_mode(self, cfg: Mapping[str, Any]) -> str | None:
        return controls.read_battery_mode(self._get_state, cfg)

    def read_reserve(self, cfg: Mapping[str, Any]) -> int | None:
        return controls.read_reserve(self._get_state, cfg)

    def read_charge_rate(self, cfg: Mapping[str, Any]) -> int | None:
        return controls.read_charge_rate(self._get_state, cfg)

    def read_discharge_rate(self, cfg: Mapping[str, Any]) -> int | None:
        return controls.read_discharge_rate(self._get_state, cfg)

    def clock_skew_s(self, cfg: Mapping[str, Any], now: datetime) -> float | None:
        return controls.clock_skew_s(self._get_state, cfg, now)

    async def apply_battery_mode(self, cfg: Mapping[str, Any], mode: str) -> bool:
        return await self._controls.apply_battery_mode(cfg, mode)

    async def apply_reserve(self, cfg: Mapping[str, Any], percent: int) -> bool:
        return await self._controls.apply_reserve(cfg, percent)

    async def apply_charge_rate(self, cfg: Mapping[str, Any], watts: int) -> bool:
        return await self._controls.apply_charge_rate(cfg, watts)

    async def apply_discharge_rate(self, cfg: Mapping[str, Any], watts: int) -> bool:
        return await self._controls.apply_discharge_rate(cfg, watts)

    async def apply_battery_pause(
        self,
        cfg: Mapping[str, Any],
        pause: BatteryPause,
        start: time | None = None,
        end: time | None = None,
    ) -> bool:
        return await self._controls.apply_battery_pause(cfg, pause, start, end)

    # ── Discharge (export), extra charge slots and timed force ────────────────

    def read_slot(
        self, cfg: Mapping[str, Any], kind: SlotKind, slot: int = 1
    ) -> tuple[str, str] | None:
        return self._schedules.read_slot(cfg, kind, slot)

    def read_discharge_target(self, cfg: Mapping[str, Any], slot: int = 1) -> int | None:
        return self._schedules.read_discharge_target(cfg, slot)

    def discharge_schedule_enabled(self, cfg: Mapping[str, Any]) -> bool | None:
        return self._schedules.discharge_schedule_enabled(cfg)

    async def apply_slot(
        self, cfg: Mapping[str, Any], kind: SlotKind, slot: int, window: Window
    ) -> bool:
        return await self._schedules.apply_slot(cfg, kind, slot, window)

    async def clear_slot(self, cfg: Mapping[str, Any], kind: SlotKind, slot: int) -> bool:
        return await self._schedules.clear_slot(cfg, kind, slot)

    async def apply_discharge_plan(
        self, cfg: Mapping[str, Any], window: Window, target_percent: int, slot: int = 1
    ) -> bool:
        return await self._schedules.apply_discharge_plan(cfg, window, target_percent, slot)

    async def stop_discharge(self, cfg: Mapping[str, Any]) -> bool:
        return await self._schedules.stop_discharge(cfg)

    async def start_force(self, cfg: Mapping[str, Any], force: Force, minutes: int) -> bool:
        return await self._force.start(cfg, force, minutes)

    async def cancel_force(self, cfg: Mapping[str, Any], force: Force) -> bool:
        return await self._force.cancel(cfg, force)

    def read_rate_defaults(self, cfg: Mapping[str, Any]) -> RateDefaults | None:
        return self._reader.rate_defaults(cfg.get(KEY_INVERTER_SERIAL), device_prefix(cfg))

    def watched_entity_ids(self, cfg: Mapping[str, Any]) -> tuple[str, ...]:
        keys = (KEY_TARGET_SOC_ENTITY, KEY_CHARGE_START_TIME_ENTITY, KEY_CHARGE_END_TIME_ENTITY)
        return tuple(cfg[key] for key in keys if cfg.get(key))

    def solar_energy_entity_id(self, cfg: Mapping[str, Any]) -> str | None:
        prefix = device_prefix(cfg)
        return f"sensor.{prefix}_pv_energy_today_kwh" if prefix else None

    @property
    def battery_cycle_entities(self) -> list[str]:
        """The BMS cycle counters found so far, one per battery pack."""
        return self._reader.battery_cycle_entities

    @battery_cycle_entities.setter
    def battery_cycle_entities(self, entity_ids: list[str]) -> None:
        self._reader.battery_cycle_entities = entity_ids

    def rediscover(self, all_states: Mapping[str, Any]) -> None:
        self.battery_cycle_entities = discover_battery_cycle_entities(dict(all_states))

    def listen_for_confirmations(self, listener: Any) -> None:
        self.writer.listen_for_confirmations(listener)

    def cooldown_active(self, entity_id: str, name: str, value: object) -> bool:
        return self.writer.cooldown_active(entity_id, name, value)

    def start_cooldown(self, entity_id: str, value: object) -> None:
        self.writer.start_cooldown(entity_id, value)

    @property
    def write_count(self) -> int:
        return self.writer.write_count

    @write_count.setter
    def write_count(self, count: int) -> None:
        self.writer.write_count = count


def read_rate_defaults(
    serial: str | None, get_state: GetState, prefix: str | None = None
) -> RateDefaults | None:
    """The rates GivTCP holds, for the setup tariff page, before any backend exists."""
    return GivTCPReader(get_state).rate_defaults(serial, prefix)


def make_backend(cfg: Mapping[str, Any], ports: GivTCPPorts) -> GivTCPBackend:
    """The GivTCP backend for the inverter named in cfg."""
    return GivTCPBackend(cfg, ports)
