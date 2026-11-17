"""demand.py: the highest half-hour power in each demand window, read from the slot history.

A demand charge is priced on the peak kW, not on kWh. A slot's kW is its import kWh over the slot's
length, so the peak is a half-hour average. A tariff that measures a shorter interval cannot be
read from half-hourly slots, and its peak is understated. A slot belongs to a window by the clock
at its start, as for a band.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from decimal import Decimal

from ..timeutil import shift_real
from .bands import no_holidays, zone_applies
from .defaults import SLOT_SECONDS
from .definition import TariffDefinition
from .definition_parse import demand_windows
from .slots import SlotDay

_KW_PER_KWH_SLOT = Decimal(3600) / Decimal(SLOT_SECONDS)


def peak_kw_by_window(
    days: Sequence[SlotDay],
    definition: TariffDefinition,
    is_holiday: Callable[[date], bool] = no_holidays,
) -> dict[str, Decimal]:
    """The peak import kW in each demand window the definition uses, over *days*.

    A window with no import in it has a peak of 0, because the slots say the power was zero."""
    windows = demand_windows(definition.total)
    peaks = dict.fromkeys(windows, 0.0)
    for day in days:
        for index, kwh in enumerate(day.flows["import"]):
            if not kwh:
                continue
            local = shift_real(day.start, timedelta(seconds=index * SLOT_SECONDS))
            local = local.astimezone(definition.timezone)
            for name, zone in windows.items():
                if zone_applies(zone, local, is_holiday):
                    peaks[name] = max(peaks[name], kwh)
    return {name: Decimal(repr(round(kwh, 6))) * _KW_PER_KWH_SLOT for name, kwh in peaks.items()}
