"""When a setting the inverter did not take raises, refreshes and clears the repair."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.lib.guards.alert import AlertAction
from custom_components.givenergy_inverter_manager.lib.guards.write_confirmation import (
    Unconfirmed,
    UnconfirmedWrite,
    confirmed_step,
    describe_unconfirmed,
    unconfirmed_step,
)

TARGET = UnconfirmedWrite("number.target_soc", "charge target", "75")
WINDOW_END = UnconfirmedWrite("select.charge_end", "charge window end", "06:20:00")


class TestARepairIsRaisedOncePerSetting:
    def test_the_first_failure_raises(self):
        step = unconfirmed_step(Unconfirmed(), TARGET)
        assert step.action is AlertAction.RAISE
        assert step.state.writes == (TARGET,)

    def test_the_same_failure_again_does_nothing(self):
        state = unconfirmed_step(Unconfirmed(), TARGET).state
        step = unconfirmed_step(state, TARGET)
        assert step.action is AlertAction.NONE
        assert step.state is state

    def test_a_second_setting_refreshes_the_repair_with_both(self):
        state = unconfirmed_step(Unconfirmed(), TARGET).state
        step = unconfirmed_step(state, WINDOW_END)
        assert step.action is AlertAction.RAISE
        assert step.state.writes == (TARGET, WINDOW_END)

    def test_a_new_value_for_a_listed_setting_replaces_the_old_one(self):
        state = unconfirmed_step(Unconfirmed(), TARGET).state
        newer = UnconfirmedWrite(TARGET.entity_id, TARGET.name, "80")
        step = unconfirmed_step(state, newer)
        assert step.action is AlertAction.RAISE
        assert step.state.writes == (newer,)


class TestARepairIsClearedWhenEverySettingIsBack:
    def test_the_last_setting_confirmed_clears(self):
        state = unconfirmed_step(Unconfirmed(), TARGET).state
        step = confirmed_step(state, TARGET.entity_id)
        assert step.action is AlertAction.CLEAR
        assert step.state.writes == ()

    def test_one_of_two_confirmed_refreshes_the_text_with_the_other(self):
        state = unconfirmed_step(unconfirmed_step(Unconfirmed(), TARGET).state, WINDOW_END).state
        step = confirmed_step(state, TARGET.entity_id)
        assert step.action is AlertAction.RAISE
        assert step.state.writes == (WINDOW_END,)

    def test_an_entity_that_never_failed_does_nothing(self):
        state = unconfirmed_step(Unconfirmed(), TARGET).state
        step = confirmed_step(state, "number.other")
        assert step.action is AlertAction.NONE
        assert step.state is state

    def test_nothing_to_clear_does_nothing(self):
        assert confirmed_step(Unconfirmed(), TARGET.entity_id).action is AlertAction.NONE


def test_the_text_names_each_setting_its_entity_and_the_value():
    text = describe_unconfirmed((TARGET, WINDOW_END))
    assert text == (
        "charge target (number.target_soc, wrote 75); "
        "charge window end (select.charge_end, wrote 06:20:00)"
    )
