"""The SoC at sunrise with a battery pause in the night (core/sunrise_charge.py and the engine).

The evening of the other sunrise tests: 66% at 19:00, a charge planned from 02:00 to a target of
90%, the house using 0.55 kWh an hour. While the battery is paused the grid serves the house, so
the load of those hours is not taken from the battery, before the charge and after it. A night
with no pause gives the figures it always did.
"""

from __future__ import annotations

from datetime import datetime, time

import pytest

from custom_components.givenergy_inverter_manager.core.battery_pause import PauseWindow
from custom_components.givenergy_inverter_manager.core.sunrise_charge import (
    BASIS_REACHES_TARGET,
    BASIS_SKIPPED,
    LOAD_NOTE_FLAT,
    BatteryNow,
    PlannedCharge,
    flat_load,
    pause_before_sunrise,
    project_sunrise_with_charge,
    slot_load,
    with_pause_note,
    without_paused_load,
)
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.core.test_sunrise_charge import _battery, _plan, _window
from tests.core.test_sunrise_charge_engine import (
    BASE_W,
    CAPACITY_KWH,
    EVENING,
    INVERTER_W,
    MIN_SOC,
    _nightboost_cfg,
    _pct,
    _raw,
    _run,
)

NIGHT = PauseWindow(time(23, 0), time(8, 0))
HOURLY_KWH = 0.55
NOTE = "The battery is paused from 23:00 to 08:00."


def _flat():
    return flat_load(HOURLY_KWH)


def _project(pause: PauseWindow | None, window=None, **fields):
    plan = _plan(window or _window("02:00", "04:35"), **fields)
    return project_sunrise_with_charge(
        _battery(), EVENING, plan, without_paused_load(_flat(), pause)
    )


class TestTheLoadModel:
    def test_without_a_pause_it_is_the_same_model(self):
        load = _flat()

        assert without_paused_load(load, None) is load

    def test_a_flat_load_counts_only_the_hours_the_battery_serves(self):
        load = without_paused_load(_flat(), NIGHT)

        # 22:00 to 08:00 is ten hours, nine of them paused.
        assert load(22 * 60, 10 * 60) == pytest.approx(HOURLY_KWH)
        assert load(9 * 60, 10 * 60) == pytest.approx(10 * HOURLY_KWH)

    def test_a_per_slot_load_leaves_out_the_paused_slots(self):
        slots = [0.1] * 16 + [0.4] * 32
        load = without_paused_load(slot_load(slots), NIGHT)

        # 19:00 to 08:00: slots 38 to 45 at 0.4 each (19:00 to 23:00), and nothing from 23:00.
        assert load(19 * 60, 13 * 60) == pytest.approx(8 * 0.4)

    def test_a_per_slot_load_keeps_the_slots_outside_the_pause_exactly(self):
        slots = [(i + 1) / 100 for i in range(48)]
        daytime = PauseWindow(time(12, 0), time(14, 0))

        # 10:00 to 16:00 is slots 20 to 31, minus the four of 12:00 to 14:00 (slots 24 to 27).
        expected = sum(slots[20:24]) + sum(slots[28:32])
        assert without_paused_load(slot_load(slots), daytime)(10 * 60, 6 * 60) == pytest.approx(
            expected
        )


class TestTheProjection:
    def test_without_a_pause_the_figures_are_the_ones_without_one(self):
        projection = _project(None)

        assert projection.soc_at_charge_start == pytest.approx(66.0 - _pct(HOURLY_KWH * 7))
        assert projection.soc == pytest.approx(90.0 - _pct(HOURLY_KWH * (205 / 60)))

    def test_a_pause_over_the_night_takes_no_load_from_the_battery_after_23_00(self):
        projection = _project(NIGHT)

        # Only 19:00 to 23:00 runs the battery down. The charge then fills it to 90%, and the
        # pause holds it there until sunrise.
        assert projection.soc_at_charge_start == pytest.approx(66.0 - _pct(HOURLY_KWH * 4))
        assert projection.soc == pytest.approx(90.0)
        assert projection.charge_added_pct == pytest.approx(
            90.0 - (66.0 - _pct(HOURLY_KWH * 4))
        )
        assert projection.basis.startswith(BASIS_REACHES_TARGET)

    def test_a_pause_that_ends_inside_the_charge_window_only_spares_the_hours_before_it(self):
        ends_in_window = PauseWindow(time(23, 0), time(3, 0))
        projection = _project(ends_in_window)

        # 19:00 to 23:00 runs down, 23:00 to 02:00 is paused, the window fills the battery, and
        # 04:35 to 08:00 runs it down as it does with no pause at all.
        assert projection.soc_at_charge_start == pytest.approx(66.0 - _pct(HOURLY_KWH * 4))
        assert projection.soc == pytest.approx(_project(None).soc)

    def test_a_pause_that_starts_inside_the_charge_window_only_spares_the_hours_after_it(self):
        starts_in_window = PauseWindow(time(3, 0), time(8, 0))
        projection = _project(starts_in_window)

        assert projection.soc_at_charge_start == pytest.approx(_project(None).soc_at_charge_start)
        assert projection.soc == pytest.approx(90.0)

    def test_a_pause_inside_the_charge_window_changes_nothing(self):
        # The window adds no house load, so a pause that falls wholly inside it spares none.
        inside = _project(PauseWindow(time(2, 30), time(4, 0)))
        none = _project(None)

        assert inside.soc == pytest.approx(none.soc)
        assert inside.soc_at_charge_start == pytest.approx(none.soc_at_charge_start)

    def test_a_skipped_night_still_gives_the_figure_without_a_charge(self):
        projection = project_sunrise_with_charge(
            BatteryNow(66.0, 9.5, 10.0, 77.0),
            EVENING,
            PlannedCharge(_window("02:00", "04:35"), 90.0, True),
            without_paused_load(_flat(), NIGHT),
        )

        assert projection.soc == 77.0
        assert projection.basis == BASIS_SKIPPED


class TestWhenThePauseIsPartOfTheNight:
    def test_a_pause_before_sunrise_is_named(self):
        assert pause_before_sunrise(NIGHT, EVENING) == NIGHT

    def test_a_pause_after_sunrise_and_before_the_evening_is_not(self):
        daytime = PauseWindow(time(12, 0), time(14, 0))

        assert pause_before_sunrise(daytime, EVENING) is None
        assert pause_before_sunrise(None, EVENING) is None

    def test_the_part_of_a_pause_still_to_come_counts_after_midnight(self):
        assert pause_before_sunrise(NIGHT, datetime(2026, 6, 16, 3, 0)) == NIGHT
        assert pause_before_sunrise(NIGHT, datetime(2026, 6, 16, 8, 30)) == NIGHT

    def test_the_basis_names_the_pause_once(self):
        projection = _project(NIGHT)

        noted = with_pause_note(with_pause_note(projection, NIGHT), NIGHT)

        assert noted.basis == f"{projection.basis}. {NOTE}"

    def test_without_a_pause_the_basis_is_unchanged(self):
        projection = _project(None)

        assert with_pause_note(projection, None) is projection


# ── Through the engine ──────────────────────────────────────────────────────


def _cycle(now: datetime, soc: float, pause: PauseWindow | None, **kw):
    """One engine cycle for a house that has used 550 W since midnight."""
    acc_minutes = now.hour * 60 + now.minute
    acc = EnergyAccumulator()
    acc.house_kwh = BASE_W / 1000 * acc_minutes / 60
    raw = _raw(
        battery_soc=soc,
        battery_capacity_kwh=CAPACITY_KWH,
        inverter_max_w=INVERTER_W,
        solar_power_w=0.0,
        house_load_w=BASE_W,
        battery_power_w=0.0,
        grid_power_w=BASE_W,
        battery_charge_rate_w=INVERTER_W,
        forecast_kwh_tomorrow=6.0,
        battery_pause=pause,
    )
    kw.setdefault("override_charge_target", 90)
    data, _ = _run(raw=raw, cfg=_nightboost_cfg(), now=now, acc=acc, **kw)
    return data


class TestTheEngine:
    def test_without_a_pause_nothing_is_named(self):
        data = _cycle(EVENING, 66.0, None)

        assert data.battery_pause is None
        assert "paused" not in data.survival_reason
        assert "paused" not in data.sunrise_with_charge.basis

    def test_the_figure_without_a_charge_is_not_run_down_by_the_paused_hours(self):
        # At 90% the battery holds 7.6 kWh above its 10% minimum. 13 hours at 0.55 kWh is 7.15
        # kWh, so it ends the night on 14.7%. Nine of those hours are paused.
        without = _cycle(EVENING, 90.0, None)
        paused = _cycle(EVENING, 90.0, NIGHT)

        assert without.estimated_soc_at_sunrise == pytest.approx(10.0 + _pct(7.6 - 7.15))
        assert paused.estimated_soc_at_sunrise - without.estimated_soc_at_sunrise == (
            pytest.approx(_pct(9 * HOURLY_KWH))
        )

    def test_the_survival_reason_and_the_pause_are_published(self):
        data = _cycle(EVENING, 66.0, NIGHT)

        assert data.battery_pause == NIGHT
        assert data.survival_reason.endswith(NOTE)
        assert data.survival_reason.count("paused") == 1
        assert data.will_survive_night is True

    def test_the_figure_with_the_charge_ends_the_night_on_the_target(self):
        data = _cycle(EVENING, 66.0, NIGHT)
        projection = data.sunrise_with_charge

        assert projection.soc == pytest.approx(90.0)
        assert projection.soc_at_charge_start == pytest.approx(66.0 - _pct(HOURLY_KWH * 4))
        assert projection.basis.endswith(f"{LOAD_NOTE_FLAT} {NOTE}")
        assert projection.basis.count("paused") == 1

    def test_the_night_has_the_pause_that_falls_in_it_only(self):
        daytime = PauseWindow(time(12, 0), time(14, 0))

        data = _cycle(EVENING, 66.0, daytime)

        assert data.battery_pause is None
        assert data.estimated_soc_at_sunrise == _cycle(EVENING, 66.0, None).estimated_soc_at_sunrise
        assert "paused" not in data.survival_reason

    def test_a_skipped_night_names_the_pause_in_the_basis(self):
        data = _cycle(EVENING, 90.0, NIGHT, override_skip_charge=True, override_charge_target=None)

        assert data.sunrise_with_charge.basis == f"{BASIS_SKIPPED}. {NOTE}"
        assert data.sunrise_with_charge.soc == data.estimated_soc_at_sunrise

    def test_the_charge_plan_reads_the_pause_too(self):
        # 40% at 19:00 with 6 kWh of sun forecast. The plan wants 86% (capped at 80) with no
        # pause, because the house runs the battery down all night. With one it needs far less.
        free = _cycle(EVENING, 40.0, None, override_charge_target=None).charge_decision
        paused = _cycle(EVENING, 40.0, NIGHT, override_charge_target=None).charge_decision

        assert paused.target_soc < free.target_soc - 30
        assert paused.reason.endswith(NOTE)
        assert "paused" not in free.reason

    def test_the_battery_never_reads_below_its_minimum(self):
        data = _cycle(EVENING, 12.0, NIGHT)

        assert data.estimated_soc_at_sunrise >= MIN_SOC
