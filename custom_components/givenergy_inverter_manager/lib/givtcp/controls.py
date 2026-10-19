"""
controls.py: the GivTCP settings that sit beside the charge write.

The battery pause, the battery mode, the reserve, the charge and discharge rates and the
inverter clock. Each write goes through the verified writer, so it is read first, held to the
cooldown, read back and counted. The host decides whether to write (dry run, a frozen feed).

The client has no policy about what to write. Whether to pause, export or change the reserve is
the host's decision, and this integration's host never exports (schedules.py and force.py hold
the export writes). One rule is kept here: a select is written with the option the entity
itself lists. GivTCP releases and people's scripts spell the pause options differently
("PauseDischarge", "Pause Discharge", "Not Paused"), so a wanted option is matched without case,
spaces, underscores or hyphens, and a value the entity does not offer is refused instead of sent.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time
from typing import Any

from ._entity import (
    EntityState,
    GetState,
    clamp_to_entity,
    listed_options,
    read_int,
    squash,
    usable,
)
from .defaults import GIVTCP_MAX_CHARGE_TARGET_PCT, GIVTCP_MIN_CHARGE_TARGET_PCT
from .discovery import battery_pause_entities, clock_time, device_prefix
from .model import BatteryMode, BatteryPause, SelfUseMode, Window
from .status import WriteStatus
from .windows import end_first
from .writer import GivTCPWriter

MODE_SUFFIX = "_mode"
RESERVE_SUFFIX = "_battery_power_reserve"
CHARGE_RATE_SUFFIX = "_battery_charge_rate"
DISCHARGE_RATE_SUFFIX = "_battery_discharge_rate"
CLOCK_SUFFIX = "_invertor_time"

_CLOCK_FORMATS = ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S")


# Other spellings seen for each option, compared after squash.
_PAUSE_ALIASES: dict[BatteryPause, tuple[str, ...]] = {
    BatteryPause.OFF: ("notpaused", "nopause", "off"),
    BatteryPause.CHARGE: (),
    BatteryPause.DISCHARGE: (),
    BatteryPause.BOTH: (),
}


def pick_option(
    state: EntityState | None, wanted: str, aliases: tuple[str, ...] = ()
) -> str | None:
    """The option to send for *wanted*, or None when the entity does not offer it.

    An entity that lists no options is sent *wanted* as it is.
    """
    offered = listed_options(state)
    if offered is None:
        return wanted
    accepted = {squash(wanted), *aliases}
    return next((o for o in offered if squash(o) in accepted), None)


def control_entity(cfg: Mapping[str, Any], domain: str, suffix: str) -> str | None:
    """The entity id of a control for the configured device, None when the prefix is unknown."""
    prefix = device_prefix(cfg)
    return f"{domain}.{prefix}{suffix}" if prefix else None


# ── Reads ─────────────────────────────────────────────────────────────────────


def read_battery_mode(get_state: GetState, cfg: Mapping[str, Any]) -> str | None:
    """The battery mode as GivTCP shows it, None when it is not published or unusable."""
    entity = control_entity(cfg, "select", MODE_SUFFIX)
    return usable(get_state(entity)) if entity else None


def read_reserve(get_state: GetState, cfg: Mapping[str, Any]) -> int | None:
    """The battery power reserve in per cent, None when it is not published or unusable."""
    return read_int(get_state, control_entity(cfg, "number", RESERVE_SUFFIX))


def read_charge_rate(get_state: GetState, cfg: Mapping[str, Any]) -> int | None:
    return read_int(get_state, control_entity(cfg, "number", CHARGE_RATE_SUFFIX))


def read_discharge_rate(get_state: GetState, cfg: Mapping[str, Any]) -> int | None:
    return read_int(get_state, control_entity(cfg, "number", DISCHARGE_RATE_SUFFIX))


def read_inverter_clock(get_state: GetState, cfg: Mapping[str, Any]) -> datetime | None:
    """The inverter's own clock as a naive wall-clock time, None when it cannot be read."""
    entity = control_entity(cfg, "sensor", CLOCK_SUFFIX)
    text = usable(get_state(entity)) if entity else None
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in _CLOCK_FORMATS:
        try:
            return datetime.strptime(text, fmt)  # noqa: DTZ007
        except ValueError:
            continue
    return None


def clock_skew_s(get_state: GetState, cfg: Mapping[str, Any], now: datetime) -> float | None:
    """Seconds the inverter's clock is ahead of *now* (negative when behind).

    *now* is the host's local time. Only its wall-clock reading is used, because the inverter
    clock has no zone. A drifted clock moves the charge window, so the host should warn on it.
    """
    clock = read_inverter_clock(get_state, cfg)
    return None if clock is None else (clock - now.replace(tzinfo=None)).total_seconds()


# ── Writes ────────────────────────────────────────────────────────────────────


class GivTCPControls:
    """The writes beside the charge write, over one verified writer."""

    def __init__(self, writer: GivTCPWriter, get_state: GetState) -> None:
        self._writer = writer
        self._get_state = get_state

    async def apply_battery_mode(
        self, cfg: Mapping[str, Any], mode: BatteryMode | SelfUseMode | str
    ) -> WriteStatus:
        """Select a battery mode such as Eco. False when the entity does not offer it.

        Timed Export is a mode like any other here. Whether to export is the host's decision.
        """
        entity = control_entity(cfg, "select", MODE_SUFFIX)
        if not entity:
            return WriteStatus.REFUSED
        option = pick_option(self._get_state(entity), str(mode))
        if option is None:
            return WriteStatus.REFUSED
        return await self._writer.set_select(entity, option, "battery mode")

    async def apply_reserve(self, cfg: Mapping[str, Any], percent: int) -> WriteStatus:
        """Set the battery power reserve, kept inside the limits the entity publishes."""
        entity = control_entity(cfg, "number", RESERVE_SUFFIX)
        if not entity:
            return WriteStatus.REFUSED
        state = self._get_state(entity)
        value = clamp_to_entity(
            percent, state, GIVTCP_MIN_CHARGE_TARGET_PCT, GIVTCP_MAX_CHARGE_TARGET_PCT
        )
        return await self._writer.set_number(entity, value, "battery reserve")

    async def apply_charge_rate(self, cfg: Mapping[str, Any], watts: int) -> WriteStatus:
        """Set the battery charge rate in watts, kept inside the limits the entity publishes."""
        entity = control_entity(cfg, "number", CHARGE_RATE_SUFFIX)
        return await self._apply_rate(entity, watts, "charge rate")

    async def apply_discharge_rate(self, cfg: Mapping[str, Any], watts: int) -> WriteStatus:
        """Set the battery discharge rate in watts, kept inside the limits the entity publishes."""
        entity = control_entity(cfg, "number", DISCHARGE_RATE_SUFFIX)
        return await self._apply_rate(entity, watts, "discharge rate")

    async def _apply_rate(self, entity: str | None, watts: int, name: str) -> WriteStatus:
        if not entity:
            return WriteStatus.REFUSED
        state = self._get_state(entity)
        return await self._writer.set_number(entity, clamp_to_entity(watts, state), name)

    async def apply_battery_pause(
        self,
        cfg: Mapping[str, Any],
        pause: BatteryPause,
        start: time | None = None,
        end: time | None = None,
    ) -> WriteStatus:
        """Pause the battery for a window, or end the pause with BatteryPause.OFF.

        The window is written before the mode, so a pause never starts on an old window. Ending
        a pause writes the mode only. False when an entity is missing, the mode is not offered,
        the window is empty or a write was not taken. Stops at the first write that fails.
        """
        prefix = device_prefix(cfg)
        if not prefix:
            return WriteStatus.REFUSED
        entities = battery_pause_entities(prefix)
        mode_state = self._get_state(entities.mode)
        option = pick_option(mode_state, pause.value, _PAUSE_ALIASES[pause])
        if mode_state is None or option is None:
            return WriteStatus.REFUSED
        if pause is not BatteryPause.OFF:
            if start is None or end is None or start == end:
                return WriteStatus.REFUSED
            clock = ClockWriter(self._writer, self._get_state)
            written = await clock.write_window(
                (entities.start, entities.end), (start, end), "pause"
            )
            if not written:
                return written
        return await self._writer.set_select(entities.mode, option, "battery pause")


class ClockWriter:
    """Writes a time of day to a GivTCP select or time entity."""

    def __init__(self, writer: GivTCPWriter, get_state: GetState) -> None:
        self._writer = writer
        self._get_state = get_state

    def _target(self, candidates: tuple[str, ...], value: time) -> tuple[str, str] | None:
        """The entity and the text to send for *value*, None when it cannot be written.

        A select is given the option that reads as the same HH:MM. A select that lists no
        options is refused, because nothing says which times it can hold.
        """
        entity = next((e for e in candidates if self._get_state(e) is not None), None)
        if entity is None:
            return None
        text = value.strftime("%H:%M:%S")
        if entity.startswith("time."):
            return entity, text
        offered = listed_options(self._get_state(entity))
        option = next((o for o in offered or [] if clock_time(_Text(o)) == text[:5]), None)
        return None if option is None else (entity, option)

    async def _send(self, target: tuple[str, str], name: str) -> WriteStatus:
        entity, text = target
        if entity.startswith("time."):
            return await self._writer.set_time(entity, text, name)
        return await self._writer.set_select(entity, text, name)

    async def write(self, candidates: tuple[str, ...], value: time, name: str) -> WriteStatus:
        """Write *value* to the first of *candidates* that exists.

        A `time` entity is set with the time service. A value the entity cannot hold is
        refused.
        """
        target = self._target(candidates, value)
        return WriteStatus.REFUSED if target is None else await self._send(target, name)

    def current_start(self, candidates: tuple[str, ...]) -> str | None:
        """The start of the window as the first of *candidates* that exists holds it, HH:MM."""
        found = next((s for e in candidates if (s := self._get_state(e)) is not None), None)
        return clock_time(found)

    async def write_window(
        self,
        entities: tuple[tuple[str, ...], tuple[str, ...]],
        window: Window,
        name: str,
    ) -> WriteStatus:
        """Write a window's start and end, the end first when the window moves later.

        See windows.py for why. Stops at the first write that is not taken.
        """
        starts, ends = entities
        start, end = window
        first = self._target(starts, start)
        second = self._target(ends, end)
        if first is None or second is None:
            return WriteStatus.REFUSED  # nothing is sent unless both ends can be written
        parts = [(first, f"{name} start"), (second, f"{name} end")]
        if end_first(self.current_start(starts), start):
            parts.reverse()
        status = WriteStatus.ALREADY_SET
        for target, label in parts:
            status = await self._send(target, label)
            if not status:
                break
        return status


class _Text:
    """A state-like wrapper so clock_time can read an option's text."""

    def __init__(self, state: str) -> None:
        self.state = state
