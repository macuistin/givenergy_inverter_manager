"""WriteAudit: the manager's writes and outside changes land in one bounded, saved log."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.givenergy_inverter_manager.accumulation import AccumulationState
from custom_components.givenergy_inverter_manager.const import REGISTER_WRITE_LOG_MAX_ENTRIES
from custom_components.givenergy_inverter_manager.core.write_log import WriteRecord
from custom_components.givenergy_inverter_manager.write_audit import WriteAudit

NOW = datetime(2026, 10, 7, 1, 59, 5, tzinfo=timezone.utc)
TARGET = "number.target_soc"


def _change(old: str | None, new: str | None, user_id=None, parent_id=None):
    def state(value):
        if value is None:
            return None
        return SimpleNamespace(
            state=value, context=SimpleNamespace(user_id=user_id, parent_id=parent_id)
        )

    return SimpleNamespace(
        data={"entity_id": TARGET, "old_state": state(old), "new_state": state(new)}
    )


@pytest.fixture
def acc():
    return SimpleNamespace(state=AccumulationState(), schedule_save=MagicMock())


@pytest.fixture
def audit(acc) -> WriteAudit:
    return WriteAudit(acc, now=lambda: NOW)


def _write(audit: WriteAudit, value: str = "62", reason: str = "charge target") -> None:
    record = WriteRecord(TARGET, value, reason)
    audit.before_write(record)
    audit.after_write(record)


class TestManagerWrites:
    def test_a_write_is_logged_with_time_entity_value_and_reason(self, audit, acc):
        _write(audit)
        assert acc.state.register_write_log == [
            {
                "time": NOW.isoformat(),
                "entity_id": TARGET,
                "value": "62",
                "reason": "charge target",
            }
        ]

    def test_a_write_asks_for_a_save(self, audit, acc):
        _write(audit)
        acc.schedule_save.assert_called_once()

    def test_a_failed_write_is_not_logged(self, audit, acc):
        record = WriteRecord(TARGET, "62", "charge target")
        audit.before_write(record)
        audit.write_failed(record)
        assert acc.state.register_write_log == []

    def test_the_log_keeps_the_newest_entries_only(self, audit, acc):
        for n in range(REGISTER_WRITE_LOG_MAX_ENTRIES + 5):
            _write(audit, value=str(n))
        log = acc.state.register_write_log
        assert len(log) == REGISTER_WRITE_LOG_MAX_ENTRIES
        assert log[0]["value"] == "5"
        assert log[-1]["value"] == str(REGISTER_WRITE_LOG_MAX_ENTRIES + 4)


class TestOutsideChanges:
    def test_a_change_the_manager_did_not_make_is_logged_with_its_context(
        self, audit, acc, caplog
    ):
        with caplog.at_level(logging.INFO):
            audit._on_state_change(_change("80", "55", user_id="u1", parent_id="p1"))
        assert acc.state.register_write_log == [
            {
                "time": NOW.isoformat(),
                "entity_id": TARGET,
                "value": "55",
                "reason": "external",
                "user_id": "u1",
                "parent_id": "p1",
            }
        ]
        assert "number.target_soc changed from 80 to 55 outside the manager" in caplog.text
        assert "user_id=u1" in caplog.text

    def test_the_log_line_is_info(self, audit, caplog):
        with caplog.at_level(logging.INFO):
            audit._on_state_change(_change("80", "55"))
        levels = [r.levelno for r in caplog.records if "outside the manager" in r.getMessage()]
        assert levels == [logging.INFO]

    def test_the_managers_own_write_coming_back_as_a_change_is_not_logged(self, audit, acc):
        record = WriteRecord(TARGET, "62", "charge target")
        audit.before_write(record)
        audit._on_state_change(_change("80", "62"))  # the entity echoes before the call returns
        audit.after_write(record)
        assert [e["reason"] for e in acc.state.register_write_log] == ["charge target"]

    def test_the_echo_may_also_arrive_after_the_call_returns(self, audit, acc):
        _write(audit)
        audit._on_state_change(_change("80", "62"))
        assert [e["reason"] for e in acc.state.register_write_log] == ["charge target"]

    def test_someone_else_setting_a_different_value_is_logged(self, audit, acc):
        _write(audit, "62")
        audit._on_state_change(_change("62", "90"))
        assert acc.state.register_write_log[-1]["reason"] == "external"

    def test_a_failed_write_does_not_hide_a_later_identical_outside_change(self, audit, acc):
        record = WriteRecord(TARGET, "62", "charge target")
        audit.before_write(record)
        audit.write_failed(record)
        audit._on_state_change(_change("80", "62"))
        assert acc.state.register_write_log[-1]["reason"] == "external"

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ("80", "unavailable"),
            ("unavailable", "80"),
            ("unknown", "80"),
            (None, "80"),
            ("80", None),
            ("80", "80"),
            ("80", "80.0"),
        ],
    )
    def test_connection_events_and_attribute_only_updates_are_ignored(
        self, audit, acc, old, new
    ):
        audit._on_state_change(_change(old, new))
        assert acc.state.register_write_log == []

    def test_outside_changes_share_the_bound(self, audit, acc):
        for n in range(REGISTER_WRITE_LOG_MAX_ENTRIES + 3):
            audit._on_state_change(_change(str(n), str(n + 1000)))
        assert len(acc.state.register_write_log) == REGISTER_WRITE_LOG_MAX_ENTRIES
