"""make_backend turns the coordinator's Home Assistant failures into the library's own error."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.givenergy_inverter_manager import conf
from custom_components.givenergy_inverter_manager.inverter.givtcp import GivTCPPorts, make_backend
from custom_components.givenergy_inverter_manager.lib.givtcp.adapter import GivTCPBackend

ENTITY = "number.givtcp_SA1_target_soc"
CFG = {conf.CONF_INVERTER_SERIAL: "SA1", conf.CONF_TARGET_SOC_ENTITY: ENTITY}


class _Bus:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.states = {ENTITY: SimpleNamespace(state="50")}

    def get_state(self, entity_id: str):
        return self.states.get(entity_id)

    async def call_service(self, domain: str, service: str, data: dict) -> None:
        if self.error is not None:
            raise self.error
        self.states[data["entity_id"]] = SimpleNamespace(state=str(data["value"]))


@pytest.fixture(autouse=True)
def _no_read_back_wait(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)


def _backend(bus: _Bus, verbose: bool = False):
    ports = GivTCPPorts(
        get_state=bus.get_state,
        call_service=bus.call_service,
        on_count_change=lambda count: None,
        verbose=lambda: verbose,
    )
    return make_backend(CFG, ports)


async def test_a_home_assistant_error_is_a_failed_write_that_is_logged_as_a_warning(caplog):
    backend = _backend(_Bus(HomeAssistantError("write rejected")))

    with caplog.at_level(logging.DEBUG):
        taken = await backend.writer.set_number(ENTITY, 80, "charge target")

    assert taken is False
    failures = [r for r in caplog.records if "failed: write rejected" in r.getMessage()]
    assert [r.levelno for r in failures] == [logging.WARNING]
    assert not any(r.exc_info for r in caplog.records)


async def test_the_library_backend_alone_does_not_know_that_error(caplog):
    bus = _Bus(HomeAssistantError("write rejected"))
    ports = GivTCPPorts(bus.get_state, bus.call_service, lambda count: None)
    backend = GivTCPBackend(CFG, ports)

    with caplog.at_level(logging.DEBUG):
        taken = await backend.writer.set_number(ENTITY, 80, "charge target")

    assert taken is False
    assert any(r.exc_info for r in caplog.records)  # logged as unexpected, not as a refused call


@pytest.mark.parametrize(("verbose", "expected"), [(False, 0), (True, 1)])
async def test_the_read_back_line_follows_the_hosts_verbose_flag(caplog, verbose, expected):
    backend = _backend(_Bus(), verbose=verbose)

    with caplog.at_level(logging.DEBUG):
        await backend.writer.set_number(ENTITY, 80, "charge target")

    lines = [r for r in caplog.records if "GIVTCP WRITE" in r.getMessage()]
    assert len(lines) == expected
