"""model.py: the names the client's calls take, in one module so interfaces can be typed on them."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from enum import StrEnum

Window = tuple[time, time]  # start, end


class BatteryPause(StrEnum):
    """What the pause stops. The values are GivTCP's own option names."""

    OFF = "Disabled"
    CHARGE = "PauseCharge"
    DISCHARGE = "PauseDischarge"
    BOTH = "PauseBoth"


@dataclass(frozen=True)
class PauseSetting:
    """The battery pause as the inverter holds it: what it stops and the window it repeats in.

    The window is None when the start or end cannot be read. A pause window repeats every day,
    so a caller that changes it for a while saves this first and writes it back.
    """

    pause: BatteryPause
    window: Window | None = None


class SelfUseMode(StrEnum):
    """The battery modes that never send power to the grid. The values are GivTCP's own."""

    ECO = "Eco"
    TIMED_DEMAND = "Timed Demand"
    ECO_PAUSED = "Eco (Paused)"


class BatteryMode(StrEnum):
    """Every battery mode, including the one that exports."""

    ECO = SelfUseMode.ECO.value
    TIMED_DEMAND = SelfUseMode.TIMED_DEMAND.value
    ECO_PAUSED = SelfUseMode.ECO_PAUSED.value
    TIMED_EXPORT = "Timed Export"


class SlotKind(StrEnum):
    """Which list of slots. The value is the entity name stem."""

    CHARGE = "charge"
    DISCHARGE = "discharge"


class Force(StrEnum):
    """What to force. The value is the entity name stem."""

    CHARGE = "force_charge"
    EXPORT = "force_export"
