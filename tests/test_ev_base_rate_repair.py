"""The repair that shows a car charging from the grid at the base rate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import homeassistant.helpers.issue_registry as ir
import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_BASE_RATE,
    CONF_RATE_PERIODS,
    EV_BASE_RATE_ALERT_DELAY_S,
)
from custom_components.givenergy_inverter_manager.repairs import (
    ISSUE_EV_BASE_RATE_CHARGING,
    LEARN_MORE_URLS,
)
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states

ZAPPI_PLUG = "sensor.myenergi_zappi_plug_status"
ZAPPI_STATUS = "sensor.myenergi_zappi_status"
ZAPPI_POWER = "sensor.myenergi_zappi_internal_load_ct1"
ZAPPI_SESSION = "sensor.myenergi_zappi_charge_added_session"
ZAPPI_MODE = "select.myenergi_zappi_charge_mode"
DELAY = timedelta(seconds=EV_BASE_RATE_ALERT_DELAY_S)
# Default tariff: Day (base) 0.3334, Night 23:00 to 08:00 at 0.1644, Nightboost 02:00 to 04:00.
MIDDAY = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
CHEAP_NIGHT = datetime(2026, 6, 15, 2, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_issue_mocks():
    ir.async_create_issue.reset_mock()
    ir.async_delete_issue.reset_mock()


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def advance(self, by: timedelta) -> None:
        self.now += by


@pytest.fixture
def clock(monkeypatch):
    clock = _Clock(MIDDAY)
    monkeypatch.setattr(FakeCoordinator, "_now", staticmethod(lambda: clock.now))
    return clock


def _charging(coord: FakeCoordinator, ev_w: float = 7200.0, grid_import_w: float = 7800.0) -> None:
    """A Zappi boosting at ev_w while the grid supplies grid_import_w (GivTCP: negative import)."""
    coord.set_states(
        {
            ZAPPI_PLUG: "EV Connected",
            ZAPPI_STATUS: "Boosting" if ev_w else "Paused",
            ZAPPI_POWER: str(ev_w),
            ZAPPI_SESSION: "3.2",
            ZAPPI_MODE: "Fast",
            "sensor.grid": str(-grid_import_w),
        }
    )


def _coord(**cfg_overrides) -> FakeCoordinator:
    coord = FakeCoordinator(cfg=_cfg(**cfg_overrides))
    coord.set_states(_default_states())
    return coord


def _raised() -> list[dict]:
    return [
        c.kwargs
        for c in ir.async_create_issue.call_args_list
        if c.args[2] == ISSUE_EV_BASE_RATE_CHARGING
    ]


def _cleared() -> int:
    return sum(
        1 for c in ir.async_delete_issue.call_args_list if c.args[2] == ISSUE_EV_BASE_RATE_CHARGING
    )


async def _cycles(coord: FakeCoordinator, clock: _Clock, span: timedelta) -> None:
    """Run a cycle now and then one every 30 seconds until span has passed."""
    await coord._async_update_data()
    elapsed = timedelta(0)
    while elapsed < span:
        clock.advance(timedelta(seconds=30))
        elapsed += timedelta(seconds=30)
        await coord._async_update_data()


@pytest.mark.asyncio
async def test_a_grid_charge_at_the_base_rate_raises_one_warning_after_the_delay(clock):
    coord = _coord()
    _charging(coord)

    await _cycles(coord, clock, DELAY - timedelta(seconds=30))
    assert _raised() == []
    await _cycles(coord, clock, timedelta(seconds=60))

    (issue,) = _raised()
    assert issue["is_fixable"] is False
    assert issue["severity"] == "warning"
    assert issue["translation_key"] == ISSUE_EV_BASE_RATE_CHARGING
    assert issue["learn_more_url"] == LEARN_MORE_URLS[ISSUE_EV_BASE_RATE_CHARGING]
    assert issue["translation_placeholders"] == {
        "power_kw": "7.2",
        "rate_name": "Day",
        "next_cheap_start": "23:00",
    }


@pytest.mark.asyncio
async def test_it_is_raised_once_for_the_session_not_every_cycle(clock):
    coord = _coord()
    _charging(coord)

    await _cycles(coord, clock, DELAY * 4)

    assert len(_raised()) == 1


@pytest.mark.asyncio
async def test_the_issue_clears_when_the_session_ends(clock):
    coord = _coord()
    _charging(coord)
    await _cycles(coord, clock, DELAY + timedelta(seconds=30))
    assert len(_raised()) == 1

    _charging(coord, ev_w=0.0, grid_import_w=800.0)
    clock.advance(timedelta(seconds=30))
    await coord._async_update_data()

    assert _cleared() == 1


@pytest.mark.asyncio
async def test_a_session_that_ends_before_the_delay_raises_nothing(clock):
    coord = _coord()
    _charging(coord)
    await _cycles(coord, clock, DELAY - timedelta(seconds=60))

    _charging(coord, ev_w=0.0, grid_import_w=800.0)
    await _cycles(coord, clock, DELAY * 2)

    assert _raised() == []
    assert _cleared() == 0


@pytest.mark.asyncio
async def test_a_charge_in_a_cheap_band_raises_nothing(clock):
    clock.now = CHEAP_NIGHT
    coord = _coord()
    _charging(coord)

    await _cycles(coord, clock, DELAY * 3)

    assert _raised() == []


@pytest.mark.asyncio
async def test_a_charge_on_solar_in_the_base_rate_band_raises_nothing(clock):
    coord = _coord()
    _charging(coord, grid_import_w=-2500.0)

    await _cycles(coord, clock, DELAY * 3)

    assert _raised() == []


@pytest.mark.asyncio
async def test_the_issue_clears_when_the_rate_drops_into_a_cheap_band(clock):
    clock.now = datetime(2026, 6, 15, 22, 52, tzinfo=timezone.utc)
    coord = _coord()
    _charging(coord)
    await _cycles(coord, clock, DELAY + timedelta(seconds=30))
    assert len(_raised()) == 1
    assert _cleared() == 0

    clock.now = datetime(2026, 6, 15, 23, 1, tzinfo=timezone.utc)
    await coord._async_update_data()

    assert _cleared() == 1


@pytest.mark.asyncio
async def test_a_session_that_enters_the_base_rate_band_raises_after_the_delay(clock):
    clock.now = datetime(2026, 6, 15, 7, 58, tzinfo=timezone.utc)
    coord = _coord()
    _charging(coord)
    await _cycles(coord, clock, timedelta(seconds=90))
    assert _raised() == []

    await _cycles(coord, clock, DELAY + timedelta(seconds=30))

    assert len(_raised()) == 1


@pytest.mark.asyncio
async def test_a_tariff_with_no_cheaper_band_never_raises(clock):
    coord = _coord(**{CONF_RATE_PERIODS: []})
    _charging(coord)

    await _cycles(coord, clock, DELAY * 3)

    assert _raised() == []


@pytest.mark.asyncio
async def test_a_band_dearer_than_the_base_rate_does_not_count_as_cheaper(clock):
    peak = [{"name": "Peak", "rate": 0.5, "start": "17:00", "end": "19:00"}]
    coord = _coord(**{CONF_RATE_PERIODS: peak, CONF_BASE_RATE: 0.3334})
    _charging(coord)

    await _cycles(coord, clock, DELAY * 3)

    assert _raised() == []


@pytest.mark.asyncio
async def test_an_install_with_no_charger_creates_and_clears_nothing(clock):
    coord = _coord()
    coord.set_state("sensor.grid", "-7800")

    await _cycles(coord, clock, DELAY * 3)

    assert coord._ev_charger is None
    assert _raised() == []
    assert _cleared() == 0


@pytest.mark.asyncio
async def test_a_charger_that_disappears_mid_session_clears_the_issue(clock):
    coord = _coord()
    _charging(coord)
    await _cycles(coord, clock, DELAY + timedelta(seconds=30))
    assert len(_raised()) == 1

    coord._ev_charger = None
    clock.advance(timedelta(seconds=30))
    await coord._async_update_data()

    assert _cleared() == 1
