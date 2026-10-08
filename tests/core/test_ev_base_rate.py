"""The decision behind the alert for a car that charges from the grid at the base rate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.const import (
    EV_BASE_RATE_ALERT_DELAY_S,
    EV_CHARGER_MIN_POWER_W,
)
from custom_components.givenergy_inverter_manager.core.ev_base_rate import (
    AlertAction,
    BaseRateReading,
    WatchState,
    watch_step,
)

START = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
DELAY = timedelta(seconds=EV_BASE_RATE_ALERT_DELAY_S)


def _reading(
    ev_w: float = 7200.0,
    grid_w: float = 7800.0,
    on_base: bool = True,
    next_cheap: str | None = "23:00",
) -> BaseRateReading:
    return BaseRateReading(
        ev_power_w=ev_w, grid_import_w=grid_w, on_base_rate=on_base, next_cheap_start=next_cheap
    )


def _run(readings_at: list[tuple[timedelta, BaseRateReading]]) -> list[AlertAction]:
    """Feed readings in order from START and collect the action of each step."""
    state, actions = WatchState(), []
    for offset, reading in readings_at:
        step = watch_step(state, reading, START + offset)
        state = step.state
        actions.append(step.action)
    return actions


class TestWhenTheAlertRaises:
    def test_a_grid_charge_in_the_base_rate_band_raises_once_the_delay_has_passed(self):
        actions = _run([(timedelta(0), _reading()), (DELAY, _reading())])
        assert actions == [AlertAction.NONE, AlertAction.RAISE]

    def test_it_waits_until_the_delay_has_passed(self):
        actions = _run([(timedelta(0), _reading()), (DELAY - timedelta(seconds=30), _reading())])
        assert actions == [AlertAction.NONE, AlertAction.NONE]

    def test_it_does_not_repeat_every_cycle(self):
        actions = _run(
            [
                (timedelta(0), _reading()),
                (DELAY, _reading()),
                (DELAY + timedelta(seconds=30), _reading()),
                (DELAY * 3, _reading()),
            ]
        )
        assert actions == [AlertAction.NONE, AlertAction.RAISE, AlertAction.NONE, AlertAction.NONE]

    def test_the_charger_minimum_power_is_the_charging_threshold(self):
        at_minimum = _reading(ev_w=EV_CHARGER_MIN_POWER_W, grid_w=EV_CHARGER_MIN_POWER_W)
        assert _run([(timedelta(0), at_minimum), (DELAY, at_minimum)])[-1] is AlertAction.RAISE

    def test_the_delay_is_counted_in_real_seconds_not_cycles(self):
        slow = [(timedelta(0), _reading()), (DELAY, _reading())]
        fast = [(timedelta(seconds=s), _reading()) for s in range(0, int(DELAY.total_seconds()), 30)]
        assert _run(slow)[-1] is AlertAction.RAISE
        assert AlertAction.RAISE not in _run(fast)


class TestWhenItStaysQuiet:
    @pytest.mark.parametrize(
        ("reading", "why"),
        [
            (_reading(ev_w=EV_CHARGER_MIN_POWER_W - 1), "the car draws less than a charging session"),
            (_reading(grid_w=EV_CHARGER_MIN_POWER_W - 1), "the grid supplies less than the minimum"),
            (_reading(grid_w=-3000.0), "the house is exporting, so the car runs on solar"),
            (_reading(on_base=False), "the rate in force is a timed band"),
            (_reading(next_cheap=None), "the tariff has no cheaper band"),
        ],
        ids=lambda value: value if isinstance(value, str) else "",
    )
    def test_no_alert(self, reading, why):
        actions = _run([(timedelta(0), reading), (DELAY * 2, reading)])
        assert actions == [AlertAction.NONE, AlertAction.NONE], why

    def test_a_flat_tariff_never_alerts(self):
        flat = _reading(next_cheap=None)
        actions = _run([(timedelta(seconds=s), flat) for s in range(0, 7200, 30)])
        assert set(actions) == {AlertAction.NONE}


class TestWhenItClears:
    def test_the_alert_clears_when_the_session_ends(self):
        idle = _reading(ev_w=0.0, grid_w=800.0)
        actions = _run(
            [
                (timedelta(0), _reading()),
                (DELAY, _reading()),
                (DELAY + timedelta(seconds=30), idle),
                (DELAY + timedelta(seconds=60), idle),
            ]
        )
        assert actions == [
            AlertAction.NONE,
            AlertAction.RAISE,
            AlertAction.CLEAR,
            AlertAction.NONE,
        ]

    def test_the_alert_clears_when_the_rate_drops_to_a_timed_band(self):
        cheap = _reading(on_base=False, next_cheap=None)
        actions = _run(
            [(timedelta(0), _reading()), (DELAY, _reading()), (DELAY + timedelta(seconds=30), cheap)]
        )
        assert actions[-1] is AlertAction.CLEAR

    def test_nothing_clears_when_nothing_was_raised(self):
        idle = _reading(ev_w=0.0)
        assert _run([(timedelta(0), _reading()), (timedelta(seconds=30), idle)]) == [
            AlertAction.NONE,
            AlertAction.NONE,
        ]

    def test_a_short_dip_before_the_delay_restarts_the_count(self):
        idle = _reading(ev_w=0.0)
        actions = _run(
            [
                (timedelta(0), _reading()),
                (DELAY - timedelta(seconds=30), _reading()),
                (DELAY, idle),
                (DELAY + timedelta(seconds=30), _reading()),
                (DELAY * 2 - timedelta(seconds=30), _reading()),
                (DELAY * 2 + timedelta(seconds=30), _reading()),
            ]
        )
        assert actions == [
            AlertAction.NONE,
            AlertAction.NONE,
            AlertAction.NONE,
            AlertAction.NONE,
            AlertAction.NONE,
            AlertAction.RAISE,
        ]


class TestAcrossABandBoundary:
    def test_a_session_that_enters_the_base_rate_band_alerts_after_the_delay(self):
        cheap = _reading(on_base=False, next_cheap=None)
        actions = _run(
            [
                (timedelta(0), cheap),
                (timedelta(seconds=30), _reading()),
                (timedelta(seconds=30) + DELAY, _reading()),
            ]
        )
        assert actions == [AlertAction.NONE, AlertAction.NONE, AlertAction.RAISE]

    def test_a_session_that_leaves_the_base_rate_band_clears_and_stays_quiet(self):
        cheap = _reading(on_base=False, next_cheap=None)
        actions = _run(
            [
                (timedelta(0), _reading()),
                (DELAY, _reading()),
                (DELAY + timedelta(seconds=30), cheap),
                (DELAY * 4, cheap),
            ]
        )
        assert actions == [
            AlertAction.NONE,
            AlertAction.RAISE,
            AlertAction.CLEAR,
            AlertAction.NONE,
        ]

    def test_the_same_session_alerts_again_on_a_later_base_rate_stretch(self):
        cheap = _reading(on_base=False, next_cheap=None)
        later = DELAY * 5
        actions = _run(
            [
                (timedelta(0), _reading()),
                (DELAY, _reading()),
                (DELAY + timedelta(seconds=30), cheap),
                (later, _reading()),
                (later + DELAY, _reading()),
            ]
        )
        assert actions == [
            AlertAction.NONE,
            AlertAction.RAISE,
            AlertAction.CLEAR,
            AlertAction.NONE,
            AlertAction.RAISE,
        ]
