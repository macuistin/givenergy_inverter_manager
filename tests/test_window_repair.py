"""A charge window that something else moved into the day rate is put back."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from custom_components.givenergy_inverter_manager.const import CONF_DRY_RUN
from tests.fakes.fake_inverter import FakeInverter
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states

NOW = datetime(2026, 10, 13, 22, 31, tzinfo=timezone.utc)
ENTITY = "select.charge_end"
TARGET = "number.target_soc"
MANAGER_WRITE = {"time": NOW.isoformat(), "entity_id": TARGET, "value": "95", "reason": "target"}


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(FakeCoordinator, "_now", staticmethod(lambda: NOW))


def _coord(*, window=("02:00:00", "00:10:00"), written=True, **cfg):
    coord = FakeCoordinator(cfg=_cfg(**cfg))
    coord.set_states(_default_states())
    backend = FakeInverter(window=window)
    coord._backend = backend
    coord.data = MagicMock(charge_window=None)
    if written:
        coord._acc.state.register_write_log.append(MANAGER_WRITE)
    return coord, backend


async def _settle(coord) -> None:
    while coord.tasks_created:
        await coord.tasks_created.pop(0)


async def _run(coord, at=NOW) -> None:
    coord._maybe_repair_window(at)
    await _settle(coord)


def _notes(coord) -> list[dict]:
    return [e for e in coord._acc.state.register_write_log if e["reason"] == "window repair"]


async def test_a_window_into_the_day_rate_is_set_back_to_the_cheap_period(clock):
    coord, backend = _coord()

    await _run(coord)

    assert backend.window_writes == [("02:00:00", "04:00:00")]
    assert backend.window == ("02:00:00", "04:00:00")


async def test_only_the_window_is_written_not_the_target_or_the_switches(clock):
    coord, backend = _coord()
    backend.target_soc = 95

    await _run(coord)

    assert backend.plans == []
    assert backend.target_soc == 95


async def test_the_repair_is_logged_with_what_was_found(clock):
    coord, _ = _coord()

    await _run(coord)

    [note] = _notes(coord)
    assert note["entity_id"] == ENTITY
    assert "02:00 to 00:10" in note["value"]
    assert "set back to 02:00 to 04:00" in note["value"]


async def test_a_good_window_is_not_touched(clock):
    coord, backend = _coord(window=("02:00:00", "04:00:00"))

    await _run(coord)

    assert backend.window_writes == []
    assert _notes(coord) == []


async def test_a_schedule_the_manager_never_wrote_is_not_touched(clock):
    coord, backend = _coord(written=False)

    await _run(coord)

    assert backend.window_writes == []


async def test_a_manual_charge_override_is_not_touched(clock):
    coord, backend = _coord()
    coord.override_charge_enabled = True

    await _run(coord)

    assert backend.window_writes == []


async def test_dry_run_says_what_it_would_do_and_writes_nothing(clock):
    coord, backend = _coord(**{CONF_DRY_RUN: True})

    await _run(coord)
    await _run(coord, NOW + timedelta(seconds=30))

    assert backend.window_writes == []
    assert coord._dry_run_last_skipped.startswith("Would repair the charge window")
    assert _notes(coord) == []


async def test_a_write_the_inverter_does_not_take_is_not_tried_again_for_a_few_minutes(clock):
    coord, backend = _coord()
    backend.fail_steps = ("charge window end",)

    await _run(coord)
    await _run(coord, NOW + timedelta(minutes=1))
    assert len(_notes(coord)) == 1

    backend.fail_steps = ()
    await _run(coord, NOW + timedelta(minutes=6))

    assert len(_notes(coord)) == 2
    assert backend.window == ("02:00:00", "04:00:00")


async def test_it_gives_up_for_the_day_after_the_limit(clock):
    coord, backend = _coord()
    backend.fail_steps = ("charge window end",)

    for minute in range(0, 60, 6):
        await _run(coord, NOW + timedelta(minutes=minute))

    assert len(_notes(coord)) == 3
    assert backend.window_writes == []
