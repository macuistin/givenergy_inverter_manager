"""The repair for an immersion switch that does not take the manager's commands."""

from __future__ import annotations

import homeassistant.helpers.issue_registry as ir
import pytest

from custom_components.givenergy_inverter_manager.const import CONF_IMMERSION_SWITCH, DOMAIN
from custom_components.givenergy_inverter_manager.repairs import (
    ISSUE_IMMERSION_SWITCH_NOT_RESPONDING,
)
from tests.test_coordinator import FakeCoordinator, _cfg

SWITCH = "switch.immersion_socket_1"


@pytest.fixture
def coord():
    ir.async_create_issue.reset_mock()
    ir.async_delete_issue.reset_mock()
    coordinator = FakeCoordinator(cfg=_cfg(**{CONF_IMMERSION_SWITCH: SWITCH}))
    coordinator.set_state(SWITCH, "off")
    return coordinator


def _reject(coord, message="The Tuya cloud rejected the command"):
    async def rejected(domain, service, data):
        raise Exception(message)  # the stub of HomeAssistantError is Exception

    coord._call_service = rejected


def _ignore_the_call(coord):
    """Home Assistant only logs a call to an unavailable entity, so nothing changes its state."""

    async def ignored(domain, service, data):
        return None

    coord._call_service = ignored


async def _send(coord, service="turn_on", *, raises=False):
    if raises:
        with pytest.raises(Exception, match="rejected"):
            await coord._send_immersion_command(service, SWITCH)
    else:
        await coord._send_immersion_command(service, SWITCH)


def _raised():
    return [c for c in ir.async_create_issue.call_args_list if c.args[2] == ISSUE_IMMERSION_SWITCH_NOT_RESPONDING]


async def test_one_rejected_command_raises_no_repair(coord):
    _reject(coord)

    await _send(coord, raises=True)

    assert _raised() == []


async def test_a_second_rejected_command_raises_the_repair_with_the_reason(coord):
    _reject(coord)

    await _send(coord, raises=True)
    await _send(coord, raises=True)

    [call] = _raised()
    assert call.args[1] == DOMAIN
    assert call.kwargs["translation_placeholders"] == {
        "switch": SWITCH,
        "reason": "The Tuya cloud rejected the command",
    }
    assert call.kwargs["is_fixable"] is False


async def test_a_switch_that_reads_unavailable_counts_even_though_the_call_does_not_raise(coord):
    _ignore_the_call(coord)
    coord.set_state(SWITCH, "unavailable")

    await _send(coord)
    await _send(coord)

    [call] = _raised()
    assert call.kwargs["translation_placeholders"]["reason"] == "the switch is unavailable"


async def test_a_command_that_goes_through_clears_the_repair(coord):
    _ignore_the_call(coord)
    coord.set_state(SWITCH, "unavailable")
    await _send(coord)
    await _send(coord)
    coord.set_state(SWITCH, "off")

    await _send(coord)

    deleted = [c.args[2] for c in ir.async_delete_issue.call_args_list]
    assert ISSUE_IMMERSION_SWITCH_NOT_RESPONDING in deleted


async def test_a_success_between_two_failures_keeps_the_repair_down(coord):
    _reject(coord)
    await _send(coord, raises=True)
    coord._call_service = type(coord)._call_service.__get__(coord)  # accepts the command again
    await _send(coord)
    _reject(coord)

    await _send(coord, raises=True)

    assert _raised() == []


async def test_a_rejected_command_is_not_read_as_a_manual_switch_off(coord):
    """The plug stays off after a rejected turn-on. That is not someone switching it off."""
    from datetime import timedelta

    actuator = coord.immersion
    actuator.last_commanded_on = True
    actuator.cooldown_until = None
    _reject(coord)

    await _send(coord, "turn_on", raises=True)

    assert actuator.last_commanded_on is None
    seen = actuator._observe(SWITCH, coord._now() + timedelta(hours=1))
    assert not actuator._toggled_externally(seen)


async def test_an_unavailable_switch_is_not_read_as_a_manual_switch_off(coord):
    coord.set_state(SWITCH, "unavailable")
    coord.immersion.last_commanded_on = True
    _ignore_the_call(coord)

    await _send(coord, "turn_on")

    assert coord.immersion.last_commanded_on is None


async def test_a_command_that_went_through_stays_the_last_command(coord):
    coord.immersion.last_commanded_on = True
    _ignore_the_call(coord)

    await _send(coord, "turn_on")

    assert coord.immersion.last_commanded_on is True
