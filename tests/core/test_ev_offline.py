"""When an offline EV charger raises a repair."""

from custom_components.givenergy_inverter_manager.core.ev_offline import (
    EV_OFFLINE_REPAIR_CYCLES,
    next_step,
)


def _run(states: list[bool]):
    cycles, raised, cleared = 0, 0, 0
    for offline in states:
        step = next_step(offline=offline, cycles=cycles)
        cycles = step.cycles
        raised += step.raise_issue
        cleared += step.clear_issue
    return raised, cleared


def test_the_repair_is_raised_once_when_the_limit_is_reached():
    assert _run([True] * (EV_OFFLINE_REPAIR_CYCLES + 5)) == (1, 0)


def test_a_short_drop_raises_nothing():
    assert _run([True] * (EV_OFFLINE_REPAIR_CYCLES - 1) + [False]) == (0, 0)


def test_the_repair_clears_when_the_charger_reports_again():
    assert _run([True] * EV_OFFLINE_REPAIR_CYCLES + [False, False]) == (1, 1)
