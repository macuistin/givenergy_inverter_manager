"""
writer.py: verified, serialised writes to GivTCP entities.

GivEnergy inverters have about 1M lifetime register writes, so every write goes
through one path that:

  1. reads the entity first and skips the write when it is already at the value,
  2. skips a value that was the last one sent to the entity inside the cooldown window,
  3. calls the service once and polls the state back with a growing delay, sending again
     only when no poll showed the value,
  4. counts each accepted service call towards the lifetime register total.

Every write returns a WriteStatus, so a caller can tell a value that was sent from one that was
skipped, refused or never read back. A write to a missing or unavailable entity is refused
before any call is made.

The write observer hears about each call before it is sent, and again when it was
accepted or failed. The write log uses that to tell the manager's own writes from
changes made by anyone else.

Writes are serialised with a lock. Two callers (the charge-target task and the
cheap-rate floor in the update cycle) never interleave their service calls.

A confirmation listener hears when a write was read back as the requested value, and when
every attempt read back the old one. The coordinator uses it to raise and clear a repair.

The writer holds no Home Assistant objects. The host hands it three callables, so the tests
drive it with a fake state dict and a recording bus. A call that fails raises ServiceCallError.
The per-step read-back lines are written only while the host's `verbose` callable says yes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from ._entity import EntityState, GetState
from .defaults import (
    GIVTCP_MAX_WRITE_RETRIES,
    GIVTCP_MIN_WRITE_INTERVAL_S,
    GIVTCP_WRITE_LIFETIME_WARN,
    GIVTCP_WRITE_RETRY_SLEEP_S,
)
from .discovery import clock_time
from .errors import ServiceCallError
from .outcome import OUTCOME_FORMAT, WriteOutcome
from .status import WriteStatus
from .values import WriteRecord

_LOG = logging.getLogger(__name__)

CallService = Callable[[str, str, dict[str, Any]], Awaitable[None]]
CountListener = Callable[[int], None]


def _never() -> bool:
    return False


class WriteObserver(Protocol):
    """Hears about each service call the writer makes to the inverter entities."""

    def before_write(self, record: WriteRecord) -> None:
        """The call is about to be sent. An entity can report the new value before it returns."""

    def after_write(self, record: WriteRecord) -> None:
        """The call was accepted."""

    def write_failed(self, record: WriteRecord) -> None:
        """The call raised, so nothing was written."""


class _NoObserver:
    """The default observer: nobody is listening."""

    def before_write(self, record: WriteRecord) -> None:
        pass

    def after_write(self, record: WriteRecord) -> None:
        pass

    def write_failed(self, record: WriteRecord) -> None:
        pass


class ConfirmationListener(Protocol):
    """Hears whether the inverter took each value the writer sent."""

    def confirmed(self, write: VerifiedWrite) -> None:
        """The entity holds the value, found before the call or read back after it."""

    def not_confirmed(self, write: VerifiedWrite) -> None:
        """Every attempt read back something other than the value."""


class _NoConfirmations:
    """The default listener: nobody is listening."""

    def confirmed(self, write: VerifiedWrite) -> None:
        pass

    def not_confirmed(self, write: VerifiedWrite) -> None:
        pass


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
    matches: Callable[[EntityState | None], bool]
    fail_if_missing: bool = False

    @property
    def entity_id(self) -> str:
        return str(self.payload["entity_id"])

    @property
    def cooldown_key(self) -> tuple[str, object]:
        return (self.entity_id, self.value)


def state_as_int(state: EntityState | None) -> int | None:
    """Return a state object's value as an int, or None if absent or not numeric."""
    try:
        return int(float(state.state)) if state else None
    except (ValueError, TypeError):
        return None


def _shown_state(state: EntityState | None) -> object:
    """The state to print in a log line, 'unknown' for a missing entity."""
    return state.state if state else "unknown"


def switch_write(entity_id: str, wanted: SwitchState, name: str, step: int) -> VerifiedWrite:
    wants_on = wanted is SwitchState.ON

    def is_wanted(state: EntityState | None) -> bool:
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


def select_write(entity_id: str, option: str, name: str, step: int) -> VerifiedWrite:
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


def number_write(entity_id: str, number: int, name: str, step: int) -> VerifiedWrite:
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


def time_write(entity_id: str, wanted: str, name: str, step: int) -> VerifiedWrite:
    """A write to a `time` entity. `wanted` is HH:MM:SS, compared as HH:MM."""
    return VerifiedWrite(
        domain="time",
        service="set_value",
        payload={"entity_id": entity_id, "time": wanted},
        value=wanted,
        shown=wanted,
        name=name,
        step=step,
        matches=lambda state: clock_time(state) == wanted[:5],
        fail_if_missing=True,
    )


@dataclass
class WriteTuning:
    """How hard the writer tries to get one value onto the inverter.

    A value is sent at most *max_sends* times. After each send the entity is read back up to
    *polls* times, the first after *poll_sleep_s* seconds and each later one after twice the
    wait before it. The value is sent again only when none of those reads showed it, so one
    logical write costs one register write unless GivTCP is slow to publish. None takes the
    default from defaults.py.
    """

    max_sends: int | None = None
    polls: int = 3
    poll_sleep_s: float | None = None


class GivTCPWriter:
    """Writes GivTCP entities with read-before-write, cooldown, retry and counting."""

    def __init__(
        self,
        get_state: GetState,
        call_service: CallService,
        on_count_change: CountListener,
        observer: WriteObserver | None = None,
    ) -> None:
        """Set up a writer. Tune the retries through `tuning` and seed the count with seed_count."""
        self.verbose: Callable[[], bool] = _never
        self._get_state = get_state
        self._call_service = call_service
        self._on_count_change = on_count_change
        self._observer: WriteObserver = observer or _NoObserver()
        self._confirmations: ConfirmationListener = _NoConfirmations()
        self._lock = asyncio.Lock()
        self.tuning = WriteTuning()
        self._write_count = 0
        self._count_warned = False
        self.last_write_time: dict[tuple[str, object], float] = {}

    @property
    def write_count(self) -> int:
        """Register writes made so far, including any count the host seeded."""
        return self._write_count

    def state_of(self, entity_id: str) -> EntityState | None:
        """The entity's state as the writer sees it, for a caller that orders its writes."""
        return self._get_state(entity_id)

    def seed_count(self, count: int) -> None:
        """Start from a lifetime register count the host kept, so the warning still fires."""
        self._write_count = count
        self._count_warned = count >= GIVTCP_WRITE_LIFETIME_WARN

    def listen_for_confirmations(self, listener: ConfirmationListener) -> None:
        """Tell *listener* whether the inverter took each value from now on."""
        self._confirmations = listener

    # ── Typed entry points ────────────────────────────────────────────────────

    async def set_switch(
        self, entity_id: str | None, wanted: SwitchState, name: str, step: int = 0
    ) -> WriteStatus:
        """Turn a GivTCP switch on or off. The status says whether it was."""
        if not entity_id:
            return WriteStatus.REFUSED
        return await self.write_verified(switch_write(entity_id, wanted, name, step))

    async def set_select(
        self, entity_id: str | None, option: str, name: str, step: int = 0
    ) -> WriteStatus:
        """Select an option on a GivTCP select. The status says whether it was."""
        if not entity_id:
            return WriteStatus.REFUSED
        return await self.write_verified(select_write(entity_id, option, name, step))

    async def set_time(
        self, entity_id: str | None, value: str, name: str, step: int = 0
    ) -> WriteStatus:
        """Set a GivTCP time entity to HH:MM:SS. The status says whether it was."""
        if not entity_id:
            return WriteStatus.REFUSED
        return await self.write_verified(time_write(entity_id, value, name, step))

    async def set_number(
        self, entity_id: str | None, number: int, name: str, step: int = 0
    ) -> WriteStatus:
        """Set a GivTCP number. The status says whether it was."""
        if not entity_id:
            return WriteStatus.REFUSED
        return await self.write_verified(number_write(entity_id, number, name, step))

    # ── The one write path ────────────────────────────────────────────────────

    async def write_verified(self, write: VerifiedWrite) -> WriteStatus:
        """Write once, serialised, and confirm by reading the state back.

        REFUSED comes back without a call when the entity is missing or unavailable, and
        ALREADY_SET when it holds the value. COOLDOWN means the last value sent to the entity
        was this one, less than the cooldown ago. A send that no poll confirms is UNCONFIRMED:
        it is logged, reported to the confirmation listener and its cooldown is released, so
        the next call can try again.
        """
        async with self._lock:
            current = self._get_state(write.entity_id)
            if current is None or str(current.state) == "unavailable":
                _LOG.warning("%s: %s is missing or unavailable, not writing", write.name,
                             write.entity_id)
                return WriteStatus.REFUSED
            if write.matches(current):
                _LOG.debug("%s: already %s, skipping write", write.name, write.shown)
                self._confirmations.confirmed(write)
                return WriteStatus.ALREADY_SET
            if self.cooldown_active(write.entity_id, write.name, write.value):
                return WriteStatus.COOLDOWN
            self.start_cooldown(write.entity_id, write.value)
            return await self._send_until_confirmed(write)

    async def _send_until_confirmed(self, write: VerifiedWrite) -> WriteStatus:
        sends = self.tuning.max_sends or GIVTCP_MAX_WRITE_RETRIES
        for send in range(1, sends + 1):
            if not await self._send(write):
                return WriteStatus.FAILED
            outcome = await self._poll(write)
            if outcome is not None:
                return outcome
            if send < sends:
                _LOG.warning(
                    "%s: sent %s but it was not read back, sending again", write.name, write.shown
                )
        _LOG.warning(
            "%s: wrote %s but could not confirm it after %d send(s)",
            write.name,
            write.shown,
            sends,
        )
        self.release_cooldown(write)
        self._confirmations.not_confirmed(write)
        return WriteStatus.UNCONFIRMED

    async def _poll(self, write: VerifiedWrite) -> WriteStatus | None:
        """Read the entity back with a doubling delay. None when no poll showed the value."""
        wait = self.tuning.poll_sleep_s
        delay = GIVTCP_WRITE_RETRY_SLEEP_S if wait is None else wait
        for _ in range(self.tuning.polls):
            await asyncio.sleep(delay)
            delay *= 2
            actual = self._get_state(write.entity_id)
            if actual is None and write.fail_if_missing:
                self._report_vanished(write)
                return WriteStatus.FAILED
            accepted = write.matches(actual)
            self._log_outcome(
                WriteOutcome(
                    write.step, write.entity_id, write.shown, _shown_state(actual), accepted
                )
            )
            if accepted:
                self._confirmations.confirmed(write)
                return WriteStatus.WRITTEN
        return None

    async def _send(self, write: VerifiedWrite) -> bool:
        """Call the write service. On failure, log it and release the cooldown."""
        record = WriteRecord(write.entity_id, str(write.shown), write.name)
        self._observer.before_write(record)
        try:
            await self._call_service(write.domain, write.service, write.payload)
        except ServiceCallError as err:
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
            self._count_write(record)
            return True
        self._observer.write_failed(record)
        self.release_cooldown(write)
        return False

    def _log_outcome(self, outcome: WriteOutcome) -> None:
        if self.verbose():
            _LOG.debug(OUTCOME_FORMAT, *outcome.log_args())

    def _report_vanished(self, write: VerifiedWrite) -> None:
        _LOG.warning(
            "%s: entity %s vanished from HA state machine after write",
            write.name,
            write.entity_id,
        )
        outcome = WriteOutcome(write.step, write.entity_id, write.shown, "unavailable", False)
        self._log_outcome(outcome)

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
        """Record that this value is being written to the entity now.

        The cooldown is on the last value sent, so a different value is never held back by an
        older one: sending A, then B, then A sends A the second time.
        """
        for key in [k for k in self.last_write_time if k[0] == entity_id]:
            del self.last_write_time[key]
        self.last_write_time[(entity_id, value)] = time.monotonic()

    def is_unconfirmed(self, write: VerifiedWrite) -> bool:
        """True when the entity does not hold the value now, after the writer's own read-backs."""
        return not write.matches(self._get_state(write.entity_id))

    def release_cooldown(self, write: VerifiedWrite) -> None:
        """Let the same value be sent again at once, for a retry of a write that did not take."""
        self.last_write_time.pop(write.cooldown_key, None)

    # ── Lifetime register count ───────────────────────────────────────────────

    def _count_write(self, record: WriteRecord) -> None:
        self._write_count += 1
        self._on_count_change(self._write_count)
        self._observer.after_write(record)
        if self._write_count >= GIVTCP_WRITE_LIFETIME_WARN and not self._count_warned:
            self._count_warned = True
            _LOG.warning(
                "GivTCP register write count has reached %d, approximately 50%% of the "
                "inverter's rated lifetime. Review automation frequency.",
                self._write_count,
            )
