"""Pins the full CoordinatorData built by build_coordinator_data.

golden_engine_snapshots.json was generated from the engine before it was split into small
steps. It holds 255 cases: every distinct call the scenario and engine tests make, plus
seeded random cases over tariffs, config, EV chargers, overrides, forecasts and accumulator
state. Each case stores the call's inputs and every CoordinatorData field that differs from
a fresh CoordinatorData(), so a refactor must reproduce the whole snapshot, not just the
fields the other tests happen to read.

The 26 cases made before 08:00 were regenerated when the charge decision started reading
the forecast remembered before midnight, so only their charge_decision changed. The new
behaviour is pinned in test_forecast_day.py.

148 cases were regenerated when the saving started pricing the load at the rate in force when
it ran. Only grid_equivalent_load_cost on the accumulators, saving_vs_grid_today and
net_saving_today moved. The new behaviour is pinned in test_saving_counterfactual.py.

189 cases were regenerated when the pre-boost export fields left CoordinatorData. Only the three
pre_boost_export_* leaves were removed, from those cases and from the fresh snapshot.

All 255 cases were regenerated when the published charge recommendation was added. Only the new
published_charge_decision leaf was added, to the fresh snapshot (None) and to every case. On the
first cycle it equals charge_decision. The hold itself is pinned in test_charge_hold.py.

The charge_window leaf was added when the charge window was sized to the plan: 217 of the 255
cases gained it, and the fresh snapshot gained it as None. Nothing else moved. Those cases have no
battery charge rate, so every window is the cheapest period. The sizing is pinned in
tests/core/test_charge_window.py.

The published_charge_window leaf was added when the Overnight Charge Window sensor started holding
its end. The fresh snapshot gained it as None and 217 of the 255 cases gained it, the same 217 that
have a charge_window. On the first cycle it equals charge_window. Nothing else moved. The hold is
pinned in test_charge_hold.py and test_decision_stability.py.

The cheap_run_remaining_minutes leaf was added for the Cheap from tile: 49 of the 255 cases gained
it, and the fresh snapshot gained it as None. Nothing else moved.

33 of the 255 cases were regenerated when the EV charger's energy left the average daily load
(night survival and the charge target no longer read a car's draw as house load). The
leaves that moved are survival_reason (all 33), estimated_soc_at_sunrise (16), will_survive_night
(7), and charge_decision with published_charge_decision (13). Every one has EV energy on
today's accumulator. The new behaviour is pinned in test_night_survival_ev_load.py and the
published estimate in test_sunrise_estimate_continuity.py.

The forecast_accuracy leaf was added for the accuracy diagnostics on the charge reason sensor. The
fresh snapshot gained it as None. No case moved, because none passes a forecast accuracy.

7 of the 255 cases were regenerated when the EV and immersion cost stopped taking battery-charging
import. Only zappi_cost, immersion_cost and house_cost on the accumulators and
ev_cost_per_km_today moved. The new behaviour is pinned in TestAccumulateEnergy in
tests/core/test_engine.py.

The givtcp_rate_mismatches leaf was added for the GivTCP rate attributes of the Current Rate
sensor. The fresh snapshot gained it as None. No case moved, because the coordinator sets it
after the engine has built the snapshot.
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
