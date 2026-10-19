"""
adapter.py: build the GivTCP backend for the coordinator.

The adapter itself lives in lib/givtcp and holds no Home Assistant objects. It reports a failed
service call by raising `ServiceCallError`, so this module wraps the coordinator's call-service
callable and turns a `HomeAssistantError` into that. Nothing else changes between the two.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from ...lib.givtcp.adapter import GivTCPBackend, GivTCPPorts, read_rate_defaults
from ...lib.givtcp.errors import ServiceCallError
from ...logging import get_logger

__all__ = ["GivTCPBackend", "GivTCPPorts", "make_backend", "read_rate_defaults"]

_LOG = get_logger(__name__)


def make_backend(cfg: Mapping[str, Any], ports: GivTCPPorts) -> GivTCPBackend:
    """The GivTCP backend for the inverter named in cfg, with failures mapped for the library."""
    call_service = ports.call_service

    async def call_and_map(domain: str, service: str, data: dict[str, Any]) -> None:
        try:
            await call_service(domain, service, data)
        except HomeAssistantError as err:
            raise ServiceCallError(str(err)) from err

    wrapped = dataclasses.replace(
        ports, call_service=call_and_map, verbose=ports.verbose or _LOG.is_verbose
    )
    return GivTCPBackend(cfg, wrapped)
