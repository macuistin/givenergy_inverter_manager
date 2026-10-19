"""A client for GivTCP: reads, verified writes and the write order, over Home Assistant entities.

This is the public surface. Everything else is reached through its module (`discovery`, `keys`,
`defaults`, `system`, `pause_modes` and so on) and may change between releases. `README.md` has
the guide.
"""

from ._entity import EntityState, GetState
from .adapter import GivTCPBackend, GivTCPPorts, make_backend
from .controls import GivTCPControls
from .discovery import GivTCPInverter, discover_givtcp_inverters
from .errors import ServiceCallError
from .force import GivTCPForce
from .model import BatteryMode, BatteryPause, Force, SelfUseMode, SlotKind, Window
from .reader import GivTCPReader
from .schedules import GivTCPSchedules
from .status import WriteStatus
from .system import SystemKind
from .values import (
    ChargePlan,
    FeedState,
    FeedStatus,
    InverterIdentity,
    InverterValues,
    RateDefaults,
    WriteResult,
)
from .writer import (
    ConfirmationListener,
    GivTCPWriter,
    VerifiedWrite,
    WriteObserver,
    WriteTuning,
)

__all__ = [
    "BatteryMode",
    "BatteryPause",
    "ChargePlan",
    "ConfirmationListener",
    "EntityState",
    "FeedState",
    "FeedStatus",
    "Force",
    "GetState",
    "GivTCPBackend",
    "GivTCPControls",
    "GivTCPForce",
    "GivTCPInverter",
    "GivTCPPorts",
    "GivTCPReader",
    "GivTCPSchedules",
    "GivTCPWriter",
    "InverterIdentity",
    "InverterValues",
    "RateDefaults",
    "SelfUseMode",
    "ServiceCallError",
    "SlotKind",
    "SystemKind",
    "VerifiedWrite",
    "Window",
    "WriteObserver",
    "WriteResult",
    "WriteStatus",
    "WriteTuning",
    "discover_givtcp_inverters",
    "make_backend",
]
