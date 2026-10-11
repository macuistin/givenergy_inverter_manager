"""The engine publishes the SoC at sunrise with and without tonight's planned charge.

estimated_soc_at_sunrise is the projection with no charge, and it still feeds night survival.
sunrise_with_charge adds the planned charge window. In the evening the first sits on the minimum
SoC while the second says where the night will end.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.givenergy_inverter_manager.core.charge_hold import HeldCharge
from custom_components.givenergy_inverter_manager.core.solar_day import HeldSolarDay
from custom_components.givenergy_inverter_manager.core.sunrise_charge import (
    BASIS_ABOVE_TARGET,
    BASIS_NOT_BEFORE_SUNRISE,
    BASIS_RATE_LIMITED,
    BASIS_RATE_UNKNOWN,
    BASIS_REACHES_TARGET,
    BASIS_SKIPPED,
    LOAD_NOTE_FLAT,
    LOAD_NOTE_PER_SLOT,
)
from custom_components.givenergy_inverter_manager.core.sunrise_hold import HeldSunrise
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run

CAPACITY_KWH = 9.5
INVERTER_W = 3600.0
BASE_W = 550.0
MIN_SOC = 10.0
EVENING = datetime(2026, 6, 15, 19, 0)

# A learned day: the evening and the day use energy, the small hours hardly any.
# 16 night slots (00:00 to 08:00) weigh 0.05, the other 32 weigh 1.0.
NIGHT_PROFILE = [0.05] * 16 + [1.0] * 32

SINGLE_NIGHT_PERIOD = [{"name": "Night", "rate": 0.1644, "start": "23:00", "end": "08:00"}]


def _pct(kwh: float) -> float:
    return kwh / CAPACITY_KWH * 100


def _data(
    now: datetime,
    soc: float,
    *,
    base_w: float = BASE_W,
    rate_w="default",
    charging: bool = False,
    **kw,
):
    """One engine cycle for a house that has used base_w since midnight."""
    minute_of_day = now.hour * 60 + now.minute
    acc = EnergyAccumulator()
    acc.house_kwh = base_w / 1000 * minute_of_day / 60
    raw = _raw(
        battery_soc=soc,
        battery_capacity_kwh=CAPACITY_KWH,
        inverter_max_w=INVERTER_W,
        solar_power_w=0.0,
        house_load_w=base_w,
        battery_power_w=INVERTER_W if charging else 0.0,
        grid_power_w=INVERTER_W + base_w if charging else base_w,
        battery_charge_rate_w=INVERTER_W if rate_w == "default" else rate_w,
        forecast_kwh_tomorrow=6.0,
    )
    cfg = kw.pop("cfg", _nightboost_cfg())
    kw.setdefault("override_charge_target", 90)
    data, _ = _run(raw=raw, cfg=cfg, now=now, acc=acc, **kw)
    return data


@pytest.fixture(scope="module")
def data():
    return _data(EVENING, 66.0)


class TestTheEveningFromTheReview:
    """66% at 19:00, a charge planned from 02:00, target 90."""

    def test_the_figure_without_a_charge_sits_on_the_minimum(self, data):
        assert data.estimated_soc_at_sunrise == MIN_SOC

    def test_night_survival_still_judges_the_figure_without_a_charge(self, data):
        assert data.will_survive_night is False
        assert data.survival_reason.startswith("Battery may run low")

    def test_the_figure_with_the_charge_ends_the_night_near_the_target(self, data):
        # 7 h at 0.55 kWh an hour takes the battery to 25.5% at 02:00. The window refills it to
        # 90% by 04:00, and 4 h at 0.55 kWh an hour follow.
        assert data.sunrise_with_charge.soc == pytest.approx(90.0 - _pct(0.55 * 4))

    def test_the_figures_that_make_it_up_are_published(self, data):
        projection = data.sunrise_with_charge
        assert projection.soc_at_charge_start == pytest.approx(66.0 - _pct(0.55 * 7))
        assert projection.charge_added_pct == pytest.approx(90.0 - projection.soc_at_charge_start)
        assert projection.charge_window == "02:00 to 04:00"
        assert projection.basis.startswith(BASIS_REACHES_TARGET)

    def test_the_two_figures_are_far_apart_because_of_the_charge(self, data):
        assert data.sunrise_with_charge.soc - data.estimated_soc_at_sunrise > 40.0


class TestNoChargeInTheNight:
    def test_a_skipped_night_gives_the_figure_without_a_charge(self):
        data = _data(EVENING, 66.0, override_skip_charge=True, override_charge_target=None)
        projection = data.sunrise_with_charge
        assert projection.soc == data.estimated_soc_at_sunrise
        assert projection.basis == BASIS_SKIPPED
        assert projection.charge_window is None
        assert projection.charge_added_pct == 0.0

    def test_a_window_that_has_finished_gives_the_figure_without_a_charge(self):
        data = _data(datetime(2026, 6, 15, 5, 0), 85.0)
        assert data.sunrise_with_charge.soc == data.estimated_soc_at_sunrise
        assert data.sunrise_with_charge.basis == BASIS_NOT_BEFORE_SUNRISE

    def test_a_tariff_with_no_timed_period_has_no_window_to_add(self):
        cfg = {**_nightboost_cfg(), "rate_periods": []}
        data = _data(EVENING, 66.0, cfg=cfg)
        assert data.sunrise_with_charge.soc == data.estimated_soc_at_sunrise


class TestTheCharge:
    def test_a_battery_above_the_target_when_the_window_opens_adds_nothing(self):
        data = _data(datetime(2026, 6, 15, 23, 0), 95.0, override_charge_target=50)
        projection = data.sunrise_with_charge
        assert projection.basis.startswith(BASIS_ABOVE_TARGET)
        assert projection.charge_added_pct == 0.0
        assert projection.soc_at_charge_start == pytest.approx(95.0 - _pct(0.55 * 3))

    def test_a_window_that_is_extended_is_sized_for_the_soc_when_it_opens(self):
        """At 1 kW the plan written at 19:00 ends 02:00 to 04:40. At 02:00 it runs to 08:00."""
        data = _data(EVENING, 66.0, rate_w=1000.0)
        assert data.published_charge_window.text == "02:00 to 04:40"
        projection = data.sunrise_with_charge
        assert projection.charge_window == "02:00 to 08:00"
        assert projection.basis.startswith(BASIS_RATE_LIMITED)
        assert projection.soc == pytest.approx(66.0 - _pct(0.55 * 7) + _pct(1.0 * 6))

    def test_an_unknown_charge_rate_assumes_the_target(self):
        data = _data(EVENING, 66.0, rate_w=None)
        assert data.sunrise_with_charge.basis.startswith(BASIS_RATE_UNKNOWN)
        assert data.sunrise_with_charge.soc == pytest.approx(90.0 - _pct(0.55 * 4))

    def test_a_window_across_midnight_before_it_opens(self):
        cfg = {**_nightboost_cfg(), "rate_periods": SINGLE_NIGHT_PERIOD}
        data = _data(datetime(2026, 6, 15, 22, 0), 66.0, cfg=cfg)
        projection = data.sunrise_with_charge
        assert projection.charge_window == "23:00 to 08:00"
        assert projection.soc_at_charge_start == pytest.approx(66.0 - _pct(0.55))

    def test_a_window_across_midnight_while_it_runs_starts_from_the_current_soc(self):
        cfg = {**_nightboost_cfg(), "rate_periods": SINGLE_NIGHT_PERIOD}
        data = _data(datetime(2026, 6, 16, 1, 0), 40.0, cfg=cfg)
        assert data.sunrise_with_charge.soc_at_charge_start == 40.0

    def test_the_figure_never_falls_below_the_minimum(self):
        data = _data(EVENING, 12.0, base_w=3000.0, rate_w=100.0)
        assert data.sunrise_with_charge.soc >= MIN_SOC
        assert data.sunrise_with_charge.soc_at_charge_start == MIN_SOC


# ── 19:00 to 08:00 through the engine ───────────────────────────────────────

STEP_MINUTES = 5
# A heavy house: the day's average is 28.8 kWh until midnight, then 15 kWh for half an hour.
HEAVY_W = 1200.0


def _path() -> list[tuple[float, bool]]:
    """(SoC, charging) each minute from 19:00 to 08:00.

    66% run down on the load until 02:00, charged at 3.6 kW to 90%, run down again.
    """
    soc, rows = 66.0, []
    for minute in range(13 * 60 + 1):
        clock = (19 * 60 + minute) % 1440
        charging = 2 * 60 <= clock < 4 * 60 + 30 and soc < 90.0
        rows.append((soc, charging))
        if charging:
            soc = min(90.0, soc + _pct(INVERTER_W / 1000 / 60))
        else:
            soc = max(MIN_SOC, soc - _pct(HEAVY_W / 1000 / 60))
    return rows


def _series(*, carry_state: bool, load_profile=None) -> list[tuple[datetime, float, float]]:
    """(time, figure without a charge, figure with it) every 5 minutes from 19:00 to 08:00."""
    held_charge, held_sunrise, held_solar = HeldCharge(), HeldSunrise(), HeldSolarDay()
    path = _path()
    rows = []
    for minute in range(0, 13 * 60 + STEP_MINUTES, STEP_MINUTES):
        now = EVENING + timedelta(minutes=minute)
        soc, charging = path[minute]
        data = _data(
            now,
            soc,
            base_w=HEAVY_W,
            charging=charging,
            load_profile=load_profile,
            held_charge=held_charge,
            held_sunrise=held_sunrise if carry_state else HeldSunrise(),
            held_solar=held_solar,
        )
        rows.append((now, data.estimated_soc_at_sunrise, data.sunrise_with_charge.soc))
    return rows


def _steps(values: list[float]) -> list[float]:
    return [abs(after - before) for before, after in zip(values, values[1:], strict=False)]


SUNRISE = datetime(2026, 6, 16, 8, 0)


@pytest.fixture(scope="module")
def paced():
    return _series(carry_state=True)


@pytest.fixture(scope="module")
def unpaced():
    return _series(carry_state=False)


class TestStabilityThroughTheNight:
    """The review counted jumps of more than 15 points in the figure between 19:00 and 08:00."""

    def test_the_figure_without_a_charge_sits_on_the_floor_all_evening(self, paced):
        evening = [no_charge for now, no_charge, _ in paced if now.hour >= 19]
        assert evening and all(value == MIN_SOC for value in evening)

    def test_the_calculated_figure_with_the_charge_really_steps_at_midnight(self, unpaced):
        """Premise: the load estimate resets at 00:00 and the figure follows it by 15 or more."""
        by_time = {now: with_charge for now, _, with_charge in unpaced}
        midnight = datetime(2026, 6, 16, 0, 0)
        assert abs(by_time[midnight] - by_time[midnight - timedelta(minutes=5)]) >= 15.0

    def test_the_published_figure_has_no_jump_over_15_points_before_sunrise(self, paced):
        before_sunrise = [with_charge for now, _, with_charge in paced if now < SUNRISE]
        assert max(_steps(before_sunrise)) <= 15.0

    def test_the_published_figure_has_no_jump_at_midnight(self, paced):
        by_time = {now: with_charge for now, _, with_charge in paced}
        midnight = datetime(2026, 6, 16, 0, 0)
        around = [by_time[midnight + timedelta(minutes=m)] for m in range(-30, 35, STEP_MINUTES)]
        assert max(_steps(around)) <= 15.0
        assert abs(by_time[midnight] - by_time[midnight - timedelta(hours=1)]) <= 15.0

    def test_the_published_figure_moves_no_faster_than_the_battery_can(self, paced):
        per_step = INVERTER_W / 1000 / CAPACITY_KWH * 100 * STEP_MINUTES / 60
        assert max(_steps([with_charge for _, _, with_charge in paced])) <= per_step + 1e-6

    def test_sampled_every_hour_the_figure_stays_within_15_points_until_the_window_is_over(
        self, paced
    ):
        hourly = [
            with_charge
            for now, _, with_charge in paced
            if now.minute == 0 and now < datetime(2026, 6, 16, 4, 0)
        ]
        assert len(hourly) == 9
        assert max(hourly) - min(hourly) <= 15.0

    def test_the_figure_without_a_charge_does_not_follow_the_charge(self, paced):
        """The figure that night survival reads stays on the floor while the charge runs."""
        overnight = [no_charge for now, no_charge, _ in paced if now < datetime(2026, 6, 16, 3, 0)]
        assert set(overnight) == {MIN_SOC}


class TestThePerSlotLoadProfile:
    """The figure with the charge reads the learned per-slot load, the one without stays flat."""

    @pytest.fixture(scope="class")
    def profiled(self):
        return _data(EVENING, 66.0, load_profile=NIGHT_PROFILE)

    def test_the_review_evening_reads_near_the_target(self, profiled):
        assert 88.0 <= profiled.sunrise_with_charge.soc <= 90.0

    def test_the_figure_without_a_charge_and_survival_stay_on_the_flat_load(self, profiled):
        flat = _data(EVENING, 66.0)
        assert profiled.estimated_soc_at_sunrise == flat.estimated_soc_at_sunrise == MIN_SOC
        assert profiled.will_survive_night is flat.will_survive_night is False
        assert profiled.survival_reason == flat.survival_reason

    def test_the_basis_says_the_per_slot_profile_was_used(self, profiled):
        assert profiled.sunrise_with_charge.basis.endswith(LOAD_NOTE_PER_SLOT)

    def test_without_a_profile_the_flat_load_is_used_and_the_basis_says_so(self):
        data = _data(EVENING, 66.0)
        assert data.sunrise_with_charge.basis.endswith(LOAD_NOTE_FLAT)
        assert data.sunrise_with_charge.soc == pytest.approx(90.0 - _pct(0.55 * 4))

    @pytest.mark.parametrize("profile", [[1.0] * 47, [0.0] * 48, [-1.0] + [1.0] * 47])
    def test_an_unusable_profile_falls_back_to_the_flat_load(self, profile):
        data = _data(EVENING, 66.0, load_profile=profile)
        assert data.sunrise_with_charge.basis.endswith(LOAD_NOTE_FLAT)
        assert data.sunrise_with_charge.soc == pytest.approx(90.0 - _pct(0.55 * 4))

    def test_a_skipped_night_is_the_flat_figure_whatever_the_profile(self):
        data = _data(
            EVENING, 66.0, override_skip_charge=True, override_charge_target=None,
            load_profile=NIGHT_PROFILE,
        )
        assert data.sunrise_with_charge.soc == data.estimated_soc_at_sunrise
        assert data.sunrise_with_charge.basis == BASIS_SKIPPED


@pytest.fixture(scope="module")
def paced_profiled():
    return _series(carry_state=True, load_profile=NIGHT_PROFILE)


class TestStabilityWithThePerSlotLoadProfile:
    def test_the_figure_stays_near_the_target_until_the_window_is_over(self, paced_profiled):
        planned = [w for now, _, w in paced_profiled if now < datetime(2026, 6, 16, 4, 0)]
        assert min(planned) >= 80.0

    def test_no_jump_over_15_points_before_sunrise(self, paced_profiled):
        before_sunrise = [w for now, _, w in paced_profiled if now < SUNRISE]
        assert max(_steps(before_sunrise)) <= 15.0

    def test_no_jump_at_midnight(self, paced_profiled):
        by_time = {now: w for now, _, w in paced_profiled}
        midnight = datetime(2026, 6, 16, 0, 0)
        around = [by_time[midnight + timedelta(minutes=m)] for m in range(-30, 35, STEP_MINUTES)]
        assert max(_steps(around)) <= 15.0

    def test_the_figure_without_a_charge_still_sits_on_the_floor_all_evening(self, paced_profiled):
        evening = [n for now, n, _ in paced_profiled if now.hour >= 19]
        assert evening and all(value == MIN_SOC for value in evening)


class TestTheHoldForTheFigureWithTheCharge:
    def test_it_is_made_once_and_is_not_the_hold_for_the_figure_without_a_charge(self):
        held = HeldSunrise(soc=40.0, at=EVENING)
        charged = held.charged()
        assert charged is held.charged()
        assert charged is not held
        assert (charged.soc, charged.at) == (None, None)

    def test_the_figures_are_published_at_their_own_pace(self):
        held = HeldSunrise()
        first = _data(EVENING, 66.0, held_sunrise=held)
        assert held.soc == first.estimated_soc_at_sunrise
        assert held.charged().soc == first.sunrise_with_charge.soc
        assert held.soc != held.charged().soc
