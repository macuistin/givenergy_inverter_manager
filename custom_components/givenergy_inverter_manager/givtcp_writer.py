"""
givtcp_writer.py: verified, serialised writes to GivTCP entities.

GivEnergy inverters have about 1M lifetime register writes, so every write goes
through one path that:

  1. reads the entity first and skips the write when it is already at the value,
  2. skips a value that was written inside the cooldown window,
  3. calls the service and reads the state back, retrying a mismatch,
  4. counts each accepted service call towards the lifetime register total.

Writes are serialised with a lock. Two callers (the charge-target task and the
cheap-rate floor in the update cycle) never interleave their service calls.

The writer holds no Home Assistant objects. The coordinator hands it three
callables, so the tests drive it with a fake state dict and a recording bus.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .const import (
    GIVTCP_MAX_WRITE_RETRIES,
    GIVTCP_MIN_WRITE_INTERVAL_S,
    GIVTCP_WRITE_LIFETIME_WARN,
    GIVTCP_WRITE_RETRY_SLEEP_S,
)
from .logging import get_logger, log_givtcp_write

_LOG = get_logger(__name__)

GetState = Callable[[str], Any]
CallService = Callable[[str, str, dict[str, Any]], Awaitable[None]]
CountListener = Callable[[int], None]


class SwitchState(StrEnum):
    """The two states a GivTCP switch can be asked to take."""

    ON = "on"
    OFF = "off"


@dataclass(frozen=True)
class VerifiedWrite:
    """One service call plus how to tell that the entity took the value.

    `value` is the cooldown key. `shown` is what the logs print as the written value.
    `matches` receives the entity state (None when the entity is missing) and says
    whether it holds the requested value. `fail_if_missing` makes an entity that
    vanishes after the call a failure instead of a retry.
    """

    domain: str
    service: str
    payload: dict[str, Any]
    value: object
    shown: object
    name: str
    step: int
    matches: Callable[[Any], bool]
    fail_if_missing: bool = False

    @property
    def entity_id(self) -> str:
        return str(self.payload["entity_id"])

    @property
    def cooldown_key(self) -> tuple[str, object]:
        return (self.entity_id, self.value)


def state_as_int(state: Any) -> int | None:
    """Return a state object's value as an int, or None if absent or not numeric."""
    try:
        return int(float(state.state)) if state else None
    except (ValueError, TypeError):
        return None


def _shown_state(state: Any) -> object:
    """The state to print in a log line, 'unknown' for a missing entity."""
    return state.state if state else "unknown"


def _switch_write(entity_id: str, wanted: SwitchState, name: str, step: int) -> VerifiedWrite:
    wants_on = wanted is SwitchState.ON

    def is_wanted(state: Any) -> bool:
        # A missing or unavailable switch reads as off.
        return (state is not None and state.state == "on") == wants_on

    return VerifiedWrite(
        domain="switch",
        service="turn_on" if wants_on else "turn_off",
        payload={"entity_id": entity_id},
        value=wanted,
        shown=wanted.value,
        name=name,
        step=step,
        matches=is_wanted,
    )


def _select_write(entity_id: str, option: str, name: str, step: int) -> VerifiedWrite:
    return VerifiedWrite(
        domain="select",
        service="select_option",
        payload={"entity_id": entity_id, "option": option},
        value=option,
        shown=option,
        name=name,
        step=step,
        matches=lambda state: state is not None and state.state == option,
        fail_if_missing=True,
    )


def _number_write(entity_id: str, number: int, name: str, step: int) -> VerifiedWrite:
    return VerifiedWrite(
        domain="number",
        service="set_value",
        payload={"entity_id": entity_id, "value": number},
        value=number,
        shown=number,
        name=name,
        step=step,
        matches=lambda state: state_as_int(state) == number,
    )


class GivTCPWriter:
    """Writes GivTCP entities with read-before-write, cooldown, retry and counting."""

    def __init__(
        self,
        get_state: GetState,
        call_service: CallService,
        on_count_change: CountListener,
    ) -> None:
        self._get_state = get_state
        self._call_service = call_service
        self._on_count_change = on_count_change
        self._lock = asyncio.Lock()
        self.write_count: int = 0
        self.last_write_time: dict[tuple[str, object], float] = {}

    # ── Typed entry points ────────────────────────────────────────────────────

    async def set_switch(
        self, entity_id: str | None, wanted: SwitchState, name: str, step: int = 0
    ) -> bool:
        """Turn a GivTCP switch on or off. False when it could not be written."""
        if not entity_id:
            return False
        return await self.write_verified(_switch_write(entity_id, wanted, name, step))

    async def set_select(
        self, entity_id: str | None, option: str, name: str, step: int = 0
    ) -> bool:
        """Select an option on a GivTCP select. False when it could not be written."""
        if not entity_id:
            return False
        return await self.write_verified(_select_write(entity_id, option, name, step))

    async def set_number(
        self, entity_id: str | None, number: int, name: str, step: int = 0
    ) -> bool:
        """Set a GivTCP number. False when it could not be written."""
        if not entity_id:
            return False
        return await self.write_verified(_number_write(entity_id, number, name, step))

    # ── The one write path ────────────────────────────────────────────────────

    async def write_verified(self, write: VerifiedWrite) -> bool:
        """Write once, serialised, and confirm by reading the state back.

        Returns True when the entity is at the value or the value was sent. A
        read-back that never matches is logged but still counts as sent, because
        GivTCP can be slow to publish the new state. Returns False when the
        service call raised or the entity is unusable.
        """
        async with self._lock:
            if self._already_at_value(write) or self.cooldown_active(
                write.entity_id, write.name, write.value
            ):
                return True
            self.start_cooldown(write.entity_id, write.value)
            return await self._send_until_confirmed(write)

    def _already_at_value(self, write: VerifiedWrite) -> bool:
        current = self._get_state(write.entity_id)
        if current is None or not write.matches(current):
            return False
        _LOG.debug("%s: already %s, skipping write", write.name, write.shown)
        return True

    async def _send_until_confirmed(self, write: VerifiedWrite) -> bool:
        for attempt in range(1, GIVTCP_MAX_WRITE_RETRIES + 1):
            if not await self._send(write):
                return False
            await asyncio.sleep(GIVTCP_WRITE_RETRY_SLEEP_S)
            actual = self._get_state(write.entity_id)
            if actual is None and write.fail_if_missing:
                self._report_vanished(write)
                return False
            accepted = write.matches(actual)
            log_givtcp_write(
                _LOG, write.step, write.entity_id, write.shown, _shown_state(actual), accepted
            )
            if accepted:
                return True
            self._warn_mismatch(write, actual, attempt)
        _LOG.warning(
            "%s: wrote %s but could not confirm after %d attempts",
            write.name,
            write.shown,
            GIVTCP_MAX_WRITE_RETRIES,
        )
        return True

    async def _send(self, write: VerifiedWrite) -> bool:
        """Call the write service. On failure, log it and release the cooldown."""
        try:
            await self._call_service(write.domain, write.service, write.payload)
        except HomeAssistantError as err:
            _LOG.warning(
                "%s: %s.%s on %s failed: %s",
                write.name,
                write.domain,
                write.service,
                write.entity_id,
                err,
            )
        except Exception:
            _LOG.exception(
                "%s: unexpected error calling %s.%s on %s",
                write.name,
                write.domain,
                write.service,
                write.entity_id,
            )
        else:
            self._count_write()
            return True
        self.last_write_time.pop(write.cooldown_key, None)
        return False

    @staticmethod
    def _report_vanished(write: VerifiedWrite) -> None:
        _LOG.warning(
            "%s: entity %s vanished from HA state machine after write",
            write.name,
            write.entity_id,
        )
        log_givtcp_write(_LOG, write.step, write.entity_id, write.shown, "unavailable", False)

    @staticmethod
    def _warn_mismatch(write: VerifiedWrite, actual: Any, attempt: int) -> None:
        if attempt >= GIVTCP_MAX_WRITE_RETRIES:
            return
        _LOG.warning(
            "%s: attempt %d/%d: wrote %s but read back %s, retrying",
            write.name,
            attempt,
            GIVTCP_MAX_WRITE_RETRIES,
            write.shown,
            _shown_state(actual),
        )

    # ── Cooldown ──────────────────────────────────────────────────────────────

    def cooldown_active(self, entity_id: str, name: str, value: object) -> bool:
        """True when this value was written to the entity inside the cooldown window."""
        last = self.last_write_time.get((entity_id, value))
        if last is None:
            return False
        elapsed = time.monotonic() - last
        if elapsed >= GIVTCP_MIN_WRITE_INTERVAL_S:
            return False
        _LOG.debug(
            "%s: write cooldown active, %.0fs remaining before next write is allowed",
            name,
            GIVTCP_MIN_WRITE_INTERVAL_S - elapsed,
        )
        return True

    def start_cooldown(self, entity_id: str, value: object) -> None:
        """Record that this value is being written to the entity now."""
        self.last_write_time[(entity_id, value)] = time.monotonic()

    # ── Lifetime register count ───────────────────────────────────────────────

    def _count_write(self) -> None:
        self.write_count += 1
        self._on_count_change(self.write_count)
        if self.write_count == GIVTCP_WRITE_LIFETIME_WARN:
            _LOG.warning(
                "GivTCP register write count has reached %d, approximately 50%% of the "
                "inverter's rated lifetime. Review automation frequency.",
                self.write_count,
            )
