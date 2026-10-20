"""accumulator.py: running energy and cost totals for a billing period."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CounterMemory:
    """The last reading of each inverter daily counter, and which ones to stop trusting.

    A daily counter drops to zero at midnight. The memory outlives the midnight reset so a
    stale reading just after it is not added a second time. lib/guards/counter.py judges each
    reading against this memory.

    Only the AC charge baseline is saved. The other readings, their times and the list of
    counters that jumped live in memory, so a restart starts them fresh.
    """

    ac_charge_kwh: float = 0.0
    readings: dict[str, tuple[float, datetime]] = field(
        default_factory=dict, compare=False, repr=False
    )
    distrusted: set[str] = field(default_factory=set, compare=False, repr=False)
    # The last reading of each counter that passed, to recognise a counter coming back.
    last_trusted: dict[str, tuple[float, datetime]] = field(
        default_factory=dict, compare=False, repr=False
    )
    # The AC charge rise the last screening allowed. It is the only rise that is booked.
    ac_charge_rise_kwh: float = field(default=0.0, compare=False, repr=False)


@dataclass
class EnergyAccumulator:
    """
    Tracks energy and cost accumulation over a billing period (resets at midnight).

    Fields are grouped by what they enable:
      Basic flows      — solar, import, export, house, zappi, immersion
      Rate breakdown   — import split by cheap (timed) vs peak (base) rate
      Cost attribution — cost per load type and per rate tier
      Savings          — value delivered by the integration
      Battery health   — throughput for cycle and depreciation tracking
    """

    # ── Basic energy flows ────────────────────────────────────────────────────
    import_kwh: float = 0.0
    export_kwh: float = 0.0
    solar_kwh: float = 0.0
    battery_discharge_kwh: float = 0.0
    battery_charge_kwh: float = 0.0
    zappi_kwh: float = 0.0
    immersion_kwh: float = 0.0
    house_kwh: float = 0.0
    # The part of import_kwh that went into the battery (the inverter's AC charge counter). It is
    # stored, not used, so it does not count as the grid supplying the house.
    grid_to_battery_kwh: float = 0.0
    # What the grid energy that went into the battery cost, and the kWh that cost covers. Both
    # are kept by the integration from the moment it prices the AC charge counter, so
    # grid_to_battery_priced_kwh can be less than grid_to_battery_kwh on the day it is
    # first installed. Today's accumulator only. See core/stored_energy.py.
    grid_to_battery_cost: float = 0.0
    grid_to_battery_priced_kwh: float = 0.0
    # The battery's state of charge at the start of the period, None until the first reading.
    # A bookmark, not an accumulated figure, so it is left out of equality: a period with
    # nothing else on it still counts as empty.
    soc_at_start_pct: float | None = field(default=None, compare=False)

    # ── Rate-tier import breakdown ────────────────────────────────────────────
    # "cheap" = any timed rate period active (Night, Nightboost, etc.)
    # "peak"  = base/day rate (no timed period active)
    import_kwh_cheap: float = 0.0  # kWh imported at timed cheap rate
    import_kwh_peak: float = 0.0  # kWh imported at base/peak rate
    import_cost_cheap: float = 0.0  # cost at cheap rate
    import_cost_peak: float = 0.0  # cost at peak rate

    # ── Cost attribution per rate period and load ─────────────────────────────
    import_cost_by_period: dict[str, float] = field(default_factory=dict)
    # kWh imported, and kWh the house used, in each rate period. They are what the bill audit
    # lists beside the cost, and are empty on a period that began before they were kept.
    import_kwh_by_period: dict[str, float] = field(default_factory=dict)
    house_kwh_by_period: dict[str, float] = field(default_factory=dict)
    export_earnings: float = 0.0
    zappi_cost: float = 0.0
    immersion_cost: float = 0.0  # import cost attributable to immersion heater
    house_cost: float = 0.0  # import cost attributable to rest-of-house load

    # ── Counterfactual ────────────────────────────────────────────────────────
    # What the house load would have cost bought from the grid at the rate in force
    # when it ran. The saving from solar and battery is this minus what was paid.
    grid_equivalent_load_cost: float = 0.0

    # ── Integration savings ───────────────────────────────────────────────────
    # immersion_solar_kwh: solar kWh diverted to immersion that would otherwise
    #   have been exported at the lower export rate.
    # immersion_savings:   (import_rate - export_rate) × immersion_solar_kwh
    immersion_solar_kwh: float = 0.0
    immersion_savings: float = 0.0

    # ── Battery throughput ────────────────────────────────────────────────────
    # Total kWh cycled through the battery (in + out). Divide by 2 × capacity
    # to get fractional cycles. Multiply by (replacement_cost / rated_cycles)
    # to estimate depreciation cost.
    battery_throughput_kwh: float = 0.0

    # ── Missed solar (self-consumption opportunity) ───────────────────────────
    # kWh exported while battery is full, solar generating, and no flex load
    # active — represents solar that could have been self-consumed.
    missed_solar_kwh: float = 0.0

    # ── Inverter derating ──────────────────────────────────────────────────────
    # Minutes the inverter spent above the derating temperature threshold today.
    inverter_derating_minutes: float = 0.0

    @property
    def total_import_cost(self) -> float:
        return sum(self.import_cost_by_period.values())

    @property
    def total_cost(self) -> float:
        """Total import cost today (standing charges tracked separately in accrued_bill)."""
        return self.total_import_cost

    @property
    def net_position(self) -> float:
        """Negative = net cost, positive = net earnings."""
        return self.export_earnings - self.total_cost

    @property
    def peak_import_fraction(self) -> float:
        """Fraction of import that occurred at peak (base) rate. 0–1."""
        total = self.import_kwh
        return (self.import_kwh_peak / total) if total > 0 else 0.0

    @property
    def cheap_import_fraction(self) -> float:
        """Fraction of import that occurred at cheap (timed) rate. 0–1."""
        total = self.import_kwh
        return (self.import_kwh_cheap / total) if total > 0 else 0.0

    @property
    def grid_to_house_kwh(self) -> float:
        """Import that went to the house, not into the battery. Never negative.

        Without a grid-to-battery reading the figure is the whole import.
        """
        return max(0.0, self.import_kwh - self.grid_to_battery_kwh)

    @property
    def supplied_without_grid_kwh(self) -> float:
        """The house load not drawn from the grid at the time: solar, and battery discharge."""
        return max(0.0, self.house_kwh - self.grid_to_house_kwh)

    @property
    def self_sufficiency_pct(self) -> float:
        """Percentage of the house's consumption that did not have to be drawn from the grid.

        house_kwh is the whole load, EV and immersion included, so they are not added again.
        Grid energy the battery stored (grid_to_battery_kwh) is not counted against it.
        Later discharge of that stored energy counts as supplied from storage. EV and
        immersion energy bought from the grid is in house_kwh, so it still counts as grid.
        With no grid-to-battery reading, all import counts, as it did before the reading
        existed.
        """
        if self.house_kwh <= 0:
            return 100.0
        return max(0.0, min(100.0, (1 - self.grid_to_house_kwh / self.house_kwh) * 100))

    @property
    def solar_share_pct(self) -> float:
        """Percentage of the house's consumption met by solar generated and kept on site.

        Solar kept on site is generation less export. It includes solar stored in the
        battery, which counts when it is generated, not when it is later discharged.
        It does not count battery discharge, so energy the battery took from the grid
        never raises the figure. It ignores grid import, so buying cheap energy does not
        lower it. Compare self_sufficiency_pct, which counts all the house did not draw from the
        grid.

        house_kwh is the whole load, EV and immersion included, so they are not added again.
        With no consumption the share is 0, not 100 as for self-sufficiency: no solar was
        used, and a day with nothing to power should not read as fully solar powered.
        """
        if self.house_kwh <= 0:
            return 0.0
        solar_kept_kwh = max(0.0, self.solar_kwh - self.export_kwh)
        return min(100.0, solar_kept_kwh / self.house_kwh * 100)

    @property
    def self_consumption_pct(self) -> float:
        """Percentage of solar generation consumed on-site."""
        if self.solar_kwh == 0:
            return 0.0
        return min(100.0, (1 - self.export_kwh / self.solar_kwh) * 100)
