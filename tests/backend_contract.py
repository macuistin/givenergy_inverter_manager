"""What any inverter backend must do, written once.

A backend test module subclasses ``BackendContract`` and provides a ``harness`` fixture. The
harness is the only code that knows how the inverter side looks: it publishes readings in the
backend's own convention, breaks the feed, plants a charge slot and reports what reached the
device. The contract calls the backend and asserts through the harness.

Used by ``tests/inverter/test_backend_contract.py`` (the fake backend and the GivTCP adapter
over a plain dict of states) and ``tests/ha_e2e/test_backend_contract_e2e.py`` (the GivTCP
adapter over ``givtcp_mock`` in a real Home Assistant). A second backend starts from
a passing contract.

Dry run is the coordinator's check, so a backend never sees a write that is held back. The
contract's dry-run clause is the other half: asking a backend to read, to report the feed or
to list slots writes nothing.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any, Protocol

from custom_components.givenergy_inverter_manager.core.inverter_values import (
    ChargePlan,
    FeedState,
)
from custom_components.givenergy_inverter_manager.inverter.backend import InverterBackend

START, END = time(0, 30), time(4, 30)
START_TEXT, END_TEXT = "00:30:00", "04:30:00"
UNUSED = "00:00:00"


class Harness(Protocol):
    """The inverter side of one backend under test."""

    backend: InverterBackend
    cfg: dict[str, Any]

    @property
    def now(self) -> datetime: ...

    def publish(
        self, *, solar_w: float, soc: float, charging_w: float, import_w: float, load_w: float
    ) -> None:
        """Publish live readings. Positive charging_w charges, positive import_w imports."""

    def go_silent(self) -> None:
        """The solar and battery entities become unavailable."""

    def pause(self) -> None:
        """The inverter integration reports that it has paused its connection."""

    def set_target(self, soc: int) -> None: ...

    def set_other_slot(self, number: int, start: str, end: str) -> None: ...

    def fail_target_writes(self) -> None: ...

    def target(self) -> int: ...

    def enable_target(self) -> bool: ...

    def window(self) -> tuple[str, str]: ...

    def other_slot(self, number: int) -> tuple[str, str]: ...

    def device_writes(self) -> int:
        """How many writes have reached the inverter."""


class BackendContract:
    """Subclass and provide a ``harness`` fixture."""

    # ── read ──────────────────────────────────────────────────────────────────

    def test_read_gives_power_in_the_integration_convention(self, harness):
        harness.publish(solar_w=3000, soc=60, charging_w=500, import_w=1200, load_w=1500)

        values = harness.backend.read(harness.cfg)

        assert values.solar_power_w == 3000
        assert values.battery_soc == 60
        assert values.battery_power_w == 500  # positive is charging
        assert values.grid_power_w == 1200  # positive is import
        assert values.house_load_w == 1500
        assert values.unavailable_inputs == ()

    def test_read_gives_power_in_the_integration_convention_when_discharging_and_exporting(
        self, harness
    ):
        harness.publish(solar_w=4000, soc=90, charging_w=-800, import_w=-2000, load_w=1200)

        values = harness.backend.read(harness.cfg)

        assert values.battery_power_w == -800
        assert values.grid_power_w == -2000

    def test_read_names_the_inputs_it_could_not_read(self, harness):
        harness.go_silent()

        values = harness.backend.read(harness.cfg)

        assert {"solar_power", "battery_soc"} <= set(values.unavailable_inputs)

    # ── feed ──────────────────────────────────────────────────────────────────

    def test_a_live_feed_is_publishing(self, harness):
        harness.publish(solar_w=0, soc=50, charging_w=0, import_w=0, load_w=300)

        assert harness.backend.feed_status(harness.cfg, harness.now).is_publishing

    def test_an_unavailable_feed_is_not_publishing(self, harness):
        harness.go_silent()

        status = harness.backend.feed_status(harness.cfg, harness.now)

        assert status.state in (FeedState.SILENT, FeedState.MISSING)
        assert not status.is_publishing

    def test_a_paused_inverter_integration_is_not_publishing(self, harness):
        harness.publish(solar_w=0, soc=50, charging_w=0, import_w=0, load_w=300)
        harness.pause()

        status = harness.backend.feed_status(harness.cfg, harness.now)

        assert status.state is FeedState.PAUSED
        assert not status.is_publishing

    def test_asking_never_writes(self, harness):
        harness.publish(solar_w=0, soc=50, charging_w=0, import_w=0, load_w=300)
        harness.set_other_slot(2, UNUSED, "08:00:00")

        harness.backend.read(harness.cfg)
        harness.backend.feed_status(harness.cfg, harness.now)
        harness.backend.read_charge_window(harness.cfg)
        harness.backend.other_active_charge_slots(harness.cfg)
        harness.backend.watched_entity_ids(harness.cfg)

        assert harness.device_writes() == 0

    # ── the charge plan ───────────────────────────────────────────────────────

    async def test_a_plan_sets_the_target_the_window_and_the_enable_switch(self, harness):
        harness.set_target(50)

        result = await harness.backend.apply_charge_plan(
            harness.cfg, ChargePlan.for_target(80, START, END)
        )

        assert result.ok
        assert harness.target() == 80
        assert harness.window() == (START_TEXT, END_TEXT)
        assert harness.enable_target()

    async def test_a_plan_for_one_hundred_percent_turns_the_enable_switch_off(self, harness):
        harness.set_target(50)

        result = await harness.backend.apply_charge_plan(
            harness.cfg, ChargePlan.for_target(100, START, END)
        )

        assert result.ok
        assert harness.target() == 100
        assert not (harness.enable_target())

    async def test_a_target_that_could_not_be_written_is_reported_and_not_enabled(self, harness):
        harness.set_target(50)
        harness.fail_target_writes()

        result = await harness.backend.apply_charge_plan(
            harness.cfg, ChargePlan.for_target(80, START, END)
        )

        assert not result.ok
        assert "charge target" in result.failed_steps
        assert harness.target() == 50
        assert not (harness.enable_target())

    # ── the cheap-rate floor ──────────────────────────────────────────────────

    async def test_the_floor_raises_a_lower_target_and_enables_it(self, harness):
        harness.set_target(20)

        result = await harness.backend.apply_floor_target(harness.cfg, 40)

        assert result.ok
        assert harness.target() == 40
        assert harness.enable_target()

    async def test_the_floor_keeps_a_higher_target(self, harness):
        harness.set_target(70)

        result = await harness.backend.apply_floor_target(harness.cfg, 40)

        assert result.ok
        assert harness.target() == 70

    async def test_a_floor_whose_target_could_not_be_written_is_reported(self, harness):
        harness.set_target(20)
        harness.fail_target_writes()

        result = await harness.backend.apply_floor_target(harness.cfg, 40)

        assert not result.ok
        assert not (harness.enable_target())

    # ── the window alone ──────────────────────────────────────────────────────

    async def test_the_window_can_be_set_alone_and_read_back(self, harness):
        harness.set_target(50)
        before = harness.enable_target()

        assert await harness.backend.apply_charge_window(harness.cfg, START, END)

        assert harness.window() == (START_TEXT, END_TEXT)
        assert harness.backend.read_charge_window(harness.cfg) == ("00:30", "04:30")
        assert harness.target() == 50
        assert harness.enable_target() == before

    # ── other charge slots ────────────────────────────────────────────────────

    def test_there_are_no_other_slots_on_a_quiet_inverter(self, harness):
        assert list(harness.backend.other_active_charge_slots(harness.cfg)) == []

    async def test_another_slot_is_found_and_can_be_cleared(self, harness):
        harness.set_other_slot(2, UNUSED, "08:00:00")

        [slot] = harness.backend.other_active_charge_slots(harness.cfg)
        assert slot.number == 2
        assert slot.label

        assert await harness.backend.clear_charge_slot(slot)
        assert list(harness.backend.other_active_charge_slots(harness.cfg)) == []
        assert harness.other_slot(2) == (UNUSED, UNUSED)

    # ── identity and the audit list ───────────────────────────────────────────

    def test_the_backend_names_its_inverter_and_the_entities_to_watch(self, harness):
        assert harness.backend.identity.serial
        assert len(harness.backend.watched_entity_ids(harness.cfg)) >= 1
