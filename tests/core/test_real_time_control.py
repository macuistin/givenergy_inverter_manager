"""When GivTCP's Real Time Control switch being off raises a repair, and when it clears."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.core.real_time_control import (
    OFF_CYCLES,
    next_step,
)


def _run(states: list[str | None]):
    count, steps = 0, []
    for state in states:
        step = next_step(state, count)
        count = step.off_cycles
        steps.append(step)
    return steps


def test_the_repair_waits_for_three_cycles_in_a_row():
    steps = _run(["off"] * OFF_CYCLES)

    assert [s.raise_issue for s in steps] == [False, False, True]


def test_it_keeps_asking_while_the_switch_stays_off():
    assert _run(["off"] * (OFF_CYCLES + 2))[-1].raise_issue is True


def test_a_switch_that_comes_back_on_clears_it_and_resets_the_count():
    steps = _run(["off", "off", "on", "off", "off"])

    assert steps[2].clear_issue is True
    assert steps[2].off_cycles == 0
    assert [s.raise_issue for s in steps] == [False] * 5


@pytest.mark.parametrize("state", [None, "", "unknown", "unavailable", "not a state"])
def test_a_switch_that_cannot_be_read_changes_nothing(state):
    step = next_step(state, 2)

    assert (step.off_cycles, step.raise_issue, step.clear_issue) == (2, False, False)


def test_the_state_is_read_in_any_case():
    assert next_step("OFF", OFF_CYCLES - 1).raise_issue is True
    assert next_step("On", 5).clear_issue is True
