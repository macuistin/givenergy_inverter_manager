"""Pins the full CoordinatorData built by build_coordinator_data.

golden_engine_snapshots.json was generated from the engine before it was split into small
steps. It holds 255 cases: every distinct call the scenario and engine tests make, plus
seeded random cases over tariffs, config, EV chargers, overrides, forecasts and accumulator
state. Each case stores the call's inputs and every CoordinatorData field that differs from
a fresh CoordinatorData(), so a refactor must reproduce the whole snapshot, not just the
fields the other tests happen to read.

109 of the 255 cases were regenerated when the overnight target gained a 25% floor. Only
charge_decision, published_charge_decision (the same value on a first cycle) and, in 13 cases,
sunrise_with_charge moved. Those cases planned a target below 25% on a sunny forecast and now plan
25 with the reason ending "Raised to the 25% floor." The floor is pinned in
tests/core/test_charge_summer_floor.py.

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

The tariff_report_state and tariff_report_html leaves were added when the Tariff in use sensor was
added. Only the fresh snapshot gained them (both empty), and none of the 255 cases moved, because the
coordinator fills them from the saved options and the engine never does. The report is pinned in
tests/core/test_tariff_report.py.

The bill audit added the kWh imported and used in each rate period (import_kwh_by_period and
house_kwh_by_period on the five accumulators), the bill without solar (bill_without_solar) and the
four audit report fields. The fresh snapshot gained all of them. Every one of the 255 cases gained
bill_without_solar, because every case works out a bill, and the cases that accumulated energy
gained the per-period kWh: 114 of today's house use, 31 of today's import, with the week, month and
year in proportion. No other leaf moved. The kWh are pinned in tests/core/test_period_kwh.py and
the audit in tests/core/test_bill_audit.py.

The bill audit's markdown tables added four leaves: bill_audit_bill_table, bill_audit_days_table,
previous_bill_audit_summary_table and previous_bill_audit_period. Only the fresh snapshot gained
them (all empty), and none of the 255 cases moved, because the coordinator fills them and the
engine never does. The tables are pinned in tests/core/test_bill_audit_tables.py.

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

20 of the 255 cases were regenerated when the immersion heater's energy left the average daily load,
as the EV charger's had. Every one has immersion energy on today's accumulator, from earlier in the day or from the cycle's own step. The leaves that
moved are survival_reason (all 20), estimated_soc_at_sunrise (8), will_survive_night (3) and
charge_decision with published_charge_decision (4). The new behaviour is pinned in
test_night_survival_immersion_load.py.

The givtcp_rate_mismatches leaf was removed with the rate comparison. The fresh snapshot lost it
and no case moved.

The charge_target_conflict leaf was added for the Charge Target Conflict sensor. The fresh snapshot
gained it as state none, count 0 and no time or entity. No case moved, because the coordinator
sets it after the engine has built the snapshot. The behaviour is pinned in
tests/core/test_controller_conflict.py.

The immersion_window_heating leaf was added for heating in the cheapest rate window. The fresh
snapshot gained it as False. No case moved, because none opts in. The behaviour is pinned in
tests/core/test_immersion_window.py.

The immersion_ready_time, immersion_expected_ready, immersion_heating_rate_c_per_h and
immersion_rate_source leaves were added for the ready-by plan. The fresh snapshot gained them as
None, None, None and "". No case moved, because none sets a ready time. The behaviour is pinned in
tests/core/test_immersion_ready.py and tests/core/test_immersion_scheduled.py.

The water_heating_advice leaf was added for the oil water heating advice. The fresh snapshot
gained it as None. No case moved, because none sets an oil price. The behaviour is pinned in
tests/core/test_alt_heat_advice.py and tests/core/test_alt_heat_advice_engine.py.

The oil_schedule leaf was added for the suggested oil schedule. The fresh snapshot gained it as
None. No case moved, because none passes a record of the immersion's grid heating. The behaviour
is pinned in tests/core/test_alt_heat_schedule.py and tests/core/test_alt_heat_schedule_engine.py.

The sunrise_with_charge leaf was added for the Estimated SoC at Sunrise With the Planned Charge
sensor. The fresh snapshot gained it as None and all 255 cases gained it, because every cycle
projects the night. Nothing else moved, so estimated_soc_at_sunrise and the survival leaves are
unchanged. The leaf was regenerated once more when it started reading the per-slot load profile and
noting the load in its basis: 162 of the 255 cases moved, and only that leaf. The projection is pinned in tests/core/test_sunrise_charge.py and
tests/core/test_sunrise_charge_engine.py.

The immersion_planned_heating leaf was added for the planned heating sentence. The fresh snapshot
gained it as None. No case moved, because none turns scheduled heating on. The behaviour is pinned
in tests/core/test_planned_heating.py and tests/core/test_immersion_scheduled.py.

The setup_items leaf was added for the setup checklist. The fresh snapshot gained it as an empty
list. No case moved, because the coordinator sets it after the engine has built the snapshot. The
checklist is pinned in tests/core/test_setup_progress.py.

The stored energy value and change in kWh were added to the saving, and today's accumulator gained
soc_at_start_pct, grid_to_battery_cost and grid_to_battery_priced_kwh. The fresh snapshot gained
stored_energy_value, stored_energy_change_kwh and the three accumulator leaves on each of today,
week, month, year and yesterday. 235 of the 255 cases gained today.soc_at_start_pct, the SoC the
first cycle read. Nothing else moved: no case sets the AC charge counter, and every case starts
its day at the SoC it reads, so the saving is unchanged. The behaviour is pinned in
tests/core/test_stored_energy.py.

The test_instance leaf was added for the test instance marker file. The fresh snapshot gained it
as False. No case moved, because the engine never sets it: the coordinator copies it onto the
snapshot after the engine has built it. The behaviour is pinned in
tests/ha_e2e/test_test_instance_e2e.py and tests/test_test_instance.py.

The oil_schedule leaf was renamed alt_heat_schedule when the oil surface became alternative heating.
Only the fresh snapshot's key moved. No case moved, because none passes a record of the immersion's
grid heating. The behaviour is pinned in tests/core/test_alt_heat_schedule.py and
tests/core/test_alt_heat_schedule_engine.py.

The battery_pause leaf was added for the battery pause that falls in the night. The fresh snapshot
gained it as None. No case moved, because none passes a pause. The behaviour is pinned in
tests/core/test_battery_pause.py, tests/core/test_night_survival_pause.py,
tests/core/test_sunrise_charge_pause.py and tests/core/test_charge_pause.py.

1 of the 255 cases was regenerated when the overmorrow reduction stopped applying before sunrise
without a day-after forecast sensor. Only charge_decision and published_charge_decision moved, in
a case made before 08:00 that read the tomorrow sensor as the day after: its target went from 87
to 100. The behaviour is pinned in tests/core/test_forecast_day.py and
tests/core/test_midnight_charge_replay.py.

218 of the 255 cases were regenerated when the night window started at the time solar is expected
to stop in daylight (20:00 with no forecast shape, where it was 00:00) and counted partial hours.
171 cases have solar on after 08:00 and 92 were made part way through an hour (45 both). The
leaves that moved are survival_reason (211), estimated_soc_at_sunrise (171), sunrise_with_charge
(53, its soc on a night with no charge, which equals the figure without one), will_survive_night
(3) and charge_decision with published_charge_decision (1). Two of the three verdicts are 14:00
cases with solar on that now count the evening and run short. The third, made at 14:45 with no
solar, now counts 17.25 hours where it counted 18 and lasts, so its plan now skips, as the skip
check reads the same window. The new behaviour is pinned in
tests/core/test_night_window_from_sunset.py.

55 of the 255 cases were regenerated when the charge cost started following the target that is
written. Only cost_to_charge on charge_decision and on published_charge_decision moved, the same
value on both. 18 cases have a target capped at the configured maximum and now cost the capped
target, 16 have a manual fixed target and now cost that target (9 up, 7 down), and 21 have a manual
skip and now cost nothing. The cost still counts only the energy above the SoC. The 14:45 case
that the night window change turned into a skip already cost nothing. The new behaviour is
pinned in tests/core/test_charge_cost_follows_target.py.

The tomorrow_outlook leaf was added for the Tomorrow Outlook sensor. The fresh snapshot gained it
as None and 84 of the 255 cases gained it. The other 171 pass no forecast and no seasonal
fractions, so they have no outlook. Nothing else moved, also with the plan's day now built by
_day_to_simulate. The behaviour is pinned in tests/core/test_tomorrow_outlook.py.

The ev_sessions leaf was added for the EV Session Cost sensor. The fresh snapshot gained it as
None. No case moved, because none passes an EV session log. The behaviour is pinned in
tests/core/test_ev_session.py and tests/core/test_ev_session_engine.py.

The active_repairs leaf was added for the Active Repairs sensor. The fresh snapshot gained it as an
empty list. No case moved, because the coordinator sets it from the issue registry after the engine
has built the snapshot. The summary is pinned in tests/core/test_repair_summary.py and the registry
side in tests/ha_e2e/test_active_repairs_e2e.py.

23 of the 255 cases were regenerated when the average daily load started from yesterday's load in
the small hours. They are the cases made between 00:30 and 03:45, where the estimate was the
house energy so far scaled to 24 hours and is now blended with the 15 kWh a case with no
yesterday falls back to. Only the leaves that read the daily load moved: survival_reason (22
cases), sunrise_with_charge (17), estimated_soc_at_sunrise (12), charge_decision and
published_charge_decision (10, the same value on a first cycle), tomorrow_outlook (6) and
will_survive_night (1). The behaviour is pinned in tests/core/test_engine.py and
tests/core/test_small_hours_target_replay.py.

3 of the 255 cases were regenerated when the charge reason started saying that the target was
raised to the minimum SoC plus 5 points. Only the reason text of charge_decision and
published_charge_decision moved, in cases 225, 243 and 253. Their targets did not move. The
behaviour is pinned in tests/core/test_charge_headroom_reason.py.
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
