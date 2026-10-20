"""The charge window and target are set back once a long night's window has closed."""

from __future__ import annotations

from datetime import datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.givenergy_inverter_manager.const import CONF_DRY_RUN, DEFAULT_BATTERY_MIN_SOC
from tests.fakes.fake_inverter import FakeInverter
from tests.test_charge_replan import TRIGGER, _Clock, _decision, _settle  # noqa: F401
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states

# The test tariff's cheapest period is 02:00 to 04:00. A long night is written to 07:15.
LONG_NIGHT = SimpleNamespace(start=time(2, 0), end=time(7, 15), extended=True)


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(FakeCoordinator, "_now", staticmethod(lambda: clock.now))
    return clock


def _coord(**cfg) -> tuple[FakeCoordinator, FakeInverter]:
    coord = FakeCoordinator(cfg=_cfg(**cfg))
    coord.set_states(_default_states())
    backend = FakeInverter()
    coord._backend = backend
    coord.data = MagicMock(charge_decision=_decision(100), charge_window=LONG_NIGHT)
    return coord, backend


async def _long_night(coord: FakeCoordinator) -> None:
    coord._write_charge_target_to_inverter(coord._now())
    await _settle(coord)


async def _at(coord, clock, hour: int, minute: int = 0, **new) -> None:
    from dataclasses import replace

    clock.now = datetime(2031, 3, 4, hour, minute, tzinfo=timezone.utc)
    if new:
        coord.data.charge_decision = replace(coord.data.charge_decision, **new)
    coord._maybe_settle_window(coord.data, clock.now)
    await _settle(coord)


async def test_after_the_window_closes_slot_1_and_the_target_go_back_to_the_plan(clock):
    coord, backend = _coord()
    await _long_night(coord)
    assert backend.plans[0].window_end == time(7, 15)

    await _at(coord, clock, 7, 16, target_soc=80, skip_charge=True)

    assert len(backend.plans) == 2
    assert backend.plans[1].window_end == time(4, 0)
    assert backend.plans[1].target_soc == DEFAULT_BATTERY_MIN_SOC


async def test_nothing_is_written_while_the_extended_window_is_open(clock):
    coord, backend = _coord()
    await _long_night(coord)

    await _at(coord, clock, 6, 0, skip_charge=True)

    assert len(backend.plans) == 1


async def test_it_writes_once_for_the_night(clock):
    coord, backend = _coord()
    await _long_night(coord)

    await _at(coord, clock, 7, 16, skip_charge=True)
    await _at(coord, clock, 12, 0, target_soc=55)
    await _at(coord, clock, 18, 0, target_soc=90)

    assert len(backend.plans) == 2


async def test_a_night_that_was_not_extended_is_left_alone(clock):
    coord, backend = _coord()
    coord.data.charge_window = None
    await _long_night(coord)

    await _at(coord, clock, 5, 0)

    assert len(backend.plans) == 1


async def test_dry_run_records_and_sends_nothing(clock):
    coord, backend = _coord(**{CONF_DRY_RUN: True})
    await _long_night(coord)

    await _at(coord, clock, 7, 16, skip_charge=True)

    assert backend.plans == []
    assert coord._dry_run_last_skipped.startswith("Would set back the 02:00 to 07:15 window")


async def test_a_manual_override_is_left_alone(clock):
    coord, backend = _coord()
    await _long_night(coord)
    coord.override_skip_charge = True

    await _at(coord, clock, 7, 16, skip_charge=True)

    assert len(backend.plans) == 1
