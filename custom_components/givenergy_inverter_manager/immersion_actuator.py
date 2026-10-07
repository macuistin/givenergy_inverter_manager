"""
immersion_actuator.py: turns the engine's immersion decision into calls on the real switch.

The coordinator owns one ImmersionActuator. It holds the state machine that sits between
the engine's decision (CoordinatorData.should_divert_immersion) and the real switch:

  * the manual override and run-to-target (heat until the water reaches its target, or for
    SENSOR_OUTAGE_HOLD_LIMIT_S when no temperature can be read),
  * the cooldown after a write, which stops the switch chattering,
  * detection of a toggle made by something else (an automation, the wall button),
  * the overheat bypass: a turn-off is never held back while the water is above target,
  * dry run: the action is recorded, not sent.

It runs once per update cycle, so diversion works even when the managed switch entity is
disabled. The entity is a thin view and command on top of it.

The actuator holds no Home Assistant objects. The coordinator hands it ImmersionPorts.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .const import IMMERSION_SWITCH_COOLDOWN_MINUTES, SENSOR_OUTAGE_HOLD_LIMIT_S
from .core.engine import CoordinatorData
from .core.timeutil import elapsed_seconds, real_time_after
from .logging import get_logger

_LOG = get_logger(__name__)


@dataclass(frozen=True)
class ImmersionPorts:
    """The outside world, as callables. `send` waits for the call; the other does not."""

    switch_entity: Callable[[], str | None]
    read_state: Callable[[str], Any]
    send: Callable[[str, str], Awaitable[None]]
    send_in_background: Callable[[str, str], None]
    is_dry_run: Callable[[], bool]
    record_skipped: Callable[[str], None]
    target_temp: Callable[[], float]
    now: Callable[[], datetime]


@dataclass(frozen=True)
class _Observation:
    """What the cycle sees of the real switch."""

    is_on: bool
    within_cooldown: bool


class ImmersionActuator:
    """Decision-to-actuation state machine for the immersion heater switch."""

    def __init__(self, ports: ImmersionPorts) -> None:
        self._ports = ports
        # Tri-state: True forces on, False forces off, None lets the engine decide.
        self.override: bool | None = None
        # True while a manual or external turn-on runs until the water reaches target.
        self.manual_run_to_target: bool = False
        # When the run first found no temperature to read. None while one is readable.
        self._temp_unreadable_since: datetime | None = None
        # Until this instant, automatic writes are held back.
        self.cooldown_until: datetime | None = None
        # What this actuator last commanded, to tell its own writes from external ones.
        self.last_commanded_on: bool | None = None

    # ── Commands from the managed switch entity ───────────────────────────────

    async def manual_on(self) -> None:
        """Force the heater on and run until the water reaches the target temperature."""
        self._start_manual_run()
        self.last_commanded_on = True
        await self._send_manual("turn_on")

    async def manual_off(self) -> None:
        """Turn the heater off now. Automatic control resumes after the cooldown."""
        self._end_manual_run()
        self._start_cooldown(self._ports.now())
        self.last_commanded_on = False
        await self._send_manual("turn_off")

    async def _send_manual(self, service: str) -> None:
        switch = self._ports.switch_entity()
        if switch and not self._ports.is_dry_run():
            await self._ports.send(service, switch)

    # ── Steps of the update cycle ─────────────────────────────────────────────

    def release_if_at_target(self, water_temp: float | None) -> None:
        """End a manual run once the water reaches target, or the temperature stays unreadable.

        With no temperature to read (no sensor, or one that is unavailable) a run cannot
        reach a target. It lasts SENSOR_OUTAGE_HOLD_LIMIT_S, the time the engine also
        holds a running heater through a sensor outage, then control returns to automatic.
        """
        if not self.manual_run_to_target:
            self._temp_unreadable_since = None
            return
        if water_temp is None:
            self._release_if_unreadable_too_long()
        elif water_temp >= self._ports.target_temp():
            _LOG.info("Immersion reached target %.1f°C — releasing manual override", water_temp)
            self._end_manual_run()
        else:
            self._temp_unreadable_since = None

    def _release_if_unreadable_too_long(self) -> None:
        now = self._ports.now()
        if self._temp_unreadable_since is None:
            self._temp_unreadable_since = now
        if elapsed_seconds(self._temp_unreadable_since, now) >= SENSOR_OUTAGE_HOLD_LIMIT_S:
            _LOG.info(
                "Immersion has no temperature reading after %ds — releasing manual override",
                SENSOR_OUTAGE_HOLD_LIMIT_S,
            )
            self._end_manual_run()

    def _start_manual_run(self) -> None:
        self.override = True
        self.manual_run_to_target = True
        self._temp_unreadable_since = None
        self.cooldown_until = None

    def _end_manual_run(self) -> None:
        self.manual_run_to_target = False
        self.override = None
        self._temp_unreadable_since = None

    def annotate_divert_reason(self, data: CoordinatorData, water_temp: float | None) -> None:
        """Say on the snapshot that a manual run-to-target is in charge."""
        if not (self.manual_run_to_target and data.should_divert_immersion):
            return
        reason = f"Manual — running to {self._ports.target_temp():.0f}°C"
        if water_temp is not None:
            reason += f" ({water_temp:.1f}°C now)"
        data.divert_reason = reason

    def actuate(self, data: CoordinatorData, now: datetime) -> None:
        """Bring the real switch in line with the decision, or notice an external toggle."""
        switch = self._ports.switch_entity()
        if not switch:
            return
        seen = self._observe(switch, now)
        if self._toggled_externally(seen):
            self._adopt_external_toggle(seen, now)
        elif data.should_divert_immersion != seen.is_on:
            self._drive_switch(switch, data, now, seen)

    # ── Observation ───────────────────────────────────────────────────────────

    def _observe(self, switch: str, now: datetime) -> _Observation:
        state = self._ports.read_state(switch)
        within = self.cooldown_until is not None and now < self.cooldown_until
        return _Observation(is_on=state is not None and state.state == "on", within_cooldown=within)

    def _toggled_externally(self, seen: _Observation) -> bool:
        """True when the switch differs from our last command outside a cooldown."""
        return (
            self.last_commanded_on is not None
            and seen.is_on != self.last_commanded_on
            and not seen.within_cooldown
        )

    # ── External toggles ──────────────────────────────────────────────────────

    def _adopt_external_toggle(self, seen: _Observation, now: datetime) -> None:
        if seen.is_on:
            self._adopt_external_turn_on()
        else:
            self._adopt_external_turn_off(now)
        self.last_commanded_on = seen.is_on

    def _adopt_external_turn_on(self) -> None:
        """Run to the target temperature, as if the user pressed the managed switch."""
        _LOG.info("Immersion turned on externally — running to target temperature")
        self._start_manual_run()

    def _adopt_external_turn_off(self, now: datetime) -> None:
        """Respect it, and hold off so the heater is not turned straight back on."""
        _LOG.info(
            "Immersion turned off externally — respecting for %d min",
            IMMERSION_SWITCH_COOLDOWN_MINUTES,
        )
        self._end_manual_run()
        self._start_cooldown(now)

    # ── Automatic writes ──────────────────────────────────────────────────────

    def _drive_switch(
        self, switch: str, data: CoordinatorData, now: datetime, seen: _Observation
    ) -> None:
        if seen.within_cooldown and not self._water_above_target(data):
            self._log_held_back(data)
            return
        service = "turn_on" if data.should_divert_immersion else "turn_off"
        if self._ports.is_dry_run():
            self._record_dry_run(service, data)
            return
        _LOG.debug("Immersion: %s (reason: %s)", service, data.divert_reason)
        self._ports.send_in_background(service, switch)
        self._start_cooldown(now)
        self.last_commanded_on = data.should_divert_immersion

    def _water_above_target(self, data: CoordinatorData) -> bool:
        """A turn-off is never delayed while the water is at or above target (overheat)."""
        temp = data.immersion_temp
        return (
            not data.should_divert_immersion
            and temp is not None
            and temp >= self._ports.target_temp()
        )

    def _log_held_back(self, data: CoordinatorData) -> None:
        _LOG.debug(
            "Immersion: skipping %s, cooldown active until %s",
            "turn_on" if data.should_divert_immersion else "turn_off",
            self.cooldown_until.strftime("%H:%M:%S") if self.cooldown_until else "",
        )

    def _record_dry_run(self, service: str, data: CoordinatorData) -> None:
        action = f"Would {service} immersion heater (reason: {data.divert_reason})"
        _LOG.info("DRY RUN: %s", action)
        self._ports.record_skipped(action)

    def _start_cooldown(self, now: datetime) -> None:
        self.cooldown_until = real_time_after(
            now, timedelta(minutes=IMMERSION_SWITCH_COOLDOWN_MINUTES)
        )
