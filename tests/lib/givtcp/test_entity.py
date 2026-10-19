"""The reads every control shares: option spellings, usable text and limits."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.givenergy_inverter_manager.lib.givtcp._entity import (
    attribute_limit,
    clamp_to_entity,
    listed_options,
    read_int,
    squash,
    usable,
)


def _state(value="1", **attributes):
    return SimpleNamespace(state=str(value), attributes=attributes)


def test_option_spellings_compare_without_case_spaces_underscores_or_hyphens():
    assert squash("Pause Discharge") == squash("pause_discharge") == squash("Pause-Discharge")


@pytest.mark.parametrize("text", ["unavailable", "UNKNOWN", "none", "", "  "])
def test_a_state_that_says_nothing_is_not_usable(text):
    assert usable(_state(text)) is None
    assert usable(None) is None


def test_a_select_lists_its_options_as_text():
    assert listed_options(_state(options=["Eco", 3])) == ["Eco", "3"]
    assert listed_options(_state()) is None


def test_a_limit_that_is_not_a_number_is_ignored():
    assert attribute_limit(_state(max="lots"), "max") is None
    assert attribute_limit(_state(max="2600"), "max") == 2600.0
    assert attribute_limit(None, "max") is None


@pytest.mark.parametrize(
    ("asked", "state", "floor", "ceiling", "expected"),
    [
        (50, _state(min=0, max=100), 4, 100, 50),
        (0, _state(min=0, max=100), 4, 100, 4),
        (200, _state(min=0, max=100), 4, 100, 100),
        (200, _state(min=0, max=90), 4, 100, 90),
        (3000, _state(min=0, max=2600), 0, None, 2600),
        (3000, _state(), 0, None, 3000),
        (-5, _state(), 0, None, 0),
        (80, _state(min="abc", max="xyz"), 4, 100, 80),
        (80, _state(max=0), 0, None, 0),
        (80, None, 4, 100, 80),
        (49.6, _state(), 0, None, 50),
    ],
)
def test_a_number_is_kept_inside_the_floor_the_ceiling_and_what_the_entity_publishes(
    asked, state, floor, ceiling, expected
):
    assert clamp_to_entity(asked, state, floor, ceiling) == expected


def test_a_whole_number_is_read_from_a_numeric_state():
    states = {"number.a": _state("80.0"), "number.b": _state("abc")}

    assert read_int(states.get, "number.a") == 80
    assert read_int(states.get, "number.b") is None
    assert read_int(states.get, "number.c") is None
    assert read_int(states.get, None) is None
