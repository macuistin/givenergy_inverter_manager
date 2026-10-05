"""Pins calculate_overnight_charge_target output when no load history or accuracy data exists.

The golden file was generated from the algorithm before the load profile and forecast
correction were wired in. With no history those inputs are None, so every row must
match exactly.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from custom_components.givenergy_inverter_manager.core.rules import monthly_solar_fractions
from tests.core.flat_rules import calculate_overnight_charge_target

_ROWS = json.loads((Path(__file__).parent / "golden_charge_targets.json").read_text())


@pytest.mark.parametrize(
    "row", _ROWS, ids=[f"m{r[0]}-fc{r[1]}-l{r[2]}-s{r[3]}-p{r[4]}-c{r[5]}-ev{r[6]}" for r in _ROWS]
)
def test_charge_decision_unchanged_without_history(row):
    month, forecast, load, soc, p10, conservatism, ev = row[:7]
    decision = calculate_overnight_charge_target(
        current_soc=soc,
        battery_capacity_kwh=19.0,
        forecast_kwh=forecast,
        inverter_max_kw=5.0,
        car_plugged_in=ev,
        min_soc=10,
        skip_charge_threshold=75,
        average_daily_consumption_kwh=load,
        cheapest_rate=0.0965,
        solar_fractions=monthly_solar_fractions(53.3),
        forecast_kwh_p10=p10,
        forecast_conservatism=conservatism,
        dt=datetime(2026, month, 15, 22, 0),
    )
    assert decision.target_soc == row[7]
    assert decision.skip_charge == row[8]
    assert decision.forecast_kwh == row[9]
    assert decision.reason == row[10]
    assert decision.cost_to_charge == row[11]
