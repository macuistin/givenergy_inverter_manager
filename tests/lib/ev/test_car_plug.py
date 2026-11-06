"""Whether a car is plugged in at home, from the charger and the car's own readings."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.lib.ev import (
    CAR_READING_MAX_AGE_S,
    CarPlugInputs,
    Confidence,
    PlugSource,
    PlugState,
    car_home_from_state,
    car_plug_from_state,
    decide_car_plug,
)

P, N = PlugState.PLUGGED_IN, PlugState.NOT_PLUGGED_IN


@pytest.mark.parametrize(
    ("charger", "plug", "home", "state", "source", "conflict", "matches"),
    [
        (True, True, True, P, PlugSource.CHARGER_AND_CAR, False, True),
        (True, False, True, P, PlugSource.CHARGER, True, True),
        (True, None, True, P, PlugSource.CHARGER, False, True),
        (True, True, False, P, PlugSource.CHARGER, True, False),
        (True, None, None, P, PlugSource.CHARGER, False, True),
        (False, True, True, P, PlugSource.CAR, True, True),
        (False, True, False, N, PlugSource.CHARGER, False, True),
        (False, False, True, N, PlugSource.CHARGER, False, True),
        (False, None, None, N, PlugSource.CHARGER, False, True),
        (None, True, True, P, PlugSource.CAR, False, True),
        (None, True, False, N, PlugSource.CAR, False, True),
        (None, False, True, N, PlugSource.CAR, False, True),
        (None, None, None, PlugState.UNKNOWN, PlugSource.NONE, False, True),
    ],
)
def test_decision_table(charger, plug, home, state, source, conflict, matches):
    result = decide_car_plug(CarPlugInputs(charger, plug, home))
    assert (result.state, result.source, result.conflict, result.car_matches) == (
        state,
        source,
        conflict,
        matches,
    )


def test_a_stale_car_reading_falls_back_to_the_charger():
    stale = CarPlugInputs(True, False, False, car_age_s=CAR_READING_MAX_AGE_S + 1)
    result = decide_car_plug(stale)
    assert result.state is P
    assert result.source is PlugSource.CHARGER
    assert result.confidence is Confidence.HIGH
    assert not result.conflict


def test_a_fresh_car_reading_is_used():
    fresh = CarPlugInputs(True, False, True, car_age_s=CAR_READING_MAX_AGE_S)
    assert decide_car_plug(fresh).conflict


def test_a_car_with_no_tracker_is_trusted_with_low_confidence():
    result = decide_car_plug(CarPlugInputs(None, True, None))
    assert result.state is P
    assert result.confidence is Confidence.LOW


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("on", True),
        ("Plugged in", True),
        ("connected", True),
        ("off", False),
        ("Disconnected", False),
        ("unavailable", None),
        ("unknown", None),
        (None, None),
        ("charging", None),
    ],
)
def test_plug_states(raw, expected):
    assert car_plug_from_state(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("home", True), ("not_home", False), ("Work", False), ("unavailable", None), (None, None)],
)
def test_home_states(raw, expected):
    assert car_home_from_state(raw) is expected
