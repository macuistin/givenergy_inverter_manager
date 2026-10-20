"""water.py: the water and the heater a heating plan reads."""

from __future__ import annotations

from dataclasses import dataclass

from .ready import hours_to_heat

MINUTES_PER_HOUR = 60.0
RUN_ROUND_MINUTES = 5


@dataclass(frozen=True)
class WaterReading:
    """The water and the heater the advice reads, in degrees and degrees an hour."""

    temp: float
    target: float
    rate_c_per_h: float
    min_temp: float
    restart_gap_c: float

    @property
    def at_target(self) -> bool:
        return self.temp >= self.target

    @property
    def hours_to_target(self) -> float:
        """Heating hours to the target, with the plan's margin. Zero when there is no heating."""
        return hours_to_heat(self.temp, self.target, self.rate_c_per_h)

    @property
    def restart_below(self) -> float:
        """The temperature the immersion has to cool below before it starts a run of its own."""
        return self.target - self.restart_gap_c

    @property
    def needs_heating(self) -> bool:
        """Whether a ready time needs heat: below the restart threshold, run of 5 minutes or more.

        Above the threshold, or for a run shorter than one rounding step, the water is as good
        as ready and a start would only be noise.
        """
        long_enough = self.hours_to_target * MINUTES_PER_HOUR >= RUN_ROUND_MINUTES
        return self.temp < self.restart_below and long_enough

    @property
    def keep_warm_below(self) -> float:
        """The temperature at or below which a keep-warm run is worth suggesting.

        The lower of the minimum plus the restart gap and the target less the restart gap, so
        the default settings (minimum 50, gap 5, target 55) give 50, not the target.
        """
        return min(self.min_temp + self.restart_gap_c, self.target - self.restart_gap_c)
