"""A fake GivTCP and recorded GivTCP system fixtures, for testing Home Assistant code.

The mock replaces the write services of the Home Assistant instance it is installed on. Never
point it at a real instance. ``givtcp_mock.systems`` loads the recorded and built system
snapshots. Nothing here imports ``homeassistant`` at run time.
"""

from .mock import (
    DEFAULT_SERIAL,
    EVC_PREFIX,
    UNUSED_SLOT,
    ZAPPI_PREFIX,
    MockGivTCP,
    Readings,
    describe,
)

__all__ = [
    "DEFAULT_SERIAL",
    "EVC_PREFIX",
    "UNUSED_SLOT",
    "ZAPPI_PREFIX",
    "MockGivTCP",
    "Readings",
    "describe",
]
