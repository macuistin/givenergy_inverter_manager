"""Pins the rule functions over a wide parameter grid.

golden_rules_grid.json was generated from the rules before they were split into small
steps. Inputs were drawn at random (fixed seed) from edge-heavy value sets, so every
branch of the charge target, immersion divert, appliance and surplus rules
is hit. Each row holds the flat inputs and the exact output. A refactor must reproduce
every row, including the reason strings.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from custom_components.givenergy_inverter_manager.core.rules import monthly_solar_fractions
from tests.core.flat_rules import (
    available_surplus_w,
    calculate_overnight_charge_target,
    should_divert_to_immersion,
    suggest_appliance_run,
)

_GRID = json.loads((Path(__file__).parent / "golden_rules_grid.json").read_text())
_FRACTIONS = monthly_solar_fractions(53.3)


def _profile(name):
    return {
        None: None,
        "flat": [1.0] * 48,
        "evening": [0.2] * 30 + [1.5] * 12 + [0.3] * 6,
        "bad": [1.0] * 47,
    }[name]


@pytest.mark.parametrize("row", _GRID["charge"])
def test_charge_target_grid(row):
    kwargs = dict(row["in"])
    month, hour = kwargs.pop("month"), kwargs.pop("hour")
    kwargs["dt"] = datetime(2026, month, 15, hour, 0)
    kwargs["solar_fractions"] = _FRACTIONS if kwargs.pop("fractions") else None
    kwargs["load_profile"] = _profile(kwargs.pop("profile"))
    assert calculate_overnight_charge_target(**kwargs).__dict__ == row["out"]


@pytest.mark.parametrize("row", _GRID["immersion"])
def test_immersion_divert_grid(row):
    assert list(should_divert_to_immersion(**row["in"])) == row["out"]


@pytest.mark.parametrize("row", _GRID["appliance"])
def test_appliance_run_grid(row):
    assert list(suggest_appliance_run(**row["in"])) == row["out"]


@pytest.mark.parametrize("row", _GRID["surplus"])
def test_available_surplus_grid(row):
    assert available_surplus_w(**row["in"]) == row["out"]
