"""When a switch that does not take the manager's commands raises a repair, and when it clears."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.core.switch_commands import (
    FAILURES_BEFORE_REPAIR,
    CommandHealth,
    after_failure,
    after_success,
)


def _fail(times: int, reason: str = "rejected"):
    health, steps = CommandHealth(), []
    for _ in range(times):
        step = after_failure(health, reason)
        health = step.health
        steps.append(step)
    return steps


def test_one_failed_command_raises_nothing():
    assert _fail(1)[0].raise_issue is False


def test_the_repair_appears_with_the_second_failure_in_a_row():
    steps = _fail(FAILURES_BEFORE_REPAIR)

    assert [s.raise_issue for s in steps] == [False, True]


def test_it_is_asked_for_again_on_each_later_failure_with_the_latest_reason():
    health = CommandHealth()
    for reason in ("first", "second", "third"):
        step = after_failure(health, reason)
        health = step.health

    assert step.raise_issue is True
    assert health.reason == "third"


def test_a_command_that_goes_through_clears_the_repair_and_the_count():
    health = _fail(3)[-1].health

    step = after_success(health)

    assert step.clear_issue is True
    assert step.health == CommandHealth()


def test_a_success_before_the_repair_clears_nothing_and_resets_the_count():
    health = _fail(1)[-1].health

    step = after_success(health)

    assert step.clear_issue is False
    assert _fail(1)[0].raise_issue is False
    assert after_failure(step.health, "x").raise_issue is False
