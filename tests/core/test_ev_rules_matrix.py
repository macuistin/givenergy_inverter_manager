"""Every combination of the EV mode inputs against a plain truth table, and the transitions.

The table is written out here from the rules in the design (window, Pause, Charge now, the one-time
return to Eco+, surplus), not read from rules.py, so a rule that drifts fails. The diagram in
docs/ev-charger-logic.mermaid is kept in step with it by the last class.
"""

from __future__ import annotations

import itertools
import re
from datetime import datetime, time, timedelta
from pathlib import Path

import pytest

from custom_components.givenergy_inverter_manager.const import EV_CHARGER_MIN_POWER_W
from custom_components.givenergy_inverter_manager.core.charge_window import in_clock_window
from custom_components.givenergy_inverter_manager.core.rules import EVRequest
from custom_components.givenergy_inverter_manager.core.rules import (
    decide_ev_charger_action as decide,
)
from custom_components.givenergy_inverter_manager.discovery import (
    EVCharger,
    EVChargerBrand,
    EVChargerState,
)

OPTIONS = ("Fast", "Eco", "Eco+", "Stopped")
MODES = ("Fast", "Eco", "Eco+", "Stopped")
SURPLUSES = (0.0, 1379.0, 1380.0, 5000.0)
DIAGRAM = Path(__file__).parents[2] / "docs" / "ev-charger-logic.mermaid"


def _zappi(mode: str, *, plugged: bool) -> EVCharger:
    return EVCharger(
        brand=EVChargerBrand.ZAPPI,
        name="Zappi",
        serial="123",
        display_name="Zappi (123)",
        state=EVChargerState.CONNECTED if plugged else EVChargerState.DISCONNECTED,
        charge_mode=mode,
        charge_mode_entity="select.zappi_123_charge_mode",
        charge_mode_options=OPTIONS,
    )


def expected(*, scheduled, pause, charge_now, grid_held, plugged, mode, surplus):
    """The mode the rules ask for, or None, written as a plain list of cases."""
    if scheduled:
        return "Fast" if plugged and mode != "Fast" else None
    if pause:
        return "Stopped" if mode != "Stopped" else None
    if charge_now and plugged:
        return "Fast" if mode != "Fast" else None
    if grid_held and mode == "Fast":
        return "Eco+"
    if not plugged:
        return None
    if surplus < 1380:
        return None
    return "Eco+" if mode != "Eco+" else None


CASES = list(
    itertools.product(
        (True, False), (True, False), (True, False), (True, False), (True, False), MODES, SURPLUSES
    )
)


@pytest.mark.parametrize(
    ("scheduled", "pause", "charge_now", "grid_held", "plugged", "mode", "surplus"), CASES
)
def test_every_combination_matches_the_truth_table(
    scheduled, pause, charge_now, grid_held, plugged, mode, surplus
):
    target, reason = decide(
        _zappi(mode, plugged=plugged),
        60.0,
        surplus,
        EVRequest(scheduled=scheduled, pause=pause, charge_now=charge_now, grid_held=grid_held),
    )
    assert target == expected(
        scheduled=scheduled,
        pause=pause,
        charge_now=charge_now,
        grid_held=grid_held,
        plugged=plugged,
        mode=mode,
        surplus=surplus,
    )
    assert reason


class TestEachRuleOnItsOwn:
    def test_the_window_asks_for_fast_for_a_plugged_in_car(self):
        assert decide(_zappi("Eco+", plugged=True), 60.0, 0.0, EVRequest(scheduled=True))[0] == "Fast"

    def test_the_window_never_changes_the_mode_of_an_unplugged_charger(self):
        for mode in MODES:
            assert decide(_zappi(mode, plugged=False), 60.0, 0.0, EVRequest(scheduled=True))[0] is None

    def test_the_window_beats_pause_and_charge_now(self):
        request = EVRequest(scheduled=True, pause=True, charge_now=True)
        assert decide(_zappi("Stopped", plugged=True), 60.0, 0.0, request)[0] == "Fast"

    def test_pause_asks_for_stopped_outside_the_window_even_unplugged(self):
        for plugged in (True, False):
            assert decide(_zappi("Eco+", plugged=plugged), 60.0, 9000.0, EVRequest(pause=True))[0] == "Stopped"

    def test_pause_beats_charge_now_outside_the_window(self):
        request = EVRequest(pause=True, charge_now=True)
        assert decide(_zappi("Eco+", plugged=True), 60.0, 0.0, request)[0] == "Stopped"

    def test_charge_now_asks_for_fast_outside_the_window_with_no_surplus(self):
        assert decide(_zappi("Eco+", plugged=True), 60.0, 0.0, EVRequest(charge_now=True))[0] == "Fast"

    def test_charge_now_does_nothing_for_an_unplugged_charger(self):
        assert decide(_zappi("Eco+", plugged=False), 60.0, 0.0, EVRequest(charge_now=True))[0] is None

    def test_an_unplugged_charger_is_never_asked_for_stopped_without_pause(self):
        for mode, surplus in itertools.product(MODES, SURPLUSES):
            target = decide(_zappi(mode, plugged=False), 60.0, surplus, EVRequest())[0]
            assert target in (None,)

    def test_surplus_at_the_minimum_asks_for_eco_plus_and_just_below_does_not(self):
        assert EV_CHARGER_MIN_POWER_W == 1380
        assert decide(_zappi("Stopped", plugged=True), 60.0, 1380.0, EVRequest())[0] == "Eco+"
        assert decide(_zappi("Stopped", plugged=True), 60.0, 1379.9, EVRequest())[0] is None

    def test_a_small_surplus_leaves_every_mode_alone(self):
        for mode in MODES:
            assert decide(_zappi(mode, plugged=True), 60.0, 1000.0, EVRequest())[0] is None

    def test_the_return_to_eco_plus_needs_fast_and_the_integration_note(self):
        assert decide(_zappi("Fast", plugged=True), 60.0, 0.0, EVRequest(grid_held=True))[0] == "Eco+"
        assert decide(_zappi("Fast", plugged=True), 60.0, 0.0, EVRequest(grid_held=False))[0] is None
        assert decide(_zappi("Stopped", plugged=True), 60.0, 0.0, EVRequest(grid_held=True))[0] is None

    def test_the_return_to_eco_plus_happens_for_an_unplugged_charger_too(self):
        assert decide(_zappi("Fast", plugged=False), 60.0, 0.0, EVRequest(grid_held=True))[0] == "Eco+"


class _Day:
    """The coordinator's loop in miniature: decide, note that Fast was set, apply the target."""

    def __init__(self, *, mode="Stopped", start=time(23, 0), end=time(9, 0)):
        self.mode, self.held, self.start, self.end = mode, False, start, end
        self.commands: list[tuple[datetime, str]] = []

    def cycle(self, now, *, plugged=True, surplus=0.0, pause=False, charge_now=False):
        scheduled = in_clock_window(now, self.start, self.end)
        request = EVRequest(
            scheduled=scheduled, pause=pause, charge_now=charge_now, grid_held=self.held
        )
        target, _ = decide(_zappi(self.mode, plugged=plugged), 60.0, surplus, request)
        if self.mode != "Fast":
            self.held = False
        elif scheduled:
            self.held = True
        if target is not None:
            self.held = target == "Fast"
            self.mode = target
            self.commands.append((now, target))


def _run(day: _Day, inputs, days=2):
    """Run whole days of 30 second cycles from midnight. inputs(now) gives a cycle's inputs."""
    now = datetime(2026, 11, 18, 0, 0)
    for _ in range(days * 24 * 120):
        day.cycle(now, **inputs(now))
        now += timedelta(seconds=30)


def _surplus_by_the_sun(now):
    """Nothing at night, and by day a surplus that wobbles across 1,380 W every minute."""
    if 9 <= now.hour < 17:
        return 1300.0 if now.minute % 2 else 1500.0
    return 0.0


def _at(commands):
    return [(t.strftime("%H:%M"), m) for t, m in commands]


class TestTransitions:
    def test_a_plugged_in_car_gets_fast_at_the_start_and_eco_plus_once_at_the_end(self):
        day = _Day()
        _run(day, lambda now: {"surplus": _surplus_by_the_sun(now)})
        assert _at(day.commands) == [
            ("00:00", "Fast"),  # the first cycle is already inside the window
            ("09:00", "Eco+"),
            ("23:00", "Fast"),
            ("09:00", "Eco+"),
            ("23:00", "Fast"),
        ]

    def test_a_wobbling_surplus_never_makes_the_mode_flap(self):
        day = _Day(mode="Eco+")
        _run(day, lambda now: {"surplus": _surplus_by_the_sun(now)}, days=3)
        modes = [m for _, m in day.commands]
        assert modes == ["Fast", "Eco+"] * 3 + ["Fast"]
        assert "Stopped" not in modes

    def test_the_return_to_eco_plus_happens_once_and_at_the_end_of_the_window(self):
        day = _Day(mode="Eco+")
        _run(day, lambda now: {}, days=2)
        assert [t for t, m in _at(day.commands) if m == "Eco+"] == ["09:00", "09:00"]

    def test_pause_outside_the_window_stops_once_and_the_window_overrides_it(self):
        day = _Day(mode="Eco+")
        _run(day, lambda now: {"pause": True}, days=2)
        assert _at(day.commands) == [
            ("00:00", "Fast"),
            ("09:00", "Stopped"),
            ("23:00", "Fast"),
            ("09:00", "Stopped"),
            ("23:00", "Fast"),
        ]

    def test_a_fast_set_by_hand_outside_the_window_is_left_alone_all_day(self):
        day = _Day(mode="Fast")
        now = datetime(2026, 11, 18, 10, 0)
        for _ in range(8 * 120):
            day.cycle(now)
            now += timedelta(seconds=30)
        assert day.commands == []
        assert day.mode == "Fast"

    def test_a_restart_inside_the_window_still_returns_to_eco_plus_at_the_end(self):
        day = _Day(mode="Fast")  # Fast found after a restart, nothing noted yet
        now = datetime(2026, 11, 19, 3, 0)
        while now < datetime(2026, 11, 19, 9, 5):
            day.cycle(now)
            now += timedelta(seconds=30)
        assert [(t.strftime("%H:%M"), m) for t, m in day.commands] == [("09:00", "Eco+")]

    def test_charge_now_by_day_asks_for_fast_once_and_turning_it_off_returns_to_eco_plus_once(self):
        day = _Day(mode="Eco+")
        now = datetime(2026, 11, 18, 10, 0)
        for cycle in range(240):
            day.cycle(now, charge_now=cycle < 120)
            now += timedelta(seconds=30)
        assert [m for _, m in day.commands] == ["Fast", "Eco+"]

    def test_unplugging_inside_the_window_changes_nothing_and_the_end_still_returns_to_eco_plus(self):
        day = _Day(mode="Eco+")
        now = datetime(2026, 11, 18, 23, 0)
        while now < datetime(2026, 11, 19, 9, 5):
            day.cycle(now, plugged=not (datetime(2026, 11, 19, 2, 0) <= now < datetime(2026, 11, 19, 4, 0)))
            now += timedelta(seconds=30)
        assert [m for _, m in day.commands] == ["Fast", "Eco+"]


class TestTheDiagramMatchesTheRules:
    TEXT = DIAGRAM.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "phrase",
        [
            "Inside the charge window",
            "Charge Start Time to Charge End Time",
            "Pause on?",
            "Charge now on",
            "In Fast, and this",
            "integration set it",
            "Request Eco+ once",
            "never Stopped",
            "Battery hold",
            "PauseDischarge",
            "30 minutes",
            "5 minutes",
            "200 W",
            "Hold switch on",
            "Never writes the charge slot",
        ],
    )
    def test_each_decision_the_code_makes_is_in_the_diagram(self, phrase):
        assert phrase in self.TEXT

    def test_the_diagram_quotes_the_charger_minimum_the_code_uses(self):
        assert f"{EV_CHARGER_MIN_POWER_W:,} W" in self.TEXT

    def test_the_diagram_names_every_mode_the_rules_can_ask_for(self):
        for mode in ("Fast", "Stopped", "Eco+"):
            assert mode in self.TEXT

    def test_the_hold_numbers_match_the_tuning_constants(self):
        from custom_components.givenergy_inverter_manager.const import (
            EV_HOLD_MINUTES,
            EV_HOLD_RELEASE_MINUTES,
        )

        assert f"{EV_HOLD_MINUTES} minutes" in self.TEXT
        assert f"{EV_HOLD_RELEASE_MINUTES} minutes" in self.TEXT

    def test_every_node_is_defined_and_every_edge_points_at_one(self):
        nodes = set(re.findall(r"\b([A-Z0-9]+)(?=[\[\(\{])", self.TEXT))
        edges = re.findall(r"([A-Z0-9]+)\s*--(?:\s*\w+\s*--)?>\s*([A-Z0-9]+)", self.TEXT)
        assert edges
        for _left, right in edges:
            assert right in nodes, right
