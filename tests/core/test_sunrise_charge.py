"""The SoC at sunrise with tonight's planned charge (core/sunrise_charge.py).

The evening case from a daily review of a live install: the battery at 66% at 19:00, a charge
planned from 02:00 to 04:35 to a target of 90%. The estimate without a charge sits on the
minimum SoC all evening, although the battery finishes the night near the target.
"""

from __future__ import annotations

from datetime import datetime, time

import pytest

from custom_components.givenergy_inverter_manager.core.battery import (
    NightEstimateInputs,
    estimate_will_survive_night,
)
from custom_components.givenergy_inverter_manager.core.charge_window import ChargeWindow
from custom_components.givenergy_inverter_manager.core.sunrise_charge import (
    BASIS_ABOVE_TARGET,
    BASIS_NO_WINDOW,
    BASIS_NOT_BEFORE_SUNRISE,
    BASIS_RATE_LIMITED,
    BASIS_RATE_UNKNOWN,
    BASIS_REACHES_TARGET,
    BASIS_SKIPPED,
    LOAD_NOTE_FLAT,
    LOAD_NOTE_PER_SLOT,
    BatteryNow,
    PlannedCharge,
    flat_load,
    project_sunrise_with_charge,
    slot_load,
    with_load_note,
)

CAPACITY_KWH = 9.5
MIN_SOC = 10.0
POWER_KW = 3.6
NO_CHARGE_FIGURE = 10.0


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 15, hour, minute)


def _window(start: str = "02:00", end: str = "04:35") -> ChargeWindow:
    start_at, end_at = time.fromisoformat(start), time.fromisoformat(end)
    return ChargeWindow(start_at, end_at, False, None, None)


def _battery(soc: float = 66.0, without_charge: float = NO_CHARGE_FIGURE) -> BatteryNow:
    return BatteryNow(soc, CAPACITY_KWH, MIN_SOC, without_charge)


def _plan(window: ChargeWindow | None = None, **fields) -> PlannedCharge:
    fields.setdefault("target_soc", 90.0)
    fields.setdefault("skipped", False)
    fields.setdefault("charge_power_kw", POWER_KW)
    return PlannedCharge(window if window is not None else _window(), **fields)


def _per_slot(from_minute: float, minutes: float) -> float:
    """A per-slot load: busy evening, quiet small hours, a little more from 06:00."""

    def hourly(minute_of_day: float) -> float:
        hour = (minute_of_day % 1440) // 60
        if hour >= 19:
            return 0.40
        return 0.05 if hour < 8 else 0.30

    steps = int(minutes)
    used = sum(hourly(from_minute + m + 0.5) / 60 for m in range(steps))
    return used + hourly(from_minute + steps) / 60 * (minutes - steps)


def _flat(hourly_kwh: float = 0.55):
    return flat_load(hourly_kwh)


class TestTheEveningFromTheReview:
    def test_without_a_charge_the_figure_sits_on_the_floor(self):
        """Premise: the existing projection reads the minimum for the whole evening."""
        _, without_charge, _ = estimate_will_survive_night(
            NightEstimateInputs(66.0, CAPACITY_KWH, MIN_SOC, 13.0, 0.55)
        )
        assert without_charge == MIN_SOC

    def test_with_the_planned_charge_the_battery_ends_the_night_near_the_target(self):
        result = project_sunrise_with_charge(_battery(), _at(19), _plan(), _per_slot)
        assert 88.0 <= result.soc <= 90.0
        assert result.basis == BASIS_REACHES_TARGET

    def test_the_figures_that_make_it_up_are_given(self):
        result = project_sunrise_with_charge(_battery(), _at(19), _plan(), _per_slot)
        # 19:00 to 02:00 uses 5 h at 0.40 and 2 h at 0.05 kWh an hour, 2.1 kWh in all.
        assert result.soc_at_charge_start == pytest.approx(66.0 - 2.1 / CAPACITY_KWH * 100)
        assert result.charge_added_pct == pytest.approx(90.0 - result.soc_at_charge_start)
        assert result.charge_window == "02:00 to 04:35"

    def test_the_figure_does_not_depend_on_the_figure_without_a_charge(self):
        low = project_sunrise_with_charge(_battery(without_charge=10.0), _at(19), _plan(), _per_slot)
        high = project_sunrise_with_charge(_battery(without_charge=55.0), _at(19), _plan(), _per_slot)
        assert low.soc == high.soc


class TestNoChargeInTheNight:
    def test_a_skipped_night_gives_the_figure_without_a_charge(self):
        result = project_sunrise_with_charge(
            _battery(without_charge=37.5), _at(19), _plan(skipped=True), _flat()
        )
        assert result.soc == 37.5
        assert result.basis == BASIS_SKIPPED
        assert (result.soc_at_charge_start, result.charge_window) == (None, None)
        assert result.charge_added_pct == 0.0

    def test_no_timed_window_gives_the_figure_without_a_charge(self):
        plan = PlannedCharge(None, 90.0, False, POWER_KW)
        result = project_sunrise_with_charge(_battery(without_charge=22.0), _at(19), plan, _flat())
        assert result.soc == 22.0
        assert result.basis == BASIS_NO_WINDOW

    def test_a_window_that_has_finished_starts_from_the_current_soc(self):
        result = project_sunrise_with_charge(
            _battery(soc=88.0, without_charge=74.0), _at(5), _plan(), _flat()
        )
        assert result.soc == 74.0
        assert result.basis == BASIS_NOT_BEFORE_SUNRISE
        assert result.charge_window is None

    def test_a_window_that_opens_after_sunrise_adds_nothing_tonight(self):
        plan = _plan(_window("09:00", "11:00"))
        result = project_sunrise_with_charge(_battery(without_charge=12.0), _at(20), plan, _flat())
        assert result.soc == 12.0
        assert result.basis == BASIS_NOT_BEFORE_SUNRISE


class TestTheWindowAddsCharge:
    def test_a_target_below_the_soc_when_the_window_opens_adds_nothing(self):
        battery = _battery(soc=95.0)
        result = project_sunrise_with_charge(battery, _at(19), _plan(target_soc=70.0), _flat(0.1))
        assert result.basis == BASIS_ABOVE_TARGET
        assert result.charge_added_pct == 0.0
        assert result.soc_at_charge_start == pytest.approx(95.0 - 0.1 * 7 / CAPACITY_KWH * 100)

    def test_the_charge_stops_at_the_target(self):
        result = project_sunrise_with_charge(_battery(), _at(19), _plan(target_soc=80.0), _flat(0.0))
        assert result.soc == pytest.approx(80.0)

    def test_the_charge_never_goes_above_the_battery_capacity(self):
        result = project_sunrise_with_charge(_battery(), _at(19), _plan(target_soc=130.0), _flat(0.0))
        assert result.soc == pytest.approx(100.0)

    def test_a_slow_charge_stops_short_of_the_target(self):
        """0.5 kW for 2 h 35 min is 1.29 kWh, 13.6 points, from the SoC when the window opens."""
        plan = _plan(charge_power_kw=0.5)
        result = project_sunrise_with_charge(_battery(), _at(19), plan, _flat(0.0))
        assert result.basis == BASIS_RATE_LIMITED
        assert result.charge_added_pct == pytest.approx(0.5 * 155 / 60 / CAPACITY_KWH * 100)
        assert result.soc == pytest.approx(66.0 + result.charge_added_pct)

    def test_an_unknown_charge_rate_assumes_the_target(self):
        plan = _plan(charge_power_kw=0.0)
        result = project_sunrise_with_charge(_battery(), _at(19), plan, _flat(0.0))
        assert result.basis == BASIS_RATE_UNKNOWN
        assert result.soc == pytest.approx(90.0)

    def test_the_house_runs_the_battery_down_from_the_end_of_the_window_to_sunrise(self):
        """04:35 to 08:00 is 205 minutes of load at 0.55 kWh an hour."""
        result = project_sunrise_with_charge(_battery(), _at(19), _plan(), _flat(0.55))
        after = 90.0 - 0.55 * 205 / 60 / CAPACITY_KWH * 100
        assert result.soc == pytest.approx(after)

    def test_the_load_before_the_window_does_not_reach_the_figure_at_sunrise_when_it_refills(self):
        """From 23:00 the battery runs down for 3 h, the window refills it, 205 minutes follow."""
        _, without_charge, _ = estimate_will_survive_night(
            NightEstimateInputs(100.0, CAPACITY_KWH, MIN_SOC, 9.0, 0.30)
        )
        plan = _plan(target_soc=100.0)
        result = project_sunrise_with_charge(_battery(soc=100.0), _at(23), plan, _flat(0.30))
        assert result.soc == pytest.approx(100.0 - 0.30 * 205 / 60 / CAPACITY_KWH * 100)
        assert result.soc > without_charge


class TestTheWindowIsSizedForTheSocWhenItOpens:
    def test_the_sized_window_is_used_when_the_charge_has_not_started(self):
        sized = []

        def size(soc: float) -> ChargeWindow:
            sized.append(soc)
            return _window("02:00", "06:00")

        plan = _plan(_window("02:00", "03:00"), size_window=size)
        result = project_sunrise_with_charge(_battery(), _at(19), plan, _flat(0.0))
        assert sized == [pytest.approx(66.0)]
        assert result.charge_window == "02:00 to 06:00"
        # 3.6 kW for 4 h is far more than the deficit, so it reaches the target.
        assert result.soc == pytest.approx(90.0)

    def test_a_longer_sized_window_delivers_more_than_the_published_one(self):
        short = _plan(_window("02:00", "03:00"), target_soc=100.0)
        longer = _plan(
            _window("02:00", "03:00"),
            target_soc=100.0,
            size_window=lambda soc: _window("02:00", "05:00"),
        )
        battery = _battery(soc=10.0)
        assert (
            project_sunrise_with_charge(battery, _at(19), longer, _flat(0.0)).soc
            > project_sunrise_with_charge(battery, _at(19), short, _flat(0.0)).soc
        )

    def test_a_window_that_is_running_is_not_sized_again(self):
        def size(soc: float) -> ChargeWindow:
            raise AssertionError("a running window keeps its end")

        plan = _plan(size_window=size)
        result = project_sunrise_with_charge(_battery(soc=50.0), _at(3), plan, _flat(0.0))
        assert result.charge_window == "02:00 to 04:35"


class TestAWindowThatIsRunning:
    def test_it_starts_from_the_current_soc(self):
        result = project_sunrise_with_charge(_battery(soc=50.0), _at(3), _plan(), _flat(0.0))
        assert result.soc_at_charge_start == 50.0

    def test_only_the_rest_of_the_window_adds_charge(self):
        """03:00 to 04:35 is 95 minutes at 3.6 kW, 5.7 kWh, which would pass the target."""
        plan = _plan(charge_power_kw=1.0)
        result = project_sunrise_with_charge(_battery(soc=50.0), _at(3), plan, _flat(0.0))
        assert result.charge_added_pct == pytest.approx(95 / 60 / CAPACITY_KWH * 100)
        assert result.basis == BASIS_RATE_LIMITED

    def test_a_window_that_ends_at_this_minute_has_finished(self):
        result = project_sunrise_with_charge(
            _battery(soc=90.0, without_charge=80.0), _at(4, 35), _plan(), _flat()
        )
        assert result.basis == BASIS_NOT_BEFORE_SUNRISE


class TestMidnightWrap:
    def test_a_window_across_midnight_before_it_opens(self):
        plan = _plan(_window("23:30", "05:30"))
        result = project_sunrise_with_charge(_battery(), _at(22), plan, _flat(0.3))
        # 1 h 30 min to the window, 05:30 to 08:00 afterwards.
        assert result.soc_at_charge_start == pytest.approx(66.0 - 0.3 * 1.5 / CAPACITY_KWH * 100)
        assert result.soc == pytest.approx(90.0 - 0.3 * 2.5 / CAPACITY_KWH * 100)

    @pytest.mark.parametrize(("hour", "minute"), [(23, 45), (1, 0), (5, 0)])
    def test_a_window_across_midnight_while_it_runs(self, hour, minute):
        plan = _plan(_window("23:30", "05:30"))
        result = project_sunrise_with_charge(_battery(soc=40.0), _at(hour, minute), plan, _flat(0.0))
        assert result.soc_at_charge_start == 40.0
        assert result.charge_window == "23:30 to 05:30"

    def test_the_sunrise_after_midnight_is_this_morning(self):
        """At 01:00 the night is 7 hours long, not 31."""
        plan = _plan(_window("02:00", "04:00"))
        result = project_sunrise_with_charge(_battery(soc=80.0), _at(1), plan, _flat(0.5))
        # 01:00 to 02:00 and 04:00 to 08:00 are loaded.
        assert result.soc == pytest.approx(90.0 - 0.5 * 4 / CAPACITY_KWH * 100)

    def test_at_exactly_sunrise_the_next_night_is_projected(self):
        """08:00 is the start of the day, so the next sunrise is 24 hours away."""
        result = project_sunrise_with_charge(_battery(soc=70.0), _at(8), _plan(), _flat(0.0))
        assert result.soc_at_charge_start == pytest.approx(70.0)
        assert result.soc == pytest.approx(90.0)


class TestTheWindowStraddlesSunrise:
    def test_the_charge_stops_at_sunrise(self):
        """A window from 06:00 to 10:00 charges for two hours before sunrise."""
        plan = _plan(_window("06:00", "10:00"), charge_power_kw=1.0)
        result = project_sunrise_with_charge(_battery(soc=50.0), _at(5), plan, _flat(0.0))
        assert result.charge_added_pct == pytest.approx(2.0 / CAPACITY_KWH * 100)
        assert result.soc == pytest.approx(50.0 + result.charge_added_pct)


class TestTheFloor:
    def test_the_soc_when_the_window_opens_never_falls_below_the_minimum(self):
        result = project_sunrise_with_charge(
            _battery(soc=15.0), _at(19), _plan(), _flat(1.5)
        )
        assert result.soc_at_charge_start == MIN_SOC

    def test_the_figure_at_sunrise_never_falls_below_the_minimum(self):
        plan = _plan(target_soc=20.0)
        result = project_sunrise_with_charge(_battery(), _at(19), plan, _flat(3.0))
        assert result.soc == MIN_SOC

    def test_a_battery_that_runs_flat_before_the_window_still_charges_from_the_minimum(self):
        plan = _plan(charge_power_kw=1.0)
        result = project_sunrise_with_charge(_battery(soc=12.0), _at(19), plan, _flat(1.0))
        assert result.soc_at_charge_start == MIN_SOC
        assert result.charge_added_pct == pytest.approx(155 / 60 / CAPACITY_KWH * 100)


def test_the_flat_load_is_the_same_every_hour():
    load = flat_load(0.6)
    assert load(0, 60) == pytest.approx(0.6)
    assert load(1000, 90) == pytest.approx(0.9)


class TestSlotLoad:
    def test_a_whole_slot_is_its_energy(self):
        slots = [0.1 * (n + 1) for n in range(48)]
        assert slot_load(slots)(60, 30) == pytest.approx(0.3)

    def test_a_span_across_slots_is_the_sum_of_their_shares(self):
        slots = [float(n) for n in range(48)]
        # 00:15 to 01:15: half of slot 0, all of slot 1, half of slot 2.
        assert slot_load(slots)(15, 60) == pytest.approx(0.0 * 0.5 + 1.0 + 2.0 * 0.5)

    def test_it_wraps_at_midnight(self):
        slots = [1.0] * 47 + [2.0]
        assert slot_load(slots)(23 * 60 + 30, 60) == pytest.approx(2.0 + 1.0)

    def test_a_start_past_midnight_wraps(self):
        slots = [float(n) for n in range(48)]
        assert slot_load(slots)(24 * 60 + 30, 30) == pytest.approx(1.0)

    def test_a_flat_profile_matches_the_flat_load(self):
        slots = [0.25] * 48
        assert slot_load(slots)(1000, 345) == pytest.approx(flat_load(0.5)(1000, 345))

    def test_the_projection_uses_the_profile_it_is_given(self):
        quiet = [0.0] * 48
        result = project_sunrise_with_charge(_battery(), _at(19), _plan(), slot_load(quiet))
        assert result.soc_at_charge_start == 66.0
        assert result.soc == pytest.approx(90.0)


class TestLoadNote:
    def test_a_charged_night_says_which_load_it_used(self):
        result = project_sunrise_with_charge(_battery(), _at(19), _plan(), _flat())
        assert with_load_note(result, LOAD_NOTE_PER_SLOT).basis.endswith(LOAD_NOTE_PER_SLOT)
        assert with_load_note(result, LOAD_NOTE_FLAT).basis.endswith(LOAD_NOTE_FLAT)

    def test_a_night_with_no_charge_is_left_as_it_is(self):
        result = project_sunrise_with_charge(_battery(), _at(19), _plan(skipped=True), _flat())
        assert with_load_note(result, LOAD_NOTE_PER_SLOT) == result
