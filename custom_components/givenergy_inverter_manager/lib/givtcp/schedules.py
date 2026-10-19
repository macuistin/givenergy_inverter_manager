"""
schedules.py: the discharge (export) schedule and the extra charge slots.

GivTCP publishes ten charge slots and ten discharge slots, each a start and an end, a discharge
target per discharge slot, and one switch per schedule. This integration only ever uses charge
slot 1 and never exports, but the client is for any host, so the rest is here.

The order of a discharge write matters. Nothing discharges to the grid until the schedule is
enabled, so the target and the window are written first and the switch last. A write that fails
stops the sequence before the switch, so a half-set schedule is never switched on. Turning a
schedule off writes the switch only.

The client has no policy. A host that must not export does not call this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import time
from typing import Any

from ._entity import GetState, clamp_to_entity, read_int
from .controls import ClockWriter, control_entity
from .defaults import GIVTCP_MAX_CHARGE_TARGET_PCT, GIVTCP_MIN_CHARGE_TARGET_PCT
from .discovery import MAX_CHARGE_SLOTS, UNUSED_SLOT_TIME, clock_time, device_prefix
from .model import SlotKind, Window
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
        state = self._get_state(entity) if entity else None
        if state is None or str(state.state) not in ("on", "off"):
            return None
        return str(state.state) == "on"

    # ── Writes ────────────────────────────────────────────────────────────────

    async def apply_slot(
        self, cfg: Mapping[str, Any], kind: SlotKind, slot: int, window: Window
    ) -> WriteStatus:
        """Write one slot's start and end and nothing else, in the order windows.py gives."""
        prefix = device_prefix(cfg)
        highest = MAX_DISCHARGE_SLOTS if kind is SlotKind.DISCHARGE else MAX_CHARGE_SLOTS
        start, end = window
        if not prefix or not _slot_ok(slot, highest) or start == end:
            return WriteStatus.REFUSED
        starts, ends = slot_entities(prefix, kind, slot)
        name = f"{kind.value} slot {slot}"
        clock = ClockWriter(self._writer, self._get_state)
        return await clock.write_window((starts, ends), (start, end), name)

    async def clear_slot(self, cfg: Mapping[str, Any], kind: SlotKind, slot: int) -> WriteStatus:
        """Set a slot back to unused (00:00:00 to 00:00:00)."""
        prefix = device_prefix(cfg)
        highest = MAX_DISCHARGE_SLOTS if kind is SlotKind.DISCHARGE else MAX_CHARGE_SLOTS
        if not prefix or not _slot_ok(slot, highest):
            return WriteStatus.REFUSED
        starts, ends = slot_entities(prefix, kind, slot)
        name = f"clear {kind.value} slot {slot}"
        clock = ClockWriter(self._writer, self._get_state)
        unused = time(0, 0)
        return await clock.write_window((starts, ends), (unused, unused), name)

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
