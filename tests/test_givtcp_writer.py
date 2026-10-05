"""
test_givtcp_writer.py: GivTCPWriter driven directly through its three seams.

A fake state dict and a recording service bus stand in for Home Assistant, so the
tests need no coordinator.
"""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

from custom_components.givenergy_inverter_manager.const import (
    GIVTCP_MAX_WRITE_RETRIES,
    GIVTCP_MIN_WRITE_INTERVAL_S,
    GIVTCP_WRITE_LIFETIME_WARN,
)
from custom_components.givenergy_inverter_manager.givtcp_writer import (
    GivTCPWriter,
    SwitchState,
    VerifiedWrite,
)


class _State:
    def __init__(self, state: str) -> None:
        self.state = state


class _Bus:
    """Recording service bus. By default a call sets the entity to the written value."""

    def __init__(self) -> None:
        self.states: dict[str, _State] = {}
        self.calls: list[tuple[str, str, dict]] = []
        self.counts: list[int] = []
        self.settle_on: int | None = 1  # call number from which the state follows the write
        self.error: Exception | None = None

    def get_state(self, entity_id: str):
        return self.states.get(entity_id)

    async def call_service(self, domain: str, service: str, data: dict) -> None:
        self.calls.append((domain, service, data))
        if self.error is not None:
            raise self.error
        if self.settle_on is not None and len(self.calls) >= self.settle_on:
            self.states[data["entity_id"]] = _State(_written_state(service, data))


def _written_state(service: str, data: dict) -> str:
    if service == "turn_on":
        return "on"
    if service == "turn_off":
        return "off"
    return str(data.get("option", data.get("value")))


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    monkeypatch.setitem(GivTCPWriter.write_verified.__globals__, "GIVTCP_WRITE_RETRY_SLEEP_S", 0)


@pytest.fixture
def bus() -> _Bus:
    return _Bus()


@pytest.fixture
def writer(bus) -> GivTCPWriter:
    return GivTCPWriter(bus.get_state, bus.call_service, bus.counts.append)


class TestReadBeforeWrite:
    async def test_switch_already_at_value_is_not_written(self, writer, bus):
        bus.states["switch.s"] = _State("on")
        assert await writer.set_switch("switch.s", SwitchState.ON, "s") is True
        assert bus.calls == []

    async def test_unavailable_switch_counts_as_off(self, writer, bus):
        bus.states["switch.s"] = _State("unavailable")
        assert await writer.set_switch("switch.s", SwitchState.OFF, "s") is True
        assert bus.calls == []

    async def test_number_compares_as_a_whole_number(self, writer, bus):
        bus.states["number.n"] = _State("80.0")
        assert await writer.set_number("number.n", 80, "n") is True
        assert bus.calls == []

    async def test_select_already_at_option_is_not_written(self, writer, bus):
        bus.states["select.o"] = _State("23:00:00")
        assert await writer.set_select("select.o", "23:00:00", "o") is True
        assert bus.calls == []

    @pytest.mark.parametrize("setter", ["set_switch", "set_select", "set_number"])
    async def test_missing_entity_id_is_not_written(self, writer, bus, setter):
        value = {"set_switch": SwitchState.ON, "set_select": "x", "set_number": 1}[setter]
        assert await getattr(writer, setter)(None, value, "n") is False
        assert bus.calls == []


class TestServiceCalls:
    async def test_switch_on_and_off_use_turn_on_and_turn_off(self, writer, bus):
        await writer.set_switch("switch.a", SwitchState.ON, "a")
        await writer.set_switch("switch.b", SwitchState.OFF, "b")
        bus.states["switch.b"] = _State("on")
        await writer.set_switch("switch.b", SwitchState.OFF, "b")
        assert bus.calls[0] == ("switch", "turn_on", {"entity_id": "switch.a"})
        assert bus.calls[-1] == ("switch", "turn_off", {"entity_id": "switch.b"})

    async def test_select_and_number_payloads(self, writer, bus):
        await writer.set_select("select.o", "Eco", "o")
        await writer.set_number("number.n", 80, "n")
        assert bus.calls == [
            ("select", "select_option", {"entity_id": "select.o", "option": "Eco"}),
            ("number", "set_value", {"entity_id": "number.n", "value": 80}),
        ]

    async def test_custom_write_uses_the_supplied_matcher(self, writer, bus):
        write = VerifiedWrite(
            domain="climate",
            service="set_temperature",
            payload={"entity_id": "climate.c", "temperature": 21},
            value=21,
            shown=21,
            name="c",
            step=0,
            matches=lambda state: state is not None and state.state == "21",
        )
        bus.states["climate.c"] = _State("18")
        bus.settle_on = None
        assert await writer.write_verified(write) is True
        assert len(bus.calls) == GIVTCP_MAX_WRITE_RETRIES


class TestRetry:
    async def test_confirmed_first_time_makes_one_call(self, writer, bus, caplog):
        with caplog.at_level(logging.WARNING):
            assert await writer.set_number("number.n", 80, "n") is True
        assert len(bus.calls) == 1
        assert caplog.records == []

    async def test_mismatch_is_retried_until_confirmed(self, writer, bus, caplog):
        bus.settle_on = 2
        with caplog.at_level(logging.WARNING):
            assert await writer.set_number("number.n", 80, "n") is True
        assert len(bus.calls) == 2
        assert [r.getMessage() for r in caplog.records] == [
            "n: attempt 1/3: wrote 80 but read back unknown, retrying"
        ]

    async def test_never_confirmed_gives_up_but_reports_sent(self, writer, bus, caplog):
        bus.settle_on = None
        with caplog.at_level(logging.WARNING):
            assert await writer.set_number("number.n", 80, "n") is True
        assert len(bus.calls) == GIVTCP_MAX_WRITE_RETRIES
        assert caplog.records[-1].getMessage() == "n: wrote 80 but could not confirm after 3 attempts"

    async def test_select_that_vanishes_is_a_failure(self, writer, bus, caplog):
        async def vanish(domain, service, data):
            bus.calls.append((domain, service, data))
            bus.states.pop(data["entity_id"], None)

        writer = GivTCPWriter(bus.get_state, vanish, bus.counts.append)
        bus.states["select.o"] = _State("old")
        with caplog.at_level(logging.WARNING):
            assert await writer.set_select("select.o", "new", "o") is False
        assert len(bus.calls) == 1
        assert "vanished" in caplog.records[-1].getMessage()

    async def test_number_that_vanishes_is_retried(self, writer, bus):
        async def vanish(domain, service, data):
            bus.calls.append((domain, service, data))

        writer = GivTCPWriter(bus.get_state, vanish, bus.counts.append)
        assert await writer.set_number("number.n", 80, "n") is True
        assert len(bus.calls) == GIVTCP_MAX_WRITE_RETRIES


class TestFailure:
    async def test_failed_call_returns_false_and_logs(self, writer, bus, caplog):
        bus.error = RuntimeError("boom")
        with caplog.at_level(logging.WARNING):
            assert await writer.set_number("number.n", 80, "n") is False
        assert any("number.n" in r.getMessage() for r in caplog.records)

    async def test_failed_call_is_not_counted(self, writer, bus):
        bus.error = RuntimeError("boom")
        await writer.set_number("number.n", 80, "n")
        assert writer.write_count == 0
        assert bus.counts == []

    async def test_failed_call_releases_the_cooldown(self, writer, bus):
        bus.error = RuntimeError("boom")
        await writer.set_number("number.n", 80, "n")
        assert ("number.n", 80) not in writer.last_write_time
        bus.error = None
        assert await writer.set_number("number.n", 80, "n") is True
        assert len(bus.calls) == 2


class TestCooldown:
    async def test_same_value_inside_the_window_is_not_rewritten(self, writer, bus):
        bus.settle_on = None
        await writer.set_number("number.n", 80, "n")
        calls = len(bus.calls)
        await writer.set_number("number.n", 80, "n")
        assert len(bus.calls) == calls

    async def test_different_value_inside_the_window_is_written(self, writer, bus):
        await writer.set_number("number.n", 80, "n")
        await writer.set_number("number.n", 60, "n")
        assert [c[2]["value"] for c in bus.calls] == [80, 60]

    async def test_switch_cooldown_is_per_state(self, writer, bus):
        await writer.set_switch("switch.s", SwitchState.ON, "s")
        await writer.set_switch("switch.s", SwitchState.OFF, "s")
        assert [c[1] for c in bus.calls] == ["turn_on", "turn_off"]

    async def test_write_is_allowed_again_after_the_window(self, writer, bus):
        bus.settle_on = None
        await writer.set_number("number.n", 80, "n")
        writer.last_write_time[("number.n", 80)] = (
            time.monotonic() - GIVTCP_MIN_WRITE_INTERVAL_S - 1
        )
        calls = len(bus.calls)
        await writer.set_number("number.n", 80, "n")
        assert len(bus.calls) > calls

    def test_cooldown_api_for_callers_that_write_themselves(self, writer):
        assert writer.cooldown_active("select.z", "z", "Eco+") is False
        writer.start_cooldown("select.z", "Eco+")
        assert writer.cooldown_active("select.z", "z", "Eco+") is True
        assert writer.cooldown_active("select.z", "z", "Fast") is False


class TestCounting:
    async def test_each_accepted_call_is_counted_and_reported(self, writer, bus):
        bus.settle_on = None
        await writer.set_number("number.n", 80, "n")
        assert writer.write_count == GIVTCP_MAX_WRITE_RETRIES
        assert bus.counts == [1, 2, 3]

    async def test_count_continues_from_a_restored_value(self, writer, bus):
        writer.write_count = 1000
        await writer.set_number("number.n", 80, "n")
        assert bus.counts == [1001]

    async def test_lifetime_warning_fires_once_at_the_limit(self, writer, bus, caplog):
        writer.write_count = GIVTCP_WRITE_LIFETIME_WARN - 1
        with caplog.at_level(logging.WARNING):
            await writer.set_number("number.n", 80, "n")
            await writer.set_number("number.n", 60, "n")
        warnings = [r for r in caplog.records if "rated lifetime" in r.getMessage()]
        assert len(warnings) == 1


class TestSerialisation:
    async def test_two_writers_never_overlap(self, bus):
        running = 0
        peak = 0

        async def slow_call(domain, service, data):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            bus.states[data["entity_id"]] = _State(str(data["value"]))
            running -= 1

        writer = GivTCPWriter(bus.get_state, slow_call, bus.counts.append)
        results = await asyncio.gather(
            writer.set_number("number.a", 1, "a"),
            writer.set_number("number.b", 2, "b"),
            writer.set_number("number.c", 3, "c"),
        )
        assert results == [True, True, True]
        assert peak == 1

    async def test_second_caller_sees_the_first_callers_cooldown(self, writer, bus):
        results = await asyncio.gather(
            writer.set_number("number.n", 80, "n"),
            writer.set_number("number.n", 80, "n"),
        )
        assert results == [True, True]
        assert len(bus.calls) == 1
