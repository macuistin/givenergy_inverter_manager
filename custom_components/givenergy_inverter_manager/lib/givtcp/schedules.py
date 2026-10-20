"""
schedules.py: the discharge (export) schedule and the extra charge slots.

GivTCP publishes ten charge slots and ten discharge slots, each a start and an end, a discharge
target per discharge slot, and one switch per schedule. This integration only ever uses charge
slot 1 and never exports, but the client is for any host, so the rest is here.

The order of a discharge write matters. Nothing discharges to the grid until the schedule is
enabled, so the target and the window are written first and the switch last. A write that fails
stops the sequence before the switch, so a half-set schedule is never switched on. Turning a
schedule off writes the switch only.

A discharge slot changes while its schedule might be on, and for a moment the inverter holds a
mix of the old and new times that can be wider than either (see windows.py). So a slot write
switches a schedule that is on off first, and back on once the slot reads back. If the slot is
not confirmed the schedule stays off, the safe side for an export switch. A schedule whose
switch cannot be read is not touched at all.

The client has no policy. A host that must not export does not call this module.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import time
from typing import Any

from ._entity import GetState, clamp_to_entity, read_int, usable
from .controls import ClockWriter, control_entity, write_battery_mode
from .defaults import GIVTCP_MAX_CHARGE_TARGET_PCT, GIVTCP_MIN_CHARGE_TARGET_PCT
from .discovery import MAX_CHARGE_SLOTS, UNUSED_SLOT_TIME, clock_time, device_prefix
from .model import BatteryMode, SlotKind, Window
from .status import WriteStatus
from .writer import GivTCPWriter, SwitchState

ENABLE_DISCHARGE_SCHEDULE_SUFFIX = "_enable_discharge_schedule"
ENABLE_CHARGE_SCHEDULE_SUFFIX = "_enable_charge_schedule"
MAX_DISCHARGE_SLOTS = 10
_TIME_DOMAINS = ("select", "time")


def _slot_ok(slot: int, highest: int) -> bool:
    return 1 <= slot <= highest


Entities = tuple[tuple[str, ...], tuple[str, ...]]


def slot_entities(prefix: str, kind: SlotKind, slot: int) -> Entities:
    """The start and end entity ids of one slot, best first."""
    return (
        tuple(f"{d}.{prefix}_{kind}_start_time_slot_{slot}" for d in _TIME_DOMAINS),
        tuple(f"{d}.{prefix}_{kind}_end_time_slot_{slot}" for d in _TIME_DOMAINS),
    )


class GivTCPSchedules:
    """Reads and writes the discharge schedule and the charge slots from 2 up."""

    def __init__(self, writer: GivTCPWriter, get_state: GetState) -> None:
        self._writer = writer
        self._get_state = get_state

    # ── Reads ─────────────────────────────────────────────────────────────────

    def read_slot(
        self, cfg: Mapping[str, Any], kind: SlotKind, slot: int = 1
    ) -> tuple[str, str] | None:
        """The slot's start and end as HH:MM, None when either is missing or not a time."""
        prefix = device_prefix(cfg)
        highest = MAX_DISCHARGE_SLOTS if kind is SlotKind.DISCHARGE else MAX_CHARGE_SLOTS
        if not prefix or not _slot_ok(slot, highest):
            return None
        pair = slot_entities(prefix, kind, slot)
        found = [
            next((clock_time(s) for e in candidates if (s := self._get_state(e)) is not None), None)
            for candidates in pair
        ]
        return (found[0], found[1]) if found[0] is not None and found[1] is not None else None

    def read_discharge_target(self, cfg: Mapping[str, Any], slot: int = 1) -> int | None:
        """The discharge target in per cent for a slot, None when not published."""
        entity = control_entity(cfg, "number", f"_discharge_target_soc_{slot}")
        return read_int(self._get_state, entity) if _slot_ok(slot, MAX_DISCHARGE_SLOTS) else None

    def discharge_schedule_enabled(self, cfg: Mapping[str, Any]) -> bool | None:
        """Whether the discharge schedule is on. None when GivTCP does not publish the switch."""
        entity = control_entity(cfg, "switch", ENABLE_DISCHARGE_SCHEDULE_SUFFIX)
        state = usable(self._get_state(entity)) if entity else None
        return None if state not in ("on", "off") else state == "on"

    # ── Writes ────────────────────────────────────────────────────────────────

    async def apply_slot(
        self, cfg: Mapping[str, Any], kind: SlotKind, slot: int, window: Window
    ) -> WriteStatus:
        """Write one slot's start and end and nothing else, in the order windows.py gives.

        A discharge slot is written with its schedule switched off, and the schedule goes back
        on only when the slot is confirmed.
        """
        start, end = window
        if start == end:
            return WriteStatus.REFUSED
        return await self._write_window_for(cfg, kind, slot, window)

    async def clear_slot(self, cfg: Mapping[str, Any], kind: SlotKind, slot: int) -> WriteStatus:
        """Set a slot back to unused (00:00:00 to 00:00:00), as apply_slot writes a slot."""
        unused = time(0, 0)
        return await self._write_window_for(cfg, kind, slot, (unused, unused))

    async def _write_window_for(
        self, cfg: Mapping[str, Any], kind: SlotKind, slot: int, window: Window
    ) -> WriteStatus:
        """Write a slot's window. An empty window can only come from clear_slot."""
        prefix = device_prefix(cfg)
        highest = MAX_DISCHARGE_SLOTS if kind is SlotKind.DISCHARGE else MAX_CHARGE_SLOTS
        if not prefix or not _slot_ok(slot, highest):
            return WriteStatus.REFUSED
        wanted = (window[0].strftime("%H:%M"), window[1].strftime("%H:%M"))
        if self.read_slot(cfg, kind, slot) == wanted:
            return WriteStatus.ALREADY_SET
        starts, ends = slot_entities(prefix, kind, slot)
        clock = ClockWriter(self._writer, self._get_state)
        name = f"{'clear ' if window[0] == window[1] else ''}{kind.value} slot {slot}"

        async def write() -> WriteStatus:
            return await clock.write_window((starts, ends), window, name)

        if kind is not SlotKind.DISCHARGE:
            return await write()
        return await self._with_schedule_off(cfg, write)

    async def _with_schedule_off(
        self, cfg: Mapping[str, Any], write: Callable[[], Awaitable[WriteStatus]]
    ) -> WriteStatus:
        """Run *write* with the discharge schedule off if it was on, and restore it after."""
        entity = control_entity(cfg, "switch", ENABLE_DISCHARGE_SCHEDULE_SUFFIX)
        state = self._get_state(entity) if entity else None
        if state is None:
            return await write()  # no switch is published, so no schedule can be running
        was = usable(state)
        if was not in ("on", "off"):
            return WriteStatus.REFUSED  # it might be on, and a mixed window would export
        if was == "off":
            return await write()
        stopped = await self.set_discharge_schedule(cfg, enabled=False)
        if not stopped.confirmed:
            return stopped if not stopped else WriteStatus.UNCONFIRMED
        written = await write()
        if not written.confirmed:
            return written  # the schedule stays off
        restored = await self.set_discharge_schedule(cfg, enabled=True)
        return written if restored.confirmed else restored

    async def apply_discharge_target(
        self, cfg: Mapping[str, Any], percent: int, slot: int = 1
    ) -> WriteStatus:
        """Set a discharge slot's target, kept inside what the entity publishes."""
        entity = control_entity(cfg, "number", f"_discharge_target_soc_{slot}")
        if not entity or not _slot_ok(slot, MAX_DISCHARGE_SLOTS):
            return WriteStatus.REFUSED
        value = clamp_to_entity(
            percent,
            self._get_state(entity),
            GIVTCP_MIN_CHARGE_TARGET_PCT,
            GIVTCP_MAX_CHARGE_TARGET_PCT,
        )
        return await self._writer.set_number(entity, value, f"discharge target {slot}")

    async def set_discharge_schedule(self, cfg: Mapping[str, Any], *, enabled: bool) -> WriteStatus:
        """Switch the discharge schedule on or off."""
        entity = control_entity(cfg, "switch", ENABLE_DISCHARGE_SCHEDULE_SUFFIX)
        wanted = SwitchState.ON if enabled else SwitchState.OFF
        return await self._writer.set_switch(entity, wanted, "discharge schedule")

    async def apply_discharge_plan(
        self, cfg: Mapping[str, Any], window: Window, target_percent: int, slot: int = 1
    ) -> WriteStatus:
        """Set a discharge slot and switch the schedule on, last.

        Order: target, window start, window end, then the schedule. Stops at the first write
        that fails, leaving the schedule as it was.
        """
        return (
            await self.apply_discharge_target(cfg, target_percent, slot)
            and await self.apply_slot(cfg, SlotKind.DISCHARGE, slot, window)
            and await self.set_discharge_schedule(cfg, enabled=True)
        )

    async def apply_battery_mode(self, cfg: Mapping[str, Any], mode: BatteryMode) -> WriteStatus:
        """Select any battery mode, including Timed Export, which sends power to the grid.

        The integration-facing `GivTCPControls.apply_battery_mode` takes `SelfUseMode` only.
        """
        return await write_battery_mode(self._writer, self._get_state, cfg, BatteryMode(mode))

    async def stop_discharge(self, cfg: Mapping[str, Any]) -> WriteStatus:
        """Switch the discharge schedule off. The slots keep their times.

        REFUSED when the switch cannot be read, because an unreadable switch might be on.
        """
        return await self.set_discharge_schedule(cfg, enabled=False)


__all__ = [
    "GivTCPSchedules",
    "SlotKind",
    "Window",
    "MAX_DISCHARGE_SLOTS",
    "UNUSED_SLOT_TIME",
    "slot_entities",
]
