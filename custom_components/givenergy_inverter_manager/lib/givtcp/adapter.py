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

from . import sequence
from ._entity import GetState
from .controls import (
    GivTCPControls,
    clock_skew_s,
    read_battery_mode,
    read_charge_rate,
    read_discharge_rate,
    read_reserve,
)
from .discovery import (
    GIVTCP_PREFIX,
    ActiveChargeSlot,
    clock_time,
    device_prefix,
    discover_battery_cycle_entities,
    find_other_active_charge_slots,
)
from .force import GivTCPForce
from .keys import (
    KEY_CHARGE_END_TIME_ENTITY,
    KEY_CHARGE_START_TIME_ENTITY,
    KEY_INVERTER_SERIAL,
    KEY_TARGET_SOC_ENTITY,
)
from .model import BatteryMode, BatteryPause, SelfUseMode
from .reader import GivTCPReader
from .schedules import GivTCPSchedules
from .status import WriteStatus
from .values import (
    ChargePlan,
    FeedStatus,
    InverterIdentity,
    InverterValues,
    RateDefaults,
    WriteResult,
)
from .writer import (
    CallService,
    ConfirmationListener,
    CountListener,
    GivTCPWriter,
    WriteObserver,
)


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
        # The client's other writes. The coordinator is typed against InverterBackend and
        # InverterControls, which reach none of schedules or force.
        self.controls = GivTCPControls(self.writer, get_state)
        self.schedules = GivTCPSchedules(self.writer, get_state)
        self.force = GivTCPForce(self.writer, get_state)
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

    async def apply_charge_window(
        self, cfg: Mapping[str, Any], start: time, end: time
    ) -> WriteStatus:
        return await sequence.apply_charge_window(self.writer, cfg, start, end)

    def other_active_charge_slots(self, cfg: Mapping[str, Any]) -> Sequence[ActiveChargeSlot]:
        start_entity = cfg.get(KEY_CHARGE_START_TIME_ENTITY)
        end_entity = cfg.get(KEY_CHARGE_END_TIME_ENTITY)
        if not (start_entity and end_entity):
            return []
        return find_other_active_charge_slots(start_entity, end_entity, self._get_state)

    async def clear_charge_slot(self, slot: ActiveChargeSlot) -> WriteStatus:
        return await sequence.clear_charge_slot(self.writer, slot)

    # ── Settings beside the charge write ──────────────────────────────────────

    def read_battery_mode(self, cfg: Mapping[str, Any]) -> str | None:
        return read_battery_mode(self._get_state, cfg)

    def read_reserve(self, cfg: Mapping[str, Any]) -> int | None:
        return read_reserve(self._get_state, cfg)

    def read_charge_rate(self, cfg: Mapping[str, Any]) -> int | None:
        return read_charge_rate(self._get_state, cfg)

    def read_discharge_rate(self, cfg: Mapping[str, Any]) -> int | None:
        return read_discharge_rate(self._get_state, cfg)

    def clock_skew_s(self, cfg: Mapping[str, Any], now: datetime) -> float | None:
        return clock_skew_s(self._get_state, cfg, now)

    async def apply_battery_mode(
        self, cfg: Mapping[str, Any], mode: BatteryMode | SelfUseMode | str
    ) -> WriteStatus:
        return await self.controls.apply_battery_mode(cfg, mode)

    async def apply_reserve(self, cfg: Mapping[str, Any], percent: int) -> WriteStatus:
        return await self.controls.apply_reserve(cfg, percent)

    async def apply_charge_rate(self, cfg: Mapping[str, Any], watts: int) -> WriteStatus:
        return await self.controls.apply_charge_rate(cfg, watts)

    async def apply_discharge_rate(self, cfg: Mapping[str, Any], watts: int) -> WriteStatus:
        return await self.controls.apply_discharge_rate(cfg, watts)

    async def apply_battery_pause(
        self,
        cfg: Mapping[str, Any],
        pause: BatteryPause,
        start: time | None = None,
        end: time | None = None,
    ) -> WriteStatus:
        return await self.controls.apply_battery_pause(cfg, pause, start, end)

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

    def listen_for_confirmations(self, listener: ConfirmationListener) -> None:
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
        self.writer.seed_count(count)


def read_rate_defaults(
    serial: str | None, get_state: GetState, prefix: str | None = None
) -> RateDefaults | None:
    """The rates GivTCP holds, for the setup tariff page, before any backend exists."""
    return GivTCPReader(get_state).rate_defaults(serial, prefix)


def make_backend(cfg: Mapping[str, Any], ports: GivTCPPorts) -> GivTCPBackend:
    """The GivTCP backend for the inverter named in cfg."""
    return GivTCPBackend(cfg, ports)
