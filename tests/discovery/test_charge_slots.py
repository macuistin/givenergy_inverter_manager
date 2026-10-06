"""
test_charge_slots.py: the pure finder for charge slots the integration does not manage.

HA-free: the finder takes a get_state callable returning an object with a
`.state`, or None for an entity that does not exist.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass

import pytest

from custom_components.givenergy_inverter_manager.discovery.givtcp import (
    ActiveChargeSlot,
    describe_charge_slots,
    find_other_active_charge_slots,
)

START_1 = "select.givtcp_ab1234g567_charge_start_time_slot_1"
END_1 = "select.givtcp_ab1234g567_charge_end_time_slot_1"


@dataclass
class _State:
    state: str


def _start(n: int) -> str:
    return f"select.givtcp_ab1234g567_charge_start_time_slot_{n}"


def _end(n: int) -> str:
    return f"select.givtcp_ab1234g567_charge_end_time_slot_{n}"


def _find(states: dict[str, str], start: str = START_1, end: str = END_1):
    lookup = {entity_id: _State(value) for entity_id, value in states.items()}
    return find_other_active_charge_slots(start, end, lookup.get)


def _slot(n: int, start: str, end: str) -> dict[str, str]:
    return {_start(n): start, _end(n): end}


class TestActiveSlots:
    def test_slot_with_a_window_is_reported_as_hh_mm(self):
        slots = _find({**_slot(1, "01:59:00", "04:00:00"), **_slot(2, "00:00:00", "08:00:00")})

        assert slots == [ActiveChargeSlot(2, _start(2), _end(2), "00:00", "08:00")]

    def test_unused_slot_is_not_reported(self):
        assert _find({**_slot(2, "00:00:00", "00:00:00")}) == []

    def test_any_equal_start_and_end_is_unused(self):
        assert _find(_slot(3, "06:30:00", "06:30:00")) == []

    def test_the_managed_slot_is_never_reported(self):
        assert _find(_slot(1, "02:00:00", "04:00:00")) == []

    def test_times_without_seconds_are_read(self):
        assert [s.label for s in _find(_slot(2, "2:00", "04:00"))] == ["Slot 2 (02:00 to 04:00)"]

    def test_several_slots_come_back_in_slot_order(self):
        slots = _find({**_slot(5, "10:00:00", "11:00:00"), **_slot(2, "00:00:00", "08:00:00")})

        assert [s.number for s in slots] == [2, 5]

    def test_slot_ten_is_checked(self):
        assert [s.number for s in _find(_slot(10, "12:00:00", "13:00:00"))] == [10]

    def test_slot_eleven_is_not_checked(self):
        assert _find(_slot(11, "12:00:00", "13:00:00")) == []


class TestIgnoredEntities:
    def test_missing_entities_are_ignored(self):
        assert _find({}) == []

    def test_a_slot_missing_its_end_entity_is_ignored(self):
        assert _find({_start(2): "00:00:00"}) == []

    def test_a_slot_missing_its_start_entity_is_ignored(self):
        assert _find({_end(2): "08:00:00"}) == []

    @pytest.mark.parametrize("state", ["unavailable", "unknown", "", "not a time"])
    def test_unusable_states_are_ignored(self, state):
        assert _find(_slot(2, state, "08:00:00")) == []
        assert _find(_slot(2, "00:00:00", state)) == []


class TestEntityNames:
    def test_prefix_comes_from_the_configured_entities(self):
        start, end = "select.my_inv_charge_start_slot_1", "select.my_inv_charge_end_slot_1"
        states = {"select.my_inv_charge_start_slot_4": "01:00", "select.my_inv_charge_end_slot_4": "02:00"}

        slots = _find(states, start, end)

        assert slots == [
            ActiveChargeSlot(
                4, "select.my_inv_charge_start_slot_4", "select.my_inv_charge_end_slot_4",
                "01:00", "02:00",
            )
        ]

    def test_a_configured_slot_other_than_one_makes_slot_one_a_sibling(self):
        slots = _find({**_slot(1, "00:00:00", "08:00:00")}, _start(2), _end(2))

        assert [s.number for s in slots] == [1]

    def test_configured_entities_without_a_slot_number_find_nothing(self):
        assert _find(_slot(2, "00:00:00", "08:00:00"), "select.charge_start", "select.charge_end") == []

    def test_configured_entities_with_different_slot_numbers_find_nothing(self):
        assert _find(_slot(3, "00:00:00", "08:00:00"), _start(1), _end(2)) == []


class TestDescription:
    def test_label_names_the_slot_and_window(self):
        assert ActiveChargeSlot(2, "a", "b", "00:00", "08:00").label == "Slot 2 (00:00 to 08:00)"

    def test_several_slots_are_joined_in_one_line(self):
        slots = [ActiveChargeSlot(2, "a", "b", "00:00", "08:00"), ActiveChargeSlot(3, "c", "d", "09:00", "10:00")]

        assert describe_charge_slots(slots) == "Slot 2 (00:00 to 08:00), Slot 3 (09:00 to 10:00)"

    def test_slot_is_frozen(self):
        with pytest.raises(FrozenInstanceError):
            ActiveChargeSlot(2, "a", "b", "00:00", "08:00").start = "01:00"  # type: ignore[misc]
