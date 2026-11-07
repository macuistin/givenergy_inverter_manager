"""
battery_hold.py - holds the house battery back while the car charges, and puts the pause back.

The coordinator owns one BatteryHold and calls `run` once per cycle. The decision is in
core/ev_battery_hold.py. This class does the writes through the inverter backend, so they go
through the verified writer, and it keeps what a hold changed:

  * START saves the live pause, then writes a short PauseDischarge window.
  * RENEW writes the next window while the car keeps charging.
  * RELEASE writes the saved pause back once the car has stopped or the switch is off.

The saved pause also goes to a store, so a restart in the middle of a hold still ends it.
Dry run records what would be written and sends nothing. The coordinator does not run a cycle
while the GivTCP feed is not live, so no write is tried then.

The class holds no Home Assistant objects. The coordinator hands it BatteryHoldPorts.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from .core.ev_battery_hold import (
    HoldDecision,
    HoldFacts,
    HoldRecord,
    HoldStep,
    decide_hold,
    hold_ends,
    hold_window,
)
from .lib.givtcp.model import BatteryPause, PauseSetting, Window
from .lib.givtcp.status import WriteStatus
from .logging import get_logger

_LOG = get_logger(__name__)


@dataclass(frozen=True)
class BatteryHoldPorts:
    """The outside world, as callables."""

    read_pause: Callable[[], PauseSetting | None]
    apply_pause: Callable[[BatteryPause, Window | None], Awaitable[WriteStatus]]
    save: Callable[[HoldRecord | None], Awaitable[None]]
    is_dry_run: Callable[[], bool]
    record_skipped: Callable[[str], None]


class BatteryHold:
    """The battery hold: decides each cycle, writes through the ports, remembers its record."""

    def __init__(self, ports: BatteryHoldPorts) -> None:
        self._ports = ports
        self.record: HoldRecord | None = None
        self._car_off_since: datetime | None = None
        self._dry_run_reported = False

    @property
    def holding(self) -> bool:
        return self.record is not None

    def restore(self, record: HoldRecord | None) -> None:
        """Take the record saved before a restart, so the hold it started is ended."""
        self.record = record

    async def run(
        self, *, enabled: bool, car_charging: bool, car_draining: bool, now: datetime
    ) -> None:
        """One cycle: decide, then write when the decision calls for it."""
        facts = self._facts(
            enabled=enabled, car_charging=car_charging, car_draining=car_draining, now=now
        )
        decision = decide_hold(facts)
        if not (enabled and car_draining):
            self._dry_run_reported = False
        if decision.note:
            _LOG.debug("Battery hold not started: %s", decision.note)
        if decision.step is HoldStep.NOTHING:
            return
        if self._ports.is_dry_run():
            self._report_dry_run(decision)
            return
        await self._write(decision, facts)

    def _facts(
        self, *, enabled: bool, car_charging: bool, car_draining: bool, now: datetime
    ) -> HoldFacts:
        if car_charging:
            self._car_off_since = None
        elif self._car_off_since is None:
            self._car_off_since = now
        away = None if car_charging else (now - (self._car_off_since or now)).total_seconds() / 60
        record = self.record
        return HoldFacts(
            enabled=enabled,
            car_draining_battery=car_draining,
            minutes_since_car_charged=away,
            now=now,
            live=None if record else self._ports.read_pause(),
            holding=record is not None,
            hold_ends=record.ends if record else None,
        )

    def _report_dry_run(self, decision: HoldDecision) -> None:
        if self._dry_run_reported:
            return
        self._dry_run_reported = True
        action = {
            HoldStep.START: "Would hold the house battery back while the car charges",
            HoldStep.RENEW: "Would keep holding the house battery back",
            HoldStep.RELEASE: "Would put the battery pause back as it was",
        }[decision.step]
        _LOG.info("DRY RUN: %s", action)
        self._ports.record_skipped(action)

    async def _write(self, decision: HoldDecision, facts: HoldFacts) -> None:
        # A start has the live pause in the facts and the other steps have the record. The
        # decision only gives them when they are there.
        if self.record is None:
            if facts.live is not None:
                await self._start(facts.live, facts.now)
        elif decision.step is HoldStep.RELEASE:
            await self._release(self.record)
        else:
            await self._renew(self.record, facts.now)

    async def _start(self, prior: PauseSetting, now: datetime) -> None:
        ends = hold_ends(now)
        # The record goes to the store before the write, so a stop between the two still
        # leaves the pause to write back.
        record = HoldRecord(prior, ends)
        await self._ports.save(record)
        if await self._ports.apply_pause(BatteryPause.DISCHARGE, hold_window(now)):
            self.record = record
            _LOG.info("Holding the house battery back until %s", ends.strftime("%H:%M"))
            return
        await self._ports.save(None)
        _LOG.warning("The inverter did not take the battery hold")

    async def _renew(self, record: HoldRecord, now: datetime) -> None:
        if await self._ports.apply_pause(BatteryPause.DISCHARGE, hold_window(now)):
            self.record = HoldRecord(record.prior, hold_ends(now))
            await self._ports.save(self.record)
        else:
            _LOG.warning("The inverter did not take the renewed battery hold")

    async def _release(self, record: HoldRecord) -> None:
        prior = record.prior
        if await self._ports.apply_pause(prior.pause, prior.window):
            self.record = None
            await self._ports.save(None)
            _LOG.info("Put the battery pause back to %s", prior.pause.value)
        else:
            _LOG.warning("The inverter did not take the battery pause back, will try again")
