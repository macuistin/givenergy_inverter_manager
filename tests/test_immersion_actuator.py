"""
test_immersion_actuator.py: the immersion state machine driven through fake ports.

No coordinator and no Home Assistant. Each test sets the real switch state, hands the
actuator a decision and checks what it sent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_IMMERSION_SWITCH,
    IMMERSION_SWITCH_COOLDOWN_MINUTES,
    SENSOR_OUTAGE_HOLD_LIMIT_S,
)
from custom_components.givenergy_inverter_manager.immersion_actuator import (
    ImmersionActuator,
    ImmersionPorts,
)
from tests.test_coordinator import FakeCoordinator, _cfg

SWITCH = "switch.immersion"
T0 = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
COOLDOWN = timedelta(minutes=IMMERSION_SWITCH_COOLDOWN_MINUTES)


class _World:
    """Fake ports. The real switch state is set by the test."""

    def __init__(self) -> None:
        self.switch_state: str | None = "off"
        self.entity: str | None = SWITCH
        self.dry_run = False
        self.target = 55.0
        self.clock = T0
        self.sent: list[tuple[str, str]] = []
        self.background: list[tuple[str, str]] = []
        self.skipped: list[str] = []

    async def send(self, service: str, entity_id: str) -> None:
        self.sent.append((service, entity_id))

    def ports(self) -> ImmersionPorts:
        return ImmersionPorts(
            switch_entity=lambda: self.entity,
            read_state=lambda _eid: None
            if self.switch_state is None
            else SimpleNamespace(state=self.switch_state),
            send=self.send,
            send_in_background=lambda service, eid: self.background.append((service, eid)),
            is_dry_run=lambda: self.dry_run,
            record_skipped=self.skipped.append,
            target_temp=lambda: self.target,
            now=lambda: self.clock,
        )


@pytest.fixture
def world() -> _World:
    return _World()


@pytest.fixture
def actuator(world) -> ImmersionActuator:
    return ImmersionActuator(world.ports())


def decision(*, on: bool, temp: float | None = 50.0, reason: str = "test"):
    return SimpleNamespace(should_divert_immersion=on, immersion_temp=temp, divert_reason=reason)


class TestAutomatic:
    def test_decision_on_turns_an_off_switch_on(self, actuator, world):
        actuator.actuate(decision(on=True), T0)
        assert world.background == [("turn_on", SWITCH)]
        assert actuator.last_commanded_on is True
        assert actuator.cooldown_until == T0 + COOLDOWN

    def test_decision_off_turns_an_on_switch_off(self, actuator, world):
        world.switch_state = "on"
        actuator.actuate(decision(on=False), T0)
        assert world.background == [("turn_off", SWITCH)]
        assert actuator.last_commanded_on is False

    def test_matching_state_sends_nothing(self, actuator, world):
        world.switch_state = "on"
        actuator.actuate(decision(on=True), T0)
        assert world.background == []
        assert actuator.cooldown_until is None

    def test_missing_switch_state_reads_as_off(self, actuator, world):
        world.switch_state = None
        actuator.actuate(decision(on=True), T0)
        assert world.background == [("turn_on", SWITCH)]

    def test_no_switch_configured_does_nothing(self, actuator, world):
        world.entity = None
        actuator.actuate(decision(on=True), T0)
        assert world.background == []


class TestCooldown:
    def test_a_write_inside_the_cooldown_is_held_back(self, actuator, world):
        actuator.cooldown_until = T0 + COOLDOWN
        actuator.actuate(decision(on=True), T0)
        assert world.background == []

    def test_the_write_goes_through_once_the_cooldown_ends(self, actuator, world):
        actuator.cooldown_until = T0 + COOLDOWN
        actuator.actuate(decision(on=True), T0 + COOLDOWN)
        assert world.background == [("turn_on", SWITCH)]

    @pytest.mark.parametrize(("temp", "sent"), [(55.0, True), (60.0, True), (54.9, False)])
    def test_turn_off_bypasses_the_cooldown_only_at_or_above_target(
        self, actuator, world, temp, sent
    ):
        world.switch_state = "on"
        actuator.cooldown_until = T0 + COOLDOWN
        actuator.actuate(decision(on=False, temp=temp), T0)
        assert bool(world.background) is sent

    def test_turn_off_without_a_temperature_reading_waits(self, actuator, world):
        world.switch_state = "on"
        actuator.cooldown_until = T0 + COOLDOWN
        actuator.actuate(decision(on=False, temp=None), T0)
        assert world.background == []

    def test_turn_on_never_bypasses_the_cooldown(self, actuator, world):
        actuator.cooldown_until = T0 + COOLDOWN
        actuator.actuate(decision(on=True, temp=70.0), T0)
        assert world.background == []


class TestDryRun:
    def test_the_action_is_recorded_not_sent(self, actuator, world):
        world.dry_run = True
        actuator.actuate(decision(on=True, reason="surplus"), T0)
        assert world.background == []
        assert world.skipped == ["Would turn_on immersion heater (reason: surplus)"]

    def test_dry_run_starts_no_cooldown_and_remembers_no_command(self, actuator, world):
        world.dry_run = True
        actuator.actuate(decision(on=True), T0)
        assert actuator.cooldown_until is None
        assert actuator.last_commanded_on is None

    async def test_manual_commands_send_nothing(self, actuator, world):
        world.dry_run = True
        await actuator.manual_on()
        await actuator.manual_off()
        assert world.sent == []


class TestManual:
    async def test_manual_on_sends_and_runs_to_target(self, actuator, world):
        actuator.cooldown_until = T0 + COOLDOWN
        await actuator.manual_on()
        assert world.sent == [("turn_on", SWITCH)]
        assert actuator.override is True
        assert actuator.manual_run_to_target is True
        assert actuator.cooldown_until is None
        assert actuator.last_commanded_on is True

    async def test_manual_off_sends_and_starts_the_cooldown(self, actuator, world):
        actuator.override = True
        actuator.manual_run_to_target = True
        await actuator.manual_off()
        assert world.sent == [("turn_off", SWITCH)]
        assert actuator.override is None
        assert actuator.manual_run_to_target is False
        assert actuator.cooldown_until == T0 + COOLDOWN
        assert actuator.last_commanded_on is False

    async def test_manual_command_without_a_switch_only_sets_state(self, actuator, world):
        world.entity = None
        await actuator.manual_on()
        assert world.sent == []
        assert actuator.override is True


class TestExternalToggle:
    def test_external_turn_on_starts_a_run_to_target(self, actuator, world):
        actuator.last_commanded_on = False
        world.switch_state = "on"
        actuator.actuate(decision(on=False), T0)
        assert actuator.override is True
        assert actuator.manual_run_to_target is True
        assert actuator.cooldown_until is None
        assert actuator.last_commanded_on is True
        assert world.background == []

    def test_external_turn_off_is_respected_for_the_cooldown(self, actuator, world):
        actuator.last_commanded_on = True
        actuator.override = True
        actuator.manual_run_to_target = True
        world.switch_state = "off"
        actuator.actuate(decision(on=True), T0)
        assert actuator.override is None
        assert actuator.manual_run_to_target is False
        assert actuator.cooldown_until == T0 + COOLDOWN
        assert actuator.last_commanded_on is False
        assert world.background == []

    def test_a_toggle_inside_the_cooldown_is_not_external(self, actuator, world):
        actuator.last_commanded_on = True
        actuator.cooldown_until = T0 + COOLDOWN
        world.switch_state = "off"
        actuator.actuate(decision(on=True), T0)
        assert actuator.last_commanded_on is True
        assert actuator.override is None

    def test_nothing_is_external_before_the_first_command(self, actuator, world):
        world.switch_state = "on"
        actuator.actuate(decision(on=False, temp=50.0), T0)
        assert actuator.override is None
        assert world.background == [("turn_off", SWITCH)]


class TestRunToTarget:
    @pytest.mark.parametrize(("temp", "released"), [(55.0, True), (56.0, True), (54.9, False)])
    def test_released_when_the_water_reaches_target(self, actuator, temp, released):
        actuator.override = True
        actuator.manual_run_to_target = True
        actuator.release_if_at_target(temp)
        assert actuator.manual_run_to_target is not released
        assert actuator.override is (None if released else True)

    def test_stays_when_there_is_no_reading(self, actuator):
        actuator.override = True
        actuator.manual_run_to_target = True
        actuator.release_if_at_target(None)
        assert actuator.manual_run_to_target is True

    def test_does_nothing_when_no_run_is_active(self, actuator):
        actuator.override = False
        actuator.release_if_at_target(70.0)
        assert actuator.override is False

    def test_divert_reason_names_the_run_and_the_temperature(self, actuator):
        actuator.manual_run_to_target = True
        data = decision(on=True)
        actuator.annotate_divert_reason(data, 48.25)
        assert data.divert_reason == "Manual — running to 55°C (48.2°C now)"

    def test_divert_reason_without_a_reading(self, actuator):
        actuator.manual_run_to_target = True
        data = decision(on=True)
        actuator.annotate_divert_reason(data, None)
        assert data.divert_reason == "Manual — running to 55°C"

    def test_divert_reason_is_left_alone_when_not_diverting_or_not_manual(self, actuator):
        data = decision(on=True, reason="surplus")
        actuator.annotate_divert_reason(data, 48.0)
        actuator.manual_run_to_target = True
        off = decision(on=False, reason="full")
        actuator.annotate_divert_reason(off, 48.0)
        assert (data.divert_reason, off.divert_reason) == ("surplus", "full")


HOLD = timedelta(seconds=SENSOR_OUTAGE_HOLD_LIMIT_S)


class TestRunWithoutATemperature:
    """No reading means no target to reach, so a manual or external run is bounded in time."""

    def _after(self, world, delta: timedelta) -> None:
        world.clock = T0 + delta

    async def test_a_manual_run_ends_after_the_outage_hold_limit(self, actuator, world):
        await actuator.manual_on()
        actuator.release_if_at_target(None)
        self._after(world, HOLD)
        actuator.release_if_at_target(None)
        assert actuator.override is None
        assert actuator.manual_run_to_target is False

    async def test_a_manual_run_continues_until_the_hold_limit(self, actuator, world):
        await actuator.manual_on()
        actuator.release_if_at_target(None)
        self._after(world, HOLD - timedelta(seconds=1))
        actuator.release_if_at_target(None)
        assert actuator.override is True
        assert actuator.manual_run_to_target is True

    def test_an_external_turn_on_ends_after_the_outage_hold_limit(self, actuator, world):
        actuator.last_commanded_on = False
        world.switch_state = "on"
        actuator.actuate(decision(on=False, temp=None), T0)
        actuator.release_if_at_target(None)
        self._after(world, HOLD)
        actuator.release_if_at_target(None)
        assert actuator.override is None
        assert actuator.manual_run_to_target is False

    async def test_a_reading_that_returns_restarts_the_count(self, actuator, world):
        await actuator.manual_on()
        actuator.release_if_at_target(None)
        self._after(world, HOLD - timedelta(seconds=30))
        actuator.release_if_at_target(50.0)
        self._after(world, HOLD)
        actuator.release_if_at_target(None)
        self._after(world, HOLD + HOLD - timedelta(seconds=1))
        actuator.release_if_at_target(None)
        assert actuator.manual_run_to_target is True

    async def test_a_new_manual_run_restarts_the_count(self, actuator, world):
        await actuator.manual_on()
        actuator.release_if_at_target(None)
        self._after(world, HOLD - timedelta(seconds=30))
        await actuator.manual_on()
        actuator.release_if_at_target(None)
        self._after(world, HOLD)
        actuator.release_if_at_target(None)
        assert actuator.manual_run_to_target is True

    async def test_nothing_runs_on_after_a_manual_off(self, actuator, world):
        await actuator.manual_on()
        actuator.release_if_at_target(None)
        await actuator.manual_off()
        self._after(world, HOLD)
        actuator.release_if_at_target(None)
        assert actuator.override is None


async def test_the_coordinator_sends_the_switch_call_as_a_task():
    """The coordinator wires the background send to its task wrapper."""
    coord = FakeCoordinator(cfg=_cfg(**{CONF_IMMERSION_SWITCH: SWITCH}))
    coord.set_state(SWITCH, "off")

    coord.immersion.actuate(decision(on=True, temp=40.0), T0)

    assert len(coord.tasks_created) == 1
    await coord.tasks_created[0]
    assert coord.service_calls_for("switch", "turn_on") == [{"entity_id": SWITCH}]


async def test_the_coordinator_exposes_the_override_through_the_actuator():
    coord = FakeCoordinator(cfg=_cfg())
    coord.override_immersion = False
    assert coord.immersion.override is False
    coord.immersion.override = True
    assert coord.override_immersion is True
