"""
inverter_values.py: what the coordinator and the inverter backend hand to each other.

Pure frozen values with no Home Assistant import. A backend reads an inverter into
InverterValues, takes a ChargePlan to write, and reports a FeedStatus and a WriteResult. The
integration's own sign convention applies to every value here: grid power is positive for
import, battery power is positive for charging. An adapter converts from whatever its
inverter integration publishes, so nothing outside the adapter negates a reading.

The field names of InverterValues match the fields of RawSensorValues that the coordinator
fills from the inverter today.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum

from .battery_pause import PauseWindow


@dataclass(frozen=True)
class InverterIdentity:
    """Which inverter a backend talks to."""

    serial: str
    prefix: str  # what the backend's entity names start with
    display_name: str


@dataclass(frozen=True)
class InverterValues:
    """One read of the inverter, in the integration's sign convention."""

    solar_power_w: float = 0.0
    battery_soc: float = 0.0
    battery_power_w: float = 0.0  # positive is charging
    grid_power_w: float = 0.0  # positive is import
    house_load_w: float = 0.0
    inverter_temp: float | None = None
    battery_lifetime_cycles: float | None = None
    # Today's energy counters. None when the inverter does not publish one, and the engine
    # then falls back to adding up power over time.
    solar_energy_today_kwh: float | None = None
    import_energy_today_kwh: float | None = None
    export_energy_today_kwh: float | None = None
    charge_energy_today_kwh: float | None = None
    discharge_energy_today_kwh: float | None = None
    load_energy_today_kwh: float | None = None
    ac_charge_energy_today_kwh: float | None = None  # the part of today's import that charged
    battery_charge_rate_w: float | None = None  # None unless above zero
    data_age_s: float | None = None  # None where the inverter integration does not say
    # The window in which the inverter does not let the battery discharge. None when there is no
    # such pause: none is set, it is off or only stops charging, or it cannot be read.
    battery_pause: PauseWindow | None = None
    unavailable_inputs: tuple[str, ...] = ()  # the required inputs that could not be read


@dataclass(frozen=True)
class ChargePlan:
    """What to write for one overnight charge: a target and the window it applies to."""

    target_soc: int  # percent
    window_start: time
    window_end: time
    enable_charge_target: bool  # off at 100%, so the battery does not bounce at the top

    @classmethod
    def for_target(cls, target_soc: int, window_start: time, window_end: time) -> ChargePlan:
        """A plan whose enable-charge-target switch follows the rule below.

        Without the switch on, the inverter silently ignores the target register, so it is on
        for any target below 100%. At 100% it is off, to avoid the charge-bounce bug where the
        battery oscillates between 99 and 100% when the limit switch is on at 100%.
        """
        return cls(target_soc, window_start, window_end, enable_charge_target=target_soc < 100)


@dataclass(frozen=True)
class RateDefaults:
    """The rates the inverter integration holds, offered on the setup page only."""

    day_rate: float | None = None
    night_rate: float | None = None
    export_rate: float | None = None


@dataclass(frozen=True)
class WriteResult:
    """The outcome of a write sequence: the steps that were not taken."""

    failed_steps: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failed_steps


class FeedState(StrEnum):
    """Whether the inverter integration is giving the manager live numbers."""

    PUBLISHING = "publishing"
    MISSING = "missing"  # the entities are not in the state machine at all
    SILENT = "silent"  # the entities are unavailable
    FROZEN = "frozen"  # the entities hold values but nothing has been reported lately
    PAUSED = "paused"  # the inverter integration has stopped talking to the inverter on purpose
    STALE = "stale"  # the entities are live but the data behind them is old


@dataclass(frozen=True)
class FeedStatus:
    """The feed state, and when anything was last reported where that is known."""

    state: FeedState
    last_report: datetime | None = None

    @property
    def is_publishing(self) -> bool:
        return self.state is FeedState.PUBLISHING
