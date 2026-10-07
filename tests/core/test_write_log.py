"""The write log: bound, restore, change detection and the manager-echo memory."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.core.write_log import (
    EXTERNAL_REASON,
    ManagerWriteMemory,
    WriteLogEntry,
    append_bounded,
    is_real_value_change,
    newest_first,
    restore_entries,
    same_value,
)


def _entry(n: int) -> WriteLogEntry:
    return WriteLogEntry(f"2026-10-07T01:{n:02d}:00+01:00", "number.target", str(n), "charge target")


class TestBound:
    def test_keeps_only_the_newest_entries_in_order(self):
        entries: list[dict] = []
        for n in range(25):
            entries = append_bounded(entries, _entry(n), 20)
        assert [e["value"] for e in entries] == [str(n) for n in range(5, 25)]

    def test_does_not_change_the_list_it_was_given(self):
        original = [_entry(1).as_dict()]
        append_bounded(original, _entry(2), 20)
        assert len(original) == 1

    def test_context_fields_appear_only_when_set(self):
        plain = _entry(1).as_dict()
        external = WriteLogEntry("t", "e", "v", EXTERNAL_REASON, user_id="u", parent_id="p")
        assert "user_id" not in plain
        assert external.as_dict()["user_id"] == "u"
        assert external.as_dict()["parent_id"] == "p"


class TestRestore:
    def test_round_trips_valid_entries(self):
        stored = [_entry(1).as_dict(), _entry(2).as_dict()]
        assert restore_entries(stored, 20) == stored

    @pytest.mark.parametrize("stored", [None, "log", 5, {"a": 1}])
    def test_anything_that_is_not_a_list_is_empty(self, stored):
        assert restore_entries(stored, 20) == []

    def test_drops_malformed_entries_and_keeps_the_rest(self):
        good = _entry(1).as_dict()
        stored = [good, "x", {"time": "t"}, {**good, "value": 5}, None]
        assert restore_entries(stored, 20) == [good]

    def test_trims_an_oversized_log_to_the_newest(self):
        stored = [_entry(n).as_dict() for n in range(30)]
        restored = restore_entries(stored, 20)
        assert len(restored) == 20
        assert restored[-1]["value"] == "29"


def test_newest_first_reverses_without_touching_the_source():
    source = [_entry(1).as_dict(), _entry(2).as_dict()]
    assert [e["value"] for e in newest_first(source)] == ["2", "1"]
    assert [e["value"] for e in source] == ["1", "2"]


class TestRealValueChange:
    @pytest.mark.parametrize(
        ("old", "new", "expected"),
        [
            ("80", "55", True),
            ("02:00:00", "01:00:00", True),
            ("80", "80.0", False),
            ("80", "80", False),
            ("unavailable", "55", False),
            ("55", "unavailable", False),
            ("unknown", "55", False),
            (None, "55", False),
        ],
    )
    def test_cases(self, old, new, expected):
        assert is_real_value_change(old, new) is expected


class TestSameValue:
    def test_numbers_compare_as_numbers(self):
        assert same_value(55, "55.0")

    def test_text_compares_as_text(self):
        assert same_value("02:00:00", "02:00:00")
        assert not same_value("02:00:00", "02:30:00")


class TestManagerWriteMemory:
    def test_a_matching_change_inside_the_window_is_the_managers(self):
        memory = ManagerWriteMemory(300)
        memory.remember("number.t", "62", at_s=100)
        assert memory.is_echo("number.t", "62.0", at_s=103)

    def test_a_different_value_is_not(self):
        memory = ManagerWriteMemory(300)
        memory.remember("number.t", "62", at_s=100)
        assert not memory.is_echo("number.t", "70", at_s=103)

    def test_a_matching_change_after_the_window_is_not(self):
        memory = ManagerWriteMemory(300)
        memory.remember("number.t", "62", at_s=100)
        assert not memory.is_echo("number.t", "62", at_s=401)

    def test_the_window_edge_still_counts(self):
        memory = ManagerWriteMemory(300)
        memory.remember("number.t", "62", at_s=100)
        assert memory.is_echo("number.t", "62", at_s=400)

    def test_a_write_explains_one_change_only(self):
        memory = ManagerWriteMemory(300)
        memory.remember("number.t", "62", at_s=100)
        assert memory.is_echo("number.t", "62", at_s=101)
        assert not memory.is_echo("number.t", "62", at_s=102)

    def test_an_entity_with_no_write_is_never_an_echo(self):
        assert not ManagerWriteMemory(300).is_echo("number.t", "62", at_s=1)

    def test_entities_are_remembered_separately(self):
        memory = ManagerWriteMemory(300)
        memory.remember("number.a", "62", at_s=100)
        assert not memory.is_echo("number.b", "62", at_s=101)

    def test_a_forgotten_write_explains_nothing(self):
        memory = ManagerWriteMemory(300)
        memory.remember("number.t", "62", at_s=100)
        memory.forget("number.t")
        assert not memory.is_echo("number.t", "62", at_s=101)
