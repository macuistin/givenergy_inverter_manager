"""periods.py: a single named rate window."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time


@dataclass
class RatePeriod:
    """
    A single timed tariff rate period.

    Has explicit start and end times; is_active() returns True within that window.
    Handles overnight spans where end < start (e.g. Night 23:00–08:00).

    The base / daytime rate is NOT a RatePeriod — it is a separate scalar field
    on TariffConfig (base_rate / base_rate_name). This keeps RatePeriod simple
    and the config form clear: one field for the default rate, a list for overrides.
    """

    name: str
    rate: float  # €/kWh
    start: time
    end: time

    def is_active(self, dt: datetime) -> bool:
        """Return True if this period is active at the given datetime."""
        current = dt.time().replace(second=0, microsecond=0)
        if self.start <= self.end:
            # Normal period e.g. 08:00 – 23:00
            return self.start <= current < self.end
        # Overnight period e.g. 23:00 – 08:00
        return current >= self.start or current < self.end
