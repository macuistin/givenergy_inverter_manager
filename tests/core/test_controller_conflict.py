"""Something else is changing the charge target: two outside changes in three days."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.core.controller_conflict import (
    STATE_NONE,
    STATE_SUSPECTED,
    ConflictStatus,
    detect_conflict,
)

TARGET = "number.target_soc"
NOW = datetime(2031, 3, 4, 12, 0, tzinfo=timezone.utc)


def _entry(ago: timedelta, *, reason="external", entity=TARGET, user_id=None) -> dict:
    entry = {
        "time": (NOW - ago).isoformat(),
        "entity_id": entity,
        "value": "90",
        "reason": reason,
    }
    if user_id:
        entry["user_id"] = user_id
    return entry


HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


class TestDetect:
    def test_an_empty_log_is_none(self):
        assert detect_conflict([], TARGET, NOW) == ConflictStatus(entity_id=TARGET)

    def test_one_outside_change_is_not_enough(self):
        status = detect_conflict([_entry(HOUR)], TARGET, NOW)

        assert (status.state, status.count) == (STATE_NONE, 1)

    def test_two_outside_changes_inside_three_days_are_suspected(self):
        entries = [_entry(2 * DAY), _entry(HOUR)]

        status = detect_conflict(entries, TARGET, NOW)

        assert (status.state, status.count) == (STATE_SUSPECTED, 2)
        assert status.last_seen_iso == (NOW - HOUR).isoformat()
        assert status.entity_id == TARGET

    def test_changes_made_by_a_home_assistant_user_are_not_counted(self):
        entries = [_entry(HOUR, user_id="user-1"), _entry(2 * HOUR, user_id="user-1")]

        assert detect_conflict(entries, TARGET, NOW).state == STATE_NONE

    def test_the_managers_own_writes_are_not_counted(self):
        entries = [_entry(HOUR, reason="charge target"), _entry(2 * HOUR, reason="charge target")]

        assert detect_conflict(entries, TARGET, NOW).count == 0

    def test_changes_to_other_entities_are_not_counted(self):
        entries = [_entry(HOUR, entity="select.charge_start"), _entry(2 * HOUR, entity="select.x")]

        assert detect_conflict(entries, TARGET, NOW).count == 0

    def test_changes_older_than_three_days_age_out(self):
        entries = [_entry(3 * DAY + HOUR), _entry(4 * DAY), _entry(HOUR)]

        status = detect_conflict(entries, TARGET, NOW)

        assert (status.state, status.count) == (STATE_NONE, 1)

    def test_it_clears_after_three_days_without_a_change(self):
        entries = [_entry(HOUR), _entry(2 * HOUR)]

        assert detect_conflict(entries, TARGET, NOW).state == STATE_SUSPECTED
        assert detect_conflict(entries, TARGET, NOW + 3 * DAY).state == STATE_NONE

    def test_a_mixed_log_counts_only_what_matches(self):
        entries = [
            _entry(HOUR),
            _entry(2 * HOUR, reason="charge target"),
            _entry(3 * HOUR, user_id="user-1"),
            _entry(4 * HOUR, entity="select.charge_start"),
            _entry(5 * HOUR),
        ]

        assert detect_conflict(entries, TARGET, NOW).count == 2

    @pytest.mark.parametrize("entity", [None, ""])
    def test_no_target_entity_is_none(self, entity):
        assert detect_conflict([_entry(HOUR), _entry(2 * HOUR)], entity, NOW) == ConflictStatus()

    def test_an_entry_with_an_unreadable_time_is_ignored(self):
        bad = {**_entry(HOUR), "time": "not a time"}

        assert detect_conflict([bad, _entry(2 * HOUR)], TARGET, NOW).count == 1
