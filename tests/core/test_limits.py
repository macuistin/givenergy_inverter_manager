"""The battery capacity and inverter output: a sensor reading first, the typed value after."""

import pytest

from custom_components.givenergy_inverter_manager.core.limits import (
    capacity_kwh,
    inverter_output_kw,
)


@pytest.mark.parametrize(
    ("state", "unit", "typed", "expected"),
    [
        ("19.05", "kWh", 10.0, 19.05),
        ("19.05", None, 10.0, 19.05),
        ("9500", "Wh", 10.0, 9.5),
        ("unavailable", "kWh", 10.0, 10.0),
        ("unknown", None, 10.0, 10.0),
        (None, None, 10.0, 10.0),
        ("0", "kWh", 10.0, 10.0),
        ("nan", "kWh", 10.0, 10.0),
        ("-3", "kWh", 10.0, 10.0),
        ("19", "gallons", 10.0, 10.0),
    ],
)
def test_capacity(state, unit, typed, expected):
    assert capacity_kwh(state, unit, typed) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("state", "unit", "typed", "expected"),
    [
        ("5000", "W", 3.0, 5.0),
        ("5000", None, 3.0, 5.0),
        ("3.6", "kW", 5.0, 3.6),
        ("unavailable", "W", 5.0, 5.0),
        (None, None, 5.0, 5.0),
        ("0", "W", 5.0, 5.0),
    ],
)
def test_inverter_output(state, unit, typed, expected):
    assert inverter_output_kw(state, unit, typed) == pytest.approx(expected)
