"""A plan whose settings never read back is reported as not ok, and can be sent again."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.core.inverter_values import ChargePlan
from custom_components.givenergy_inverter_manager.inverter.givtcp.writer import GivTCPWriter
from tests.backend_contract import END, START
from tests.inverter.test_backend_contract import GivTCPHarness


@pytest.fixture(autouse=True)
def _no_write_retry_sleep(monkeypatch):
    monkeypatch.setitem(GivTCPWriter.write_verified.__globals__, "GIVTCP_WRITE_RETRY_SLEEP_S", 0)


class _DeafHarness(GivTCPHarness):
    """GivTCP with Real Time Control off: it accepts the call and never changes the state."""

    deaf = False

    async def _call_service(self, domain, service, data):
        if self.deaf:
            self.writes.append((service, data["entity_id"], None))
            return
        await super()._call_service(domain, service, data)


PLAN = ChargePlan.for_target(80, START, END)


async def test_a_plan_that_reads_back_is_ok():
    harness = _DeafHarness()

    result = await harness.backend.apply_charge_plan(harness.cfg, PLAN)

    assert result.ok


async def test_settings_that_never_read_back_are_listed_by_name():
    harness = _DeafHarness()
    harness.deaf = True

    result = await harness.backend.apply_charge_plan(harness.cfg, PLAN)

    assert not result.ok
    assert set(result.failed_steps) == {
        "enable charge schedule (not confirmed)",
        "charge window start (not confirmed)",
        "charge window end (not confirmed)",
        "charge target (not confirmed)",
        "enable charge target (not confirmed)",
    }


async def test_a_setting_that_already_held_its_value_is_not_reported():
    harness = _DeafHarness()
    harness.set_target(80)  # the target is already right, so only the others are unconfirmed
    harness.deaf = True

    result = await harness.backend.apply_charge_plan(harness.cfg, PLAN)

    assert "charge target (not confirmed)" not in result.failed_steps
    assert "charge window start (not confirmed)" in result.failed_steps


async def test_the_same_values_can_be_sent_again_at_once_when_they_did_not_take():
    harness = _DeafHarness()
    harness.deaf = True
    await harness.backend.apply_charge_plan(harness.cfg, PLAN)
    first = harness.device_writes()
    assert first > 0

    harness.deaf = False
    result = await harness.backend.apply_charge_plan(harness.cfg, PLAN)

    assert result.ok
    assert harness.device_writes() > first
    assert harness.target() == 80


async def test_a_plan_that_took_keeps_its_cooldown_so_the_same_values_are_not_resent():
    harness = _DeafHarness()
    await harness.backend.apply_charge_plan(harness.cfg, PLAN)
    sent = harness.device_writes()

    await harness.backend.apply_charge_plan(harness.cfg, PLAN)

    assert harness.device_writes() == sent
