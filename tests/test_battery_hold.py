"""The battery hold writes the pause through its ports and puts the saved pause back."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.battery_hold import (
    BatteryHold,
    BatteryHoldPorts,
)
from custom_components.givenergy_inverter_manager.core.ev_battery_hold import HoldRecord
from custom_components.givenergy_inverter_manager.lib.givtcp.model import (
    BatteryPause,
    PauseSetting,
)
from custom_components.givenergy_inverter_manager.lib.givtcp.status import WriteStatus

NOW = datetime(2031, 3, 4, 10, 17, tzinfo=timezone.utc)
NIGHT = PauseSetting(BatteryPause.DISCHARGE, (time(23, 0), time(8, 0)))


class _Ports:
    """An inverter that keeps its pause and a store that keeps the record."""

    def __init__(self, live: PauseSetting | None = NIGHT) -> None:
        self.live = live
        self.writes: list[tuple[BatteryPause, tuple | None]] = []
        self.saved: list[HoldRecord | None] = []
        self.skipped: list[str] = []
        self.dry_run = False
        self.refuse = False

    async def apply(self, pause, window):
        self.writes.append((pause, window))
        if self.refuse:
            return WriteStatus.REFUSED
        self.live = PauseSetting(pause, window)
        return WriteStatus.WRITTEN

    async def save(self, record):
        self.saved.append(record)

    def ports(self) -> BatteryHoldPorts:
        return BatteryHoldPorts(
            read_pause=lambda: self.live,
            apply_pause=self.apply,
            save=self.save,
            is_dry_run=lambda: self.dry_run,
            record_skipped=self.skipped.append,
        )


def _hold(inverter: _Ports) -> BatteryHold:
    return BatteryHold(inverter.ports())


async def _draining(hold: BatteryHold, now: datetime) -> None:
    await hold.run(enabled=True, car_charging=True, car_draining=True, now=now)


async def _charging(hold: BatteryHold, now: datetime) -> None:
    await hold.run(enabled=True, car_charging=True, car_draining=False, now=now)


async def _stopped(hold: BatteryHold, now: datetime) -> None:
    await hold.run(enabled=True, car_charging=False, car_draining=False, now=now)


async def test_a_car_draining_the_battery_starts_a_hold_and_saves_the_pause_first():
    inverter = _Ports()
    hold = _hold(inverter)

    await _draining(hold, NOW)

    assert inverter.writes == [(BatteryPause.DISCHARGE, (time(10, 15), time(10, 45)))]
    assert inverter.saved[0].prior == NIGHT
    assert hold.holding


async def test_a_hold_that_the_inverter_does_not_take_leaves_no_record():
    inverter = _Ports()
    inverter.refuse = True
    hold = _hold(inverter)

    await _draining(hold, NOW)

    assert not hold.holding
    assert inverter.saved[-1] is None


async def test_the_hold_is_renewed_as_it_runs_out_and_the_saved_pause_is_kept():
    inverter = _Ports()
    hold = _hold(inverter)
    await _draining(hold, NOW)
    inverter.writes.clear()

    await _charging(hold, NOW + timedelta(minutes=10))
    assert inverter.writes == []

    await _charging(hold, NOW + timedelta(minutes=21))

    assert inverter.writes == [(BatteryPause.DISCHARGE, (time(10, 35), time(11, 5)))]
    assert hold.record.prior == NIGHT


async def test_a_renewal_the_inverter_does_not_take_keeps_the_hold_and_is_tried_again():
    inverter = _Ports()
    hold = _hold(inverter)
    await _draining(hold, NOW)
    inverter.refuse = True

    await _charging(hold, NOW + timedelta(minutes=21))
    assert hold.record.ends == NOW.replace(minute=45)

    inverter.refuse = False
    await _charging(hold, NOW + timedelta(minutes=22))

    assert hold.record.ends == NOW.replace(hour=11, minute=5)


async def test_the_saved_pause_is_written_back_once_the_car_has_stopped_for_five_minutes():
    inverter = _Ports()
    hold = _hold(inverter)
    await _draining(hold, NOW)
    inverter.writes.clear()

    await _stopped(hold, NOW + timedelta(minutes=1))
    await _stopped(hold, NOW + timedelta(minutes=5))
    assert inverter.writes == []

    await _stopped(hold, NOW + timedelta(minutes=6))

    assert inverter.writes == [(BatteryPause.DISCHARGE, (time(23, 0), time(8, 0)))]
    assert inverter.live == NIGHT
    assert not hold.holding
    assert inverter.saved[-1] is None


async def test_a_pause_that_was_off_is_put_back_off():
    inverter = _Ports(PauseSetting(BatteryPause.OFF))
    hold = _hold(inverter)
    await _draining(hold, NOW)

    await hold.run(enabled=False, car_charging=True, car_draining=False, now=NOW)

    assert inverter.writes[-1] == (BatteryPause.OFF, None)
    assert not hold.holding


async def test_a_pause_that_will_not_go_back_is_tried_again_next_cycle():
    inverter = _Ports()
    hold = _hold(inverter)
    await _draining(hold, NOW)
    inverter.refuse = True

    await hold.run(enabled=False, car_charging=True, car_draining=False, now=NOW)
    assert hold.holding

    inverter.refuse = False
    await hold.run(enabled=False, car_charging=True, car_draining=False, now=NOW)

    assert not hold.holding


async def test_a_record_saved_before_a_restart_is_ended_when_the_car_is_not_charging():
    inverter = _Ports(PauseSetting(BatteryPause.DISCHARGE, (time(10, 15), time(10, 45))))
    hold = _hold(inverter)
    hold.restore(HoldRecord(NIGHT, NOW + timedelta(minutes=30)))

    await _stopped(hold, NOW)
    await _stopped(hold, NOW + timedelta(minutes=5))

    assert inverter.live == NIGHT
    assert not hold.holding


async def test_dry_run_records_one_would_line_and_sends_nothing():
    inverter = _Ports()
    inverter.dry_run = True
    hold = _hold(inverter)

    await _draining(hold, NOW)
    await _draining(hold, NOW + timedelta(seconds=30))

    assert inverter.writes == []
    assert inverter.saved == []
    assert inverter.skipped == ["Would hold the house battery back while the car charges"]
    assert not hold.holding


async def test_dry_run_would_line_returns_after_the_car_stops_draining():
    inverter = _Ports()
    inverter.dry_run = True
    hold = _hold(inverter)
    await _draining(hold, NOW)

    await _stopped(hold, NOW + timedelta(minutes=1))
    await _draining(hold, NOW + timedelta(minutes=2))

    assert len(inverter.skipped) == 2


async def test_nothing_is_written_with_the_switch_off():
    inverter = _Ports()
    hold = _hold(inverter)

    await hold.run(enabled=False, car_charging=True, car_draining=True, now=NOW)

    assert inverter.writes == []
    assert inverter.saved == []


async def test_a_pause_that_cannot_be_read_starts_nothing():
    inverter = _Ports(None)
    hold = _hold(inverter)

    await _draining(hold, NOW)

    assert inverter.writes == []
    assert not hold.holding


@pytest.mark.parametrize("pause", [BatteryPause.CHARGE, BatteryPause.BOTH])
async def test_a_pause_that_stops_charging_is_left_alone(pause):
    inverter = _Ports(PauseSetting(pause, (time(1, 0), time(2, 0))))
    hold = _hold(inverter)

    await _draining(hold, NOW)

    assert inverter.writes == []
