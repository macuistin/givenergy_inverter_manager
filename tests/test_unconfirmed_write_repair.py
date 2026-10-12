"""The repair for a setting the inverter did not take, against the stubbed Home Assistant."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import custom_components.givenergy_inverter_manager.unconfirmed_write_repair as module
from custom_components.givenergy_inverter_manager.givtcp_writer import (
    SwitchState,
    VerifiedWrite,
    _number_write,
    _switch_write,
)
from custom_components.givenergy_inverter_manager.repairs import (
    ISSUE_WRITE_NOT_CONFIRMED,
    LEARN_MORE_URLS,
)
from custom_components.givenergy_inverter_manager.unconfirmed_write_repair import (
    UnconfirmedWriteRepair,
)


class _State:
    def __init__(self, state: str) -> None:
        self.state = state


class _Home:
    def __init__(self) -> None:
        self.states: dict[str, _State] = {}
        self.dry_run = False
        self.created = MagicMock()
        self.deleted = MagicMock()

    def repair(self) -> UnconfirmedWriteRepair:
        return UnconfirmedWriteRepair(
            MagicMock(), lambda: self.dry_run, lambda entity_id: self.states.get(entity_id)
        )


@pytest.fixture
def home(monkeypatch) -> _Home:
    home = _Home()
    monkeypatch.setattr(module, "async_create_write_not_confirmed_issue", home.created)
    monkeypatch.setattr(module, "async_delete_write_not_confirmed_issue", home.deleted)
    return home


def _target(value: int = 75) -> VerifiedWrite:
    return _number_write("number.target_soc", value, "charge target", step=4)


def test_a_failed_write_raises_a_repair_naming_the_setting(home):
    home.repair().not_confirmed(_target())
    home.created.assert_called_once()
    assert home.created.call_args.args[1] == "charge target (number.target_soc, wrote 75)"


def test_dry_run_raises_nothing(home):
    home.dry_run = True
    home.repair().not_confirmed(_target())
    home.created.assert_not_called()


def test_the_same_failure_again_does_not_raise_again(home):
    repair = home.repair()
    repair.not_confirmed(_target())
    repair.not_confirmed(_target())
    home.created.assert_called_once()


def test_a_confirmed_write_clears_the_repair(home):
    repair = home.repair()
    repair.not_confirmed(_target())
    repair.confirmed(_target())
    home.deleted.assert_called_once()


def test_a_confirmation_for_a_setting_that_never_failed_clears_nothing(home):
    home.repair().confirmed(_target())
    home.deleted.assert_not_called()
    home.created.assert_not_called()


def test_a_setting_that_later_holds_its_value_is_cleared_on_the_next_look(home):
    repair = home.repair()
    repair.not_confirmed(_target())
    home.states["number.target_soc"] = _State("75")
    repair.recheck()
    home.deleted.assert_called_once()


def test_a_setting_still_at_the_old_value_stays_on_the_repair(home):
    repair = home.repair()
    repair.not_confirmed(_target())
    home.states["number.target_soc"] = _State("80")
    repair.recheck()
    home.deleted.assert_not_called()


def test_an_unavailable_switch_is_not_read_as_the_value_wanted(home):
    # A switch wanted off reads off when unavailable, which is no proof that it took.
    repair = home.repair()
    repair.not_confirmed(_switch_write("switch.enable_target", SwitchState.OFF, "enable", 5))
    home.states["switch.enable_target"] = _State("unavailable")
    repair.recheck()
    home.deleted.assert_not_called()


def test_clear_deletes_the_repair_and_forgets_the_list(home):
    repair = home.repair()
    repair.not_confirmed(_target())
    repair.clear()
    home.deleted.assert_called_once()
    repair.not_confirmed(_target())
    assert home.created.call_count == 2


def test_the_repair_links_to_the_troubleshooting_entry():
    assert LEARN_MORE_URLS[ISSUE_WRITE_NOT_CONFIRMED].endswith(
        "#writes-to-the-inverter-are-not-confirmed"
    )
