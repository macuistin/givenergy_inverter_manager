"""slot_sampler.py: turn each update cycle's readings into the energy for the slot store.

Every figure is the best reading there is. A counter the inverter keeps (energy today) is
preferred: the rise since the last cycle is what the meter counted. Where the counter is
missing, was screened out as untrustworthy or has just reset at midnight, the power reading
for the cycle is integrated over the time that passed instead. The EV and the immersion
have no counter, so they always use power.

Nothing here is derived from another series. The house load is the inverter's own load
reading and includes the EV and the immersion, which are recorded on their own as well.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

from ..lib.tariff.slots import SlotEnergy
from ..lib.timeutil import elapsed_seconds

if TYPE_CHECKING:
    from .engine import RawSensorValues

_KW = 1000.0

# Name -> the inverter's energy-today counter on RawSensorValues.
_FLOW_COUNTERS = {
    "import": "import_energy_today_kwh",
    "export": "export_energy_today_kwh",
    "solar": "solar_energy_today_kwh",
    "battery_charge": "charge_energy_today_kwh",
    "battery_discharge": "discharge_energy_today_kwh",
    "grid_to_battery": "ac_charge_energy_today_kwh",
}
_LOAD_COUNTERS = {"house": "load_energy_today_kwh"}

# Name -> power in watts for the cycle, used when there is no usable counter rise. Grid to
# battery has no power reading, so without its counter nothing is recorded for it.
_FLOW_POWER: dict[str, Callable[[RawSensorValues], float]] = {
    "import": lambda raw: max(0.0, raw.grid_power_w),
    "export": lambda raw: max(0.0, -raw.grid_power_w),
    "solar": lambda raw: max(0.0, raw.solar_power_w),
    "battery_charge": lambda raw: max(0.0, raw.battery_power_w),
    "battery_discharge": lambda raw: max(0.0, -raw.battery_power_w),
    "grid_to_battery": lambda raw: 0.0,
}
_LOAD_POWER: dict[str, Callable[[RawSensorValues], float]] = {
    "house": lambda raw: max(0.0, raw.house_load_w),
    "ev": lambda raw: max(0.0, raw.ev_power_w),
    "immersion": lambda raw: raw.immersion_wattage_w if raw.immersion_on else 0.0,
}


@dataclass(frozen=True)
class SlotSample:
    """The energy used over one update cycle, from *start* to *end*."""

    energy: SlotEnergy
    start: datetime
    end: datetime


class SlotSampler:
    """Remembers the last counter readings and turns a cycle into slot energy.

    The engine calls sample each cycle and the coordinator reads `latest` afterwards, so the
    engine's output type does not change.
    """

    def __init__(self) -> None:
        self._last: dict[str, tuple[date, float]] = {}
        # The latest cycle's sample. None when it has no interval (the first cycle after a
        # start, or a clock that did not move forward).
        self.latest: SlotSample | None = None

    def sample(self, raw: RawSensorValues, start: datetime | None, end: datetime) -> None:
        """Work out the energy used between *start* and *end* and keep it in `latest`.

        *raw* has had untrustworthy counters left out (None). The counters are always noted, so
        the first cycle after a restart gives a later cycle its starting point.
        """
        rises = {**self._rises(raw, _FLOW_COUNTERS, end), **self._rises(raw, _LOAD_COUNTERS, end)}
        self.latest = None
        if start is None or (hours := elapsed_seconds(start, end) / 3600) <= 0:
            return
        energy = SlotEnergy(
            flows={n: _kwh(rises.get(n), _FLOW_POWER[n](raw), hours) for n in _FLOW_POWER},
            loads={n: _kwh(rises.get(n), _LOAD_POWER[n](raw), hours) for n in _LOAD_POWER},
        )
        self.latest = SlotSample(energy, start, end)

    def _rises(
        self, raw: RawSensorValues, counters: dict[str, str], end: datetime
    ) -> dict[str, float]:
        """Each counter's rise since the last cycle. A counter with no usable rise is left out."""
        rises: dict[str, float] = {}
        for name, attribute in counters.items():
            current = getattr(raw, attribute)
            if current is None:
                self._last.pop(name, None)  # no rise across a hole in the readings
                continue
            previous = self._last.get(name)
            if previous is not None and previous[0] == end.date() and current >= previous[1]:
                rises[name] = float(current) - previous[1]
            self._last[name] = (end.date(), float(current))
        return rises


def _kwh(rise: float | None, power_w: float, hours: float) -> float:
    """The counter's rise when there is one, else the power integrated over the cycle."""
    return rise if rise is not None else power_w / _KW * hours
