"""The charge plan and the charge window write the end first when the window moves later."""

from __future__ import annotations

from datetime import time

import pytest

from custom_components.givenergy_inverter_manager.lib.givtcp import (
    ChargePlan,
    GivTCPPorts,
    make_backend,
)
from custom_components.givenergy_inverter_manager.lib.givtcp.keys import (
    KEY_CHARGE_END_TIME_ENTITY,
    KEY_CHARGE_START_TIME_ENTITY,
    KEY_ENABLE_CHARGE_SCHEDULE,
    KEY_ENABLE_CHARGE_TARGET,
    KEY_INVERTER_SERIAL,
    KEY_TARGET_SOC_ENTITY,
)

from .test_schedules import TIMES, _Bus, _no_read_back_wait, _state  # noqa: F401

START = "select.charge_start"
END = "select.charge_end"
CFG = {
    KEY_INVERTER_SERIAL: "SA1",
    KEY_CHARGE_START_TIME_ENTITY: START,
    KEY_CHARGE_END_TIME_ENTITY: END,
    KEY_ENABLE_CHARGE_SCHEDULE: "switch.schedule",
    KEY_ENABLE_CHARGE_TARGET: "switch.target_on",
    KEY_TARGET_SOC_ENTITY: "number.target",
}


def _bus(start: str, end: str) -> _Bus:
    return _Bus(
        {
            START: _state(start, options=TIMES),
            END: _state(end, options=TIMES),
            "switch.schedule": _state("off"),
            "switch.target_on": _state("off"),
            "number.target": _state("50"),
        }
    )


def _backend(bus: _Bus):
    return make_backend(CFG, GivTCPPorts(bus.get_state, bus.call_service, lambda count: None))


def _plan(start: time, end: time) -> ChargePlan:
    return ChargePlan(target_soc=80, window_start=start, window_end=end, enable_charge_target=True)


@pytest.mark.parametrize(
    ("current", "new", "first"),
    [
        (("01:00:00", "02:00:00"), (time(3, 0), time(4, 0)), END),
        (("03:00:00", "04:00:00"), (time(1, 0), time(2, 0)), START),
    ],
)
async def test_the_charge_plan_writes_the_window_so_no_gap_opens(current, new, first):
    bus = _bus(*current)

    result = await _backend(bus).apply_charge_plan(CFG, _plan(*new))

    window = [entity for entity, _ in bus.written if entity in (START, END)]
    assert result.ok
    assert window[0] == first
    assert bus.written[0][0] == "switch.schedule"
    assert bus.written[-1][0] == "switch.target_on"


@pytest.mark.parametrize(
    ("current", "new", "first"),
    [
        (("01:00:00", "02:00:00"), (time(3, 0), time(4, 0)), END),
        (("03:00:00", "04:00:00"), (time(1, 0), time(2, 0)), START),
    ],
)
async def test_the_charge_window_alone_is_written_so_no_gap_opens(current, new, first):
    bus = _bus(*current)

    assert await _backend(bus).apply_charge_window(CFG, *new)

    assert bus.written[0][0] == first
    assert bus.states[START].state == new[0].strftime("%H:%M:%S")
    assert bus.states[END].state == new[1].strftime("%H:%M:%S")
