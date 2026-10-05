"""Pins the full CoordinatorData built by build_coordinator_data.

golden_engine_snapshots.json was generated from the engine before it was split into small
steps. It holds 255 cases: every distinct call the scenario and engine tests make, plus
seeded random cases over tariffs, config, EV chargers, overrides, forecasts and accumulator
state. Each case stores the call's inputs and every CoordinatorData field that differs from
a fresh CoordinatorData(), so a refactor must reproduce the whole snapshot, not just the
fields the other tests happen to read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from tests.core import engine_snapshot as snap
from tests.core.flat_engine import build_coordinator_data

_GOLDEN = json.loads((Path(__file__).parent / "golden_engine_snapshots.json").read_text())


def test_fresh_coordinator_data_is_unchanged():
    assert snap.snapshot(CoordinatorData()) == _GOLDEN["fresh"]


@pytest.mark.parametrize("case", _GOLDEN["cases"], ids=range(len(_GOLDEN["cases"])))
def test_coordinator_snapshot_is_unchanged(case):
    kwargs = {name: snap.decode(value) for name, value in case["in"].items()}
    data, ev_target_mode = build_coordinator_data(**kwargs)
    assert snap.diff(snap.snapshot(data), _GOLDEN["fresh"]) == case["out"]
    assert ev_target_mode == case["ev"]


def test_coordinator_data_rejects_attributes_it_does_not_declare():
    with pytest.raises(AttributeError):
        CoordinatorData().not_a_field = 1


def test_coordinator_data_compares_and_hashes_by_identity():
    first, second = CoordinatorData(), CoordinatorData()
    assert first != second
    assert len({first, second}) == 2


def test_each_coordinator_data_gets_its_own_accumulators():
    first, second = CoordinatorData(), CoordinatorData()
    first.today.solar_kwh = 5.0
    assert second.today.solar_kwh == 0.0
