"""The Tonight's Charge Plan sensor says where things stand when the plan is not shown."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.core.overnight_phase import (
    PLAN_DONE_WORDS,
    PLAN_WAITING_WORDS,
    OvernightPhase,
)
from custom_components.givenergy_inverter_manager.core.reporting import (
    build_charge_plan_html,
    build_charge_plan_state,
)


def _data(phase: OvernightPhase) -> CoordinatorData:
    data = CoordinatorData()
    data.overnight_phase = phase
    data.overnight_plan_ready_at = "17:00"
    data.battery_soc = 99.6
    return data


def test_through_the_day_it_says_when_the_plan_will_be_ready() -> None:
    state = build_charge_plan_state(_data(OvernightPhase.WAITING))
    assert state == "Tonight's plan will be ready around 17:00"
    assert state.startswith(PLAN_WAITING_WORDS)


def test_after_the_night_it_gives_the_result_and_when_the_next_plan_comes() -> None:
    state = build_charge_plan_state(_data(OvernightPhase.DONE))
    assert state.startswith(PLAN_DONE_WORDS)
    assert "battery at 100%" in state
    assert state.endswith("Tonight's plan will be ready around 17:00")


def test_the_report_card_carries_the_same_words() -> None:
    for phase in (OvernightPhase.WAITING, OvernightPhase.DONE):
        data = _data(phase)
        assert build_charge_plan_state(data).split(" · ")[0] in build_charge_plan_html(data)


def test_while_the_plan_is_shown_the_state_is_the_plan() -> None:
    state = build_charge_plan_state(_data(OvernightPhase.ACTIVE))
    assert state == "No charge decision yet"
