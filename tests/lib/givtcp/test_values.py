"""The inverter value types are frozen, and the fake backend satisfies the interface."""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import time

import pytest

from custom_components.givenergy_inverter_manager.inverter.backend import InverterBackend
from custom_components.givenergy_inverter_manager.lib.givtcp.values import (
    ChargePlan,
    FeedState,
    FeedStatus,
    InverterIdentity,
    InverterValues,
    RateDefaults,
    WriteResult,
)
from tests.fakes.fake_inverter import FakeInverter, FakeSlot

_PLAN = ChargePlan(target_soc=80, window_start=time(0, 30), window_end=time(4, 30),
                   enable_charge_target=True)


@pytest.mark.parametrize(
    ("value", "field"),
    [
        (InverterIdentity("SN", "givtcp_", "Inverter"), "serial"),
        (InverterValues(), "solar_power_w"),
        (_PLAN, "target_soc"),
        (RateDefaults(), "day_rate"),
        (WriteResult(), "failed_steps"),
        (FeedStatus(FeedState.PUBLISHING), "state"),
    ],
)
def test_each_value_type_is_frozen(value, field):
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, field, None)


def test_values_default_to_a_quiet_inverter_with_no_counters():
    values = InverterValues()

    assert values.solar_power_w == 0.0
    assert values.battery_charge_rate_w is None
    assert values.data_age_s is None
    assert values.unavailable_inputs == ()


def test_a_write_result_is_ok_only_when_no_step_failed():
    assert WriteResult().ok
    assert not WriteResult(("charge target",)).ok


def test_only_a_publishing_feed_is_publishing():
    assert FeedStatus(FeedState.PUBLISHING).is_publishing
    assert not any(
        FeedStatus(state).is_publishing for state in FeedState if state is not FeedState.PUBLISHING
    )


def test_the_fake_inverter_is_an_inverter_backend():
    assert isinstance(FakeInverter(), InverterBackend)


def test_the_fake_inverter_records_the_writes_it_is_given():
    fake = FakeInverter(slots=[FakeSlot(2, "00:00", "08:00")])

    asyncio.run(fake.apply_charge_plan({}, _PLAN))
    asyncio.run(fake.apply_floor_target({}, 40))
    asyncio.run(fake.clear_charge_slot(fake.other_active_charge_slots({})[0]))

    assert fake.plans == [_PLAN]
    assert fake.floor_targets == [40]
    assert [slot.number for slot in fake.cleared] == [2]
