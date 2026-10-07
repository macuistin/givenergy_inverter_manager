"""
engine.py — Pure Python energy management engine for GivEnergy Inverter Manager.

This module contains all the decision-making and accumulation logic that runs
each coordinator update cycle. It takes plain Python inputs (floats, dicts,
datetimes) and returns a populated CoordinatorData snapshot.

Nothing in this module imports from homeassistant. That means every function
here is fully unit-testable without a running HA instance.

The coordinator (coordinator.py) is the only caller. It:
  1. Reads raw values from HA entity states (HA-dependent, not tested here)
  2. Calls build_coordinator_data() with those raw values
  3. Applies any HA-side effects (service calls, time listeners) based on the result

Separation of concerns:
  coordinator.py  HA wiring and side effects. Reads hass.states, calls the engine,
                  calls hass.services, owns timers, persistence and write safety.
  engine.py       Pure logic. Accumulation, decisions, predictions and derived values.
  rules.py        Decision functions: charge target, immersion divert, EV charger mode.
  tariff.py       Rate periods and energy accumulators.
  battery.py      Cycle tracking and night survival.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..const import (
    BATTERY_FULL_SOC_PCT,
    BATTERY_MAX_SOC_STEP_PCT,
    BATTERY_RATED_CYCLES,
    CARBON_HIGH_THRESHOLD,
    CARBON_LOW_THRESHOLD,
    CARBON_STATUS_HIGH,
    CARBON_STATUS_LOW,
    CARBON_STATUS_MEDIUM,
    CARBON_STATUS_UNKNOWN,
    CLIPPING_THRESHOLD_PERCENT,
    CONF_BATTERY_COST,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_THROUGHPUT_BUDGET,
    CONF_CAR_EFFICIENCY_KWH_PER_100KM,
    CONF_CURRENCY,
    CONF_DRY_RUN,
    CONF_FORECAST_CONSERVATISM,
    CONF_OVERNIGHT_CHARGE_TARGET,
    CONF_SKIP_CHARGE_SOC_THRESHOLD,
    CONF_SURPLUS_DIVERT_MIN_W,
    CONF_SURPLUS_DIVERT_SOC,
    CURRENCIES,
    DEFAULT_BATTERY_COST,
    DEFAULT_BATTERY_MIN_SOC,
    DEFAULT_BATTERY_THROUGHPUT_BUDGET,
    DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM,
    DEFAULT_CURRENCY,
    DEFAULT_CURRENCY_SYMBOL,
    DEFAULT_DRY_RUN,
    DEFAULT_FORECAST_CONSERVATISM,
    DEFAULT_INVERTER_MAX_OUTPUT,
    DEFAULT_OVERNIGHT_CHARGE_TARGET,
    DEFAULT_SKIP_CHARGE_SOC_THRESHOLD,
    EV_CHARGER_MIN_POWER_W,
    INVERTER_TEMP_CRITICAL,
    INVERTER_TEMP_DERATING,
    INVERTER_TEMP_STATUS_CRITICAL,
    INVERTER_TEMP_STATUS_DERATING,
    INVERTER_TEMP_STATUS_NORMAL,
    INVERTER_TEMP_STATUS_UNKNOWN,
    INVERTER_TEMP_STATUS_WARM,
    INVERTER_TEMP_WARM,
    SOLAR_NOISE_FLOOR_W,
    SOLAR_SUNRISE_HOUR,
    SURPLUS_DIVERT_MIN_POWER_W,
    SURPLUS_DIVERT_SOC_THRESHOLD,
    THROUGHPUT_BUDGET_HIGH_PCT,
    THROUGHPUT_BUDGET_STATUS_HIGH,
    THROUGHPUT_BUDGET_STATUS_OK,
    THROUGHPUT_BUDGET_STATUS_OVER,
)
from ..discovery import EVCharger, EVChargerState
from ..logging import get_logger
from .battery import (
    BatteryStats,
    NightEstimateInputs,
    calculate_cycle_increment,
    estimate_will_survive_night,
    hours_until_solar,
)
from .charge_hold import HeldCharge, next_held_recommendation
from .charge_window import ChargeNeed, ChargeWindow, plan_charge_window
from .rules import (
    ChargeDecision,
    ChargeInputs,
    DivertPolicy,
    ImmersionInputs,
    ImmersionRun,
    PowerReadings,
    SolarForecast,
    SurplusInputs,
    WaterState,
    available_surplus_w,
    calculate_overnight_charge_target,
    decide_ev_charger_action,
    should_divert_to_immersion,
)
from .tariff import EnergyAccumulator, RatePeriod, TariffConfig, build_tariff
from .timeutil import elapsed_seconds, local_time_on

_LOG = get_logger(__name__)


@dataclass
class RawSensorValues:
    """
    Plain-Python container for all values read from HA entity states.

    Populated by the coordinator (HA layer) and passed into the engine.
    All values are primitives — no HA objects.
    """

    solar_power_w: float = 0.0
    # EMA-smoothed solar (α=0.5) — used for divert decisions to prevent chasing
    # cloud transients. The coordinator sets this from the rolling EMA it maintains.
    # Defaults to -1.0 as a sentinel; __post_init__ copies solar_power_w if unset,
    # so tests that only set solar_power_w get correct behaviour without changes.
    smoothed_solar_power_w: float = -1.0
    battery_soc: float = 0.0
    battery_power_w: float = 0.0  # positive=charging, negative=discharging
    grid_power_w: float = 0.0  # positive=import, negative=export
    house_load_w: float = 0.0
    inverter_max_w: float = DEFAULT_INVERTER_MAX_OUTPUT * 1000
    battery_capacity_kwh: float = 10.0
    immersion_on: bool = False
    # False when the install has no immersion switch. The coordinator sets it from the
    # configuration. The default describes a fully equipped site, like the other immersion
    # defaults here.
    immersion_switch_configured: bool = True
    immersion_wattage_w: float = 3000.0
    immersion_temp: float | None = None
    immersion_target_temp: float = 55.0
    immersion_min_temp: float = 50.0
    immersion_hysteresis_c: float = 5.0
    forecast_kwh_tomorrow: float | None = None
    forecast_kwh_p10: float | None = None
    forecast_kwh_d2: float | None = None
    carbon_intensity_gco2: float | None = None
    ev_power_w: float = 0.0
    ev_plugged_in: bool = False
    # True once an EV charger has been discovered. The coordinator sets it.
    ev_charger_present: bool = False
    inverter_temp: float | None = None
    # Names of required inputs that were unavailable this cycle (their value is a 0.0 placeholder)
    unavailable_inputs: tuple[str, ...] = ()
    # Seconds the current unavailable_inputs outage has lasted (0.0 when none)
    unavailable_for_s: float = 0.0
    # GivTCP daily energy counters — authoritative when present, None → fall back to integration
    solar_energy_today_kwh: float | None = None
    import_energy_today_kwh: float | None = None
    export_energy_today_kwh: float | None = None
    charge_energy_today_kwh: float | None = None
    discharge_energy_today_kwh: float | None = None
    load_energy_today_kwh: float | None = None
    # Lifetime cycle count reported by the battery BMS (highest single pack), None if unknown
    battery_lifetime_cycles: float | None = None
    # The GivTCP battery charge rate setting in W, None when the entity is not readable
    battery_charge_rate_w: float | None = None

    def __post_init__(self) -> None:
        if self.smoothed_solar_power_w < 0.0:
            self.smoothed_solar_power_w = self.solar_power_w



@dataclass(slots=True, eq=False, repr=False)
class CoordinatorData:
    """
    Mutable snapshot of one update cycle, built by the engine.

    The engine fills it in place during a cycle. After the cycle, sensor entities
    read from it via value_fn lambdas. Using slots prevents accidental attribute
    creation. Each field is declared once, here, with its default. Identity
    equality is kept on purpose: a snapshot is a unique object per cycle.
    """

    solar_power_w: float = 0.0
    battery_soc: float = 0.0
    battery_power_w: float = 0.0
    grid_power_w: float = 0.0
    house_load_w: float = 0.0
    inverter_max_w: float = DEFAULT_INVERTER_MAX_OUTPUT * 1000
    battery_capacity_kwh: float = 0.0
    immersion_temp: float | None = None
    forecast_kwh_tomorrow: float | None = None
    trailing_12m_solar_kwh: float = 0.0
    trailing_12m_import_kwh: float = 0.0
    trailing_12m_export_kwh: float = 0.0
    trailing_12m_import_cost: float = 0.0
    trailing_12m_export_earnings: float = 0.0
    immersion_load_w: float = 0.0
    rest_of_house_w: float = 0.0
    current_rate_name: str = ""
    current_rate: float = 0.0
    live_grid_cost_rate: float = 0.0  # €/hr, positive=spending, negative=earning
    currency_symbol: str = DEFAULT_CURRENCY_SYMBOL
    is_clipping: bool = False
    charge_decision: ChargeDecision | None = None
    charge_window: ChargeWindow | None = None
    # The held copy of charge_decision the sensors publish. The write uses charge_decision.
    published_charge_decision: ChargeDecision | None = None
    should_divert_immersion: bool = False
    divert_reason: str = ""
    today: EnergyAccumulator = field(default_factory=EnergyAccumulator)
    week: EnergyAccumulator = field(default_factory=EnergyAccumulator)
    month: EnergyAccumulator = field(default_factory=EnergyAccumulator)
    year: EnergyAccumulator = field(default_factory=EnergyAccumulator)
    yesterday: EnergyAccumulator = field(default_factory=EnergyAccumulator)
    battery_stats: BatteryStats = field(default_factory=BatteryStats)
    accrued_bill: float = 0.0
    projected_bill: float = 0.0
    days_in_period: int = 0
    days_remaining: int = 0
    will_survive_night: bool = True
    battery_cycle_cost_per_kwh: float = 0.0
    battery_throughput_budget_pct: float | None = None
    battery_min_soc: int = 0
    net_solar_surplus_w: float = 0.0
    battery_years_remaining: float | None = None
    hours_to_cheap_rate: float | None = None
    next_cheap_rate_start: str | None = None
    battery_throughput_budget_status: str = ""
    saving_vs_grid_today: float = 0.0
    net_saving_today: float = 0.0
    ev_km_charged_today: float | None = None
    ev_cost_per_km_today: float | None = None
    cheapest_rate: float = 0.0
    cheapest_rate_name: str = ""
    is_on_cheapest_rate: bool = False
    is_on_base_rate: bool = False
    minutes_remaining_in_period: float | None = None
    rate_savings_vs_daytime: float = 0.0
    estimated_soc_at_sunrise: float = 0.0
    survival_reason: str = ""
    ev_charger_brand: str = ""
    ev_charger_name: str = ""
    ev_charger_state: EVChargerState = EVChargerState.UNKNOWN
    ev_power_w: float = 0.0
    ev_session_kwh: float = 0.0
    ev_draining_battery: bool = False
    ev_mode_change_requested: bool = False
    ev_protection_reason: str = ""
    ev_available: bool = False
    # False when the install has no immersion switch, so reports leave out its saving.
    immersion_configured: bool = True
    ev_charging_source: str = "Not charging"
    ev_solar_surplus_available: bool = False
    dry_run: bool = False
    cheap_rate_floor_status: str = ""
    dry_run_last_skipped: str = ""
    inverter_temperature: float | None = None
    inverter_temperature_status: str = "Unknown"
    last_reset_time: str = ""
    week_start_time: str = ""
    month_start_time: str = ""
    year_start_time: str = ""
    solar_forecast_kwh_today: float = 0.0
    # The provider's own forecast for today, as it stood before midnight. None when none was seen.
    solar_forecast_raw_kwh_today: float | None = None
    yesterday_forecast_accuracy_pct: float = 0.0
    forecast_accuracy_7day_avg_pct: float = 0.0
    register_write_count: int = 0
    register_write_log: list[dict] = field(default_factory=list)  # oldest first
    carbon_intensity_gco2: float | None = None
    carbon_intensity_status: str = "Unknown"


@dataclass(frozen=True)
class AccumulationWindow:
    """The tariff in force and the time span one accumulation step covers."""

    tariff: TariffConfig
    period_name: str
    now: datetime
    last_update_time: datetime | None


@dataclass(frozen=True)
class _Step:
    """One integration step: the readings, the tariff context and the loads already derived."""

    raw: RawSensorValues
    tariff: TariffConfig
    period_name: str
    now: datetime
    immersion_w: float
    elapsed_h: float


def _apportion_import_cost(
    acc: EnergyAccumulator,
    period_cost: float,
    raw: RawSensorValues,
    immersion_w: float,
) -> None:
    """Apportion import cost across loads by their fraction of total load."""
    total_load_w = max(1.0, raw.house_load_w)
    ev_raw = raw.ev_power_w / total_load_w
    imm_raw = immersion_w / total_load_w
    total_frac = ev_raw + imm_raw
    ev_frac = ev_raw
    immersion_frac = imm_raw
    if total_frac > 1.0:
        norm = 1.0 / total_frac
        ev_frac *= norm
        immersion_frac *= norm
    rest_frac = max(0.0, 1.0 - ev_frac - immersion_frac)

    acc.zappi_cost += period_cost * ev_frac
    acc.immersion_cost += period_cost * immersion_frac
    acc.house_cost += period_cost * rest_frac


def _accumulate_import(acc: EnergyAccumulator, step: _Step) -> None:
    """Handle import accumulation and cost apportionment."""
    kwh = (step.raw.grid_power_w / 1000) * step.elapsed_h
    period_cost = step.tariff.calculate_import_cost(kwh, step.now)
    acc.import_kwh += kwh
    acc.import_cost_by_period[step.period_name] = (
        acc.import_cost_by_period.get(step.period_name, 0.0) + period_cost
    )
    if step.period_name != step.tariff.base_rate_name:
        acc.import_kwh_cheap += kwh
        acc.import_cost_cheap += period_cost
    else:
        acc.import_kwh_peak += kwh
        acc.import_cost_peak += period_cost
    _apportion_import_cost(acc, period_cost, step.raw, step.immersion_w)


def _accumulate_immersion_savings(acc: EnergyAccumulator, step: _Step) -> None:
    """Handle immersion savings when there is solar surplus."""
    if step.immersion_w <= 0:
        return
    raw = step.raw
    solar_surplus_w = max(
        0.0,
        available_surplus_w(
            SurplusInputs(
                raw.solar_power_w, raw.house_load_w, raw.battery_power_w, True, step.immersion_w
            )
        ),
    )
    solar_to_immersion_w = min(step.immersion_w, solar_surplus_w)
    if solar_to_immersion_w > 0:
        solar_diverted_kwh = (solar_to_immersion_w / 1000) * step.elapsed_h
        import_rate = step.tariff.get_current_rate(step.now).rate
        saving_per_kwh = max(0.0, import_rate - step.tariff.export_rate)
        acc.immersion_solar_kwh += solar_diverted_kwh
        acc.immersion_savings += solar_diverted_kwh * saving_per_kwh


def _accumulate_loads(acc: EnergyAccumulator, step: _Step) -> None:
    """Integrate solar generation and the three loads over the step."""
    raw = step.raw
    # Ignore sensor noise — GivTCP may return a small positive value at night.
    # 10W threshold filters this without affecting any real generation reading.
    solar_w = raw.solar_power_w if raw.solar_power_w >= SOLAR_NOISE_FLOOR_W else 0.0
    acc.solar_kwh += (solar_w / 1000) * step.elapsed_h
    acc.zappi_kwh += (raw.ev_power_w / 1000) * step.elapsed_h
    acc.immersion_kwh += (step.immersion_w / 1000) * step.elapsed_h
    house_step_kwh = (raw.house_load_w / 1000) * step.elapsed_h
    acc.house_kwh += house_step_kwh
    acc.grid_equivalent_load_cost += step.tariff.calculate_import_cost(house_step_kwh, step.now)


def _accumulate_battery_flow(acc: EnergyAccumulator, step: _Step) -> None:
    """Battery discharge/charge tracking, for the self-sufficiency calculation."""
    power_w = step.raw.battery_power_w
    if power_w == 0:
        return
    battery_kwh_this_step = abs(power_w / 1000) * step.elapsed_h
    acc.battery_throughput_kwh += battery_kwh_this_step
    if power_w < 0:
        acc.battery_discharge_kwh += battery_kwh_this_step
    else:
        acc.battery_charge_kwh += battery_kwh_this_step


def _accumulate_grid(acc: EnergyAccumulator, step: _Step) -> None:
    grid_w = step.raw.grid_power_w
    if grid_w > 0:
        _accumulate_import(acc, step)
    elif grid_w < 0:
        kwh = abs(grid_w / 1000) * step.elapsed_h
        acc.export_kwh += kwh
        acc.export_earnings += step.tariff.calculate_export_earnings(kwh)


def _accumulate_missed_solar(acc: EnergyAccumulator, step: _Step) -> None:
    """Missed solar: kWh exported while the battery is full and no flex load is active.

    Represents solar that could have been self-consumed (EV charging or a larger
    immersion divert window would have captured this). With neither an immersion switch
    nor an EV charger there is nothing to have captured it, so nothing is counted.
    """
    raw = step.raw
    if not (raw.immersion_switch_configured or raw.ev_charger_present):
        return
    battery_full = raw.battery_soc >= BATTERY_FULL_SOC_PCT
    exporting = raw.grid_power_w < 0
    no_flex_load = step.immersion_w <= 0 and raw.ev_power_w <= 0
    if battery_full and exporting and no_flex_load:
        acc.missed_solar_kwh += abs(raw.grid_power_w / 1000) * step.elapsed_h


def _accumulate_inverter_derating(acc: EnergyAccumulator, step: _Step) -> None:
    inverter_temp = step.raw.inverter_temp
    if inverter_temp is not None and inverter_temp >= INVERTER_TEMP_DERATING:
        acc.inverter_derating_minutes += step.elapsed_h * 60


def _usable_elapsed_hours(window: AccumulationWindow) -> float:
    """Hours since the last update, or 0.0 when this step must not accumulate.

    No accumulation on the first update, on clock skew (zero or negative elapsed time)
    or after a gap over an hour, which implies a restart; a huge energy spike would
    otherwise be added.
    """
    if window.last_update_time is None:
        return 0.0
    elapsed_h = elapsed_seconds(window.last_update_time, window.now) / 3600
    if elapsed_h > 1.0:
        _LOG.debug(
            "Skipping accumulation: %.1fh gap since last update (probable restart or HA downtime)",
            elapsed_h,
        )
        return 0.0
    return max(0.0, elapsed_h)


def accumulate_energy(
    acc: EnergyAccumulator, raw: RawSensorValues, window: AccumulationWindow
) -> None:
    """
    Update energy accumulator in-place for one update interval.

    Only runs if window.last_update_time is set (i.e. not the first update).
    Uses elapsed wall-clock time between updates rather than assuming a
    fixed interval, so it stays accurate if the coordinator is delayed.

    Modifies acc in place; returns None.
    """
    elapsed_h = _usable_elapsed_hours(window)
    if elapsed_h <= 0:
        return
    step = _Step(
        raw=raw,
        tariff=window.tariff,
        period_name=window.period_name,
        now=window.now,
        immersion_w=raw.immersion_wattage_w if raw.immersion_on else 0.0,
        elapsed_h=elapsed_h,
    )
    _accumulate_loads(acc, step)
    _accumulate_battery_flow(acc, step)
    _accumulate_grid(acc, step)
    _accumulate_immersion_savings(acc, step)
    _accumulate_missed_solar(acc, step)
    _accumulate_inverter_derating(acc, step)


@dataclass(frozen=True)
class DailyEstimateLimits:
    """When to trust the extrapolated daily total, and the values to fall back to."""

    fallback_kwh: float = 15.0
    min_minutes: int = 30
    absolute_min: float = 5.0


_DEFAULT_ESTIMATE_LIMITS = DailyEstimateLimits()


def estimate_avg_daily_kwh(
    house_kwh_today: float,
    now: datetime,
    limits: DailyEstimateLimits = _DEFAULT_ESTIMATE_LIMITS,
) -> float:
    """
    Estimate average daily household consumption from today's partial data.

    Uses elapsed time since midnight rather than elapsed time since HA restart,
    so the estimate is stable even if HA restarts mid-day.

    Returns limits.fallback_kwh if fewer than limits.min_minutes have elapsed (too
    early to extrapolate reliably). Always returns at least limits.absolute_min kWh.
    """
    minutes_since_midnight = now.hour * 60 + now.minute
    if minutes_since_midnight < limits.min_minutes:
        return max(limits.absolute_min, limits.fallback_kwh)
    estimated = house_kwh_today * (1440 / minutes_since_midnight)
    return max(limits.absolute_min, estimated)


@dataclass(frozen=True)
class BatteryReading:
    """This cycle's SoC, the previous cycle's, and the BMS lifetime cycle count if reported."""

    current_soc: float | None
    last_soc: float | None
    lifetime_cycles: float | None = None


def _soc_step(reading: BatteryReading) -> tuple[float, float] | None:
    """(previous, new) SoC when both readings exist and differ, else None."""
    current_soc, last_soc = reading.current_soc, reading.last_soc
    if current_soc is not None and last_soc is not None and current_soc != last_soc:
        return (last_soc, current_soc)
    return None


def update_battery_stats(stats: BatteryStats, reading: BatteryReading, today: date) -> None:
    """
    Update battery stats in place for the current SoC reading.

    The lifetime cycle count comes from the battery's own BMS counter when it is
    available (lifetime_cycles above zero) and is otherwise estimated from SoC.
    The estimate counts equivalent full cycles (discharge only). A missing
    reading, a reading of 0.0 after a healthy one, or a step above
    BATTERY_MAX_SOC_STEP_PCT is a sensor glitch and adds nothing.
    Also records the date of the last full charge. today is the local date.
    """
    step = _soc_step(reading)
    if step is not None and step[1] >= BATTERY_FULL_SOC_PCT:
        stats.last_full_charge_date = today
    if reading.lifetime_cycles is not None and reading.lifetime_cycles > 0:
        _adopt_lifetime_cycles(stats, reading.lifetime_cycles, today)
        return
    stats.lifetime_from_bms = False
    if step is not None:
        _count_estimated_cycles(stats, step, today)


def _count_estimated_cycles(stats: BatteryStats, step: tuple[float, float], today: date) -> None:
    previous_soc, new_soc = step
    if previous_soc <= 0.0 or new_soc <= 0.0:
        return
    if abs(new_soc - previous_soc) > BATTERY_MAX_SOC_STEP_PCT:
        return
    if stats.tracking_start_date is None:
        stats.tracking_start_date = today
        stats.tracking_start_cycles = stats.total_cycles
    stats.total_cycles += calculate_cycle_increment(new_soc - previous_soc)


def _adopt_lifetime_cycles(stats: BatteryStats, lifetime_cycles: float, today: date) -> None:
    """Make the BMS cycle counter the lifetime total without distorting the daily rate."""
    if not stats.lifetime_from_bms and stats.tracking_start_date is not None:
        stats.tracking_start_cycles += lifetime_cycles - stats.total_cycles
    stats.total_cycles = lifetime_cycles
    stats.lifetime_from_bms = True
    if stats.tracking_start_date is None:
        stats.tracking_start_date = today
        stats.tracking_start_cycles = lifetime_cycles


def _ev_charging_source(ev_w: float, grid_w: float, batt_w: float) -> str:
    """Where the EV's energy comes from. Positive grid_w is import, positive batt_w is charging."""
    if ev_w <= 0:
        return "Not charging"
    if grid_w <= 0 and batt_w >= 0:
        return "Solar"
    if grid_w <= 0 and batt_w < 0:
        return "Battery"
    if grid_w > 0 and batt_w >= 0:
        return "Grid"
    return "Mixed"


def _process_ev_charger(
    data: CoordinatorData,
    ev_charger: EVCharger,
    raw: RawSensorValues,
) -> str | None:
    """Process EV charger state and return target mode."""
    data.ev_available = True
    data.ev_charger_brand = ev_charger.brand.value
    data.ev_charger_name = ev_charger.display_name
    data.ev_charger_state = ev_charger.state
    data.ev_power_w = ev_charger.power_w
    data.ev_session_kwh = ev_charger.session_kwh
    data.ev_draining_battery = ev_charger.is_draining_battery

    solar_surplus_w = data.net_solar_surplus_w

    ev_target_mode, reason = decide_ev_charger_action(
        charger=ev_charger,
        battery_soc=raw.battery_soc,
        solar_surplus_w=solar_surplus_w,
    )
    data.ev_protection_reason = reason
    data.ev_mode_change_requested = ev_target_mode is not None

    data.ev_charging_source = _ev_charging_source(
        ev_charger.power_w, raw.grid_power_w, raw.battery_power_w
    )

    data.ev_solar_surplus_available = solar_surplus_w >= EV_CHARGER_MIN_POWER_W

    return ev_target_mode



@dataclass(frozen=True)
class Accumulators:
    """The running energy accumulators, plus when today's was last reset.

    today is mutated in place every cycle. The others are None until the coordinator
    has restored them.
    """

    today: EnergyAccumulator
    week: EnergyAccumulator | None = None
    month: EnergyAccumulator | None = None
    year: EnergyAccumulator | None = None
    yesterday: EnergyAccumulator | None = None
    last_reset_time: str = ""

    def rolling(self) -> tuple[EnergyAccumulator, ...]:
        """The accumulators that integrate live power, today's first. Yesterday is a record."""
        candidates = (self.today, self.week, self.month, self.year)
        return tuple(acc for acc in candidates if acc is not None)


@dataclass(frozen=True)
class ManualOverrides:
    """Manual choices that replace the automatic charge and divert decisions."""

    charge_target: int | None = None
    immersion: bool | None = None
    skip_charge: bool = False


@dataclass(frozen=True)
class ForecastContext:
    """What the charge decision and the forecast sensors know about solar forecasts."""

    solar_fractions: dict[int, float] | None = None
    solar_forecast_kwh_today: float = 0.0
    yesterday_forecast_accuracy_pct: float = 0.0
    forecast_accuracy_7day_avg_pct: float = 0.0
    load_profile: list[float] | None = None
    forecast_correction: float | None = None
    # Today's P50 and P10 forecasts as the sensors read before midnight. After midnight the
    # sensors report the next day, so the charge decision reads these for the day it serves.
    today_raw_forecast_kwh: float | None = None
    today_raw_forecast_p10_kwh: float | None = None


@dataclass(frozen=True)
class PreviousCycle:
    """State carried over from the previous update. battery_stats and held_charge are mutated."""

    battery_stats: BatteryStats
    last_soc: float | None
    last_update_time: datetime | None
    held_charge: HeldCharge = field(default_factory=HeldCharge)


@dataclass(frozen=True)
class CycleInputs:
    """This cycle's readings and settings. now defaults to the current UTC time."""

    raw: RawSensorValues
    cfg: dict[str, Any]
    now: datetime | None = None
    ev_charger: EVCharger | None = None
    overrides: ManualOverrides = field(default_factory=ManualOverrides)


@dataclass(frozen=True)
class _Cycle:
    """Values every step of one cycle reads, resolved once up front."""

    raw: RawSensorValues
    cfg: dict[str, Any]
    now: datetime
    tariff: TariffConfig
    current_period: RatePeriod
    overrides: ManualOverrides
    forecast: ForecastContext


def _apply_history(
    data: CoordinatorData, accumulators: Accumulators, forecast: ForecastContext
) -> None:
    """Copy the restored accumulators and the forecast accuracy figures onto the snapshot."""
    data.last_reset_time = accumulators.last_reset_time
    data.solar_forecast_kwh_today = forecast.solar_forecast_kwh_today
    data.solar_forecast_raw_kwh_today = forecast.today_raw_forecast_kwh
    data.yesterday_forecast_accuracy_pct = forecast.yesterday_forecast_accuracy_pct
    data.forecast_accuracy_7day_avg_pct = forecast.forecast_accuracy_7day_avg_pct
    if accumulators.week is not None:
        data.week = accumulators.week
    if accumulators.month is not None:
        data.month = accumulators.month
    if accumulators.year is not None:
        data.year = accumulators.year
    if accumulators.yesterday is not None:
        data.yesterday = accumulators.yesterday


def _apply_config(data: CoordinatorData, cfg: dict[str, Any]) -> None:
    data.dry_run = bool(cfg.get(CONF_DRY_RUN, DEFAULT_DRY_RUN))
    currency_code = cfg.get(CONF_CURRENCY, DEFAULT_CURRENCY)
    data.currency_symbol = CURRENCIES.get(currency_code, DEFAULT_CURRENCY_SYMBOL)


def _apply_live_readings(data: CoordinatorData, raw: RawSensorValues) -> None:
    data.solar_power_w = raw.solar_power_w
    data.battery_soc = raw.battery_soc
    data.battery_power_w = raw.battery_power_w
    data.grid_power_w = raw.grid_power_w
    data.house_load_w = raw.house_load_w
    data.inverter_max_w = raw.inverter_max_w
    data.battery_capacity_kwh = raw.battery_capacity_kwh
    data.immersion_temp = raw.immersion_temp
    data.immersion_configured = raw.immersion_switch_configured
    data.forecast_kwh_tomorrow = raw.forecast_kwh_tomorrow


def _apply_derived_power(data: CoordinatorData, raw: RawSensorValues) -> None:
    """Set the power figures derived from the live readings.

    Which loads each power figure includes:

    house_load_w: the GivTCP load sensor as read. It is the inverter-side load and
        includes the immersion while it is on. Loads wired outside the inverter are
        not in it. The cost split, rest_of_house_w and the per-slot baseline all assume
        the EV charger's draw is inside it too.
    immersion_load_w: the configured element wattage while the switch is on, else 0.
        It is the nameplate figure, not a measurement.
    rest_of_house_w: house_load_w minus ev_power_w minus immersion_load_w, floored at 0.
    net_solar_surplus_w: smoothed solar minus house_load_w with the immersion's own
        draw added back, floored at 0. Battery charging is not subtracted (the immersion
        rule does subtract it) and the EV draw is not added back.
    """
    data.immersion_load_w = raw.immersion_wattage_w if raw.immersion_on else 0.0
    data.net_solar_surplus_w = _net_solar_surplus_w(raw)
    data.rest_of_house_w = max(
        0.0,
        raw.house_load_w - raw.ev_power_w - data.immersion_load_w,
    )
    data.is_clipping = raw.solar_power_w >= (raw.inverter_max_w * CLIPPING_THRESHOLD_PERCENT / 100)


def _net_solar_surplus_w(raw: RawSensorValues) -> float:
    if {"solar_power", "house_load"} & set(raw.unavailable_inputs):
        return 0.0
    return max(
        0.0,
        available_surplus_w(
            SurplusInputs(
                raw.smoothed_solar_power_w,
                raw.house_load_w,
                0.0,
                raw.immersion_on,
                raw.immersion_wattage_w,
            )
        ),
    )


def _initialize_coordinator_data(
    data: CoordinatorData,
    inputs: CycleInputs,
    accumulators: Accumulators,
    forecast: ForecastContext,
) -> None:
    """Initialize CoordinatorData with base values."""
    _apply_history(data, accumulators, forecast)
    _apply_config(data, inputs.cfg)
    _apply_live_readings(data, inputs.raw)
    _apply_derived_power(data, inputs.raw)


def _set_inverter_temperature(
    data: CoordinatorData,
    inverter_temp: float | None,
) -> None:
    """Populate inverter temperature and status on CoordinatorData."""
    data.inverter_temperature = inverter_temp
    if inverter_temp is None:
        data.inverter_temperature_status = INVERTER_TEMP_STATUS_UNKNOWN
    elif inverter_temp >= INVERTER_TEMP_CRITICAL:
        data.inverter_temperature_status = INVERTER_TEMP_STATUS_CRITICAL
    elif inverter_temp >= INVERTER_TEMP_DERATING:
        data.inverter_temperature_status = INVERTER_TEMP_STATUS_DERATING
    elif inverter_temp >= INVERTER_TEMP_WARM:
        data.inverter_temperature_status = INVERTER_TEMP_STATUS_WARM
    else:
        data.inverter_temperature_status = INVERTER_TEMP_STATUS_NORMAL


def _battery_cycle_cost(cfg: dict[str, Any], capacity_kwh: float) -> float:
    """Return €/kWh battery cycle cost, or 0.0 if CONF_BATTERY_COST is not set."""
    battery_cost = float(cfg.get(CONF_BATTERY_COST, DEFAULT_BATTERY_COST))
    if battery_cost <= 0 or capacity_kwh <= 0:
        return 0.0
    return battery_cost / (2 * capacity_kwh * BATTERY_RATED_CYCLES)


def _set_next_cheap_rate(data: CoordinatorData, tariff: TariffConfig, now: datetime) -> None:
    """Set hours to, and start time of, the next cheaper-than-base rate period."""
    upcoming = tariff.next_cheap_rate(now)
    if upcoming is not None:
        data.hours_to_cheap_rate, data.next_cheap_rate_start = upcoming


def _set_throughput_budget(data: CoordinatorData, cfg: dict[str, Any]) -> None:
    """Set budget used (%) and status from today's throughput, or None when no budget is set."""
    budget = float(cfg.get(CONF_BATTERY_THROUGHPUT_BUDGET, DEFAULT_BATTERY_THROUGHPUT_BUDGET))
    if budget <= 0:
        data.battery_throughput_budget_pct = None
        data.battery_throughput_budget_status = ""
        return
    pct = data.today.battery_throughput_kwh / budget * 100
    data.battery_throughput_budget_pct = pct
    if pct > 100:
        data.battery_throughput_budget_status = THROUGHPUT_BUDGET_STATUS_OVER
    elif pct >= THROUGHPUT_BUDGET_HIGH_PCT:
        data.battery_throughput_budget_status = THROUGHPUT_BUDGET_STATUS_HIGH
    else:
        data.battery_throughput_budget_status = THROUGHPUT_BUDGET_STATUS_OK


def _power_readings(raw: RawSensorValues) -> PowerReadings:
    missing = set(raw.unavailable_inputs)
    return PowerReadings(
        solar_power_w=None if "solar_power" in missing else raw.smoothed_solar_power_w,
        house_load_w=None if "house_load" in missing else raw.house_load_w,
        battery_power_w=None if "battery_power" in missing else raw.battery_power_w,
        battery_soc=raw.battery_soc,
        inverter_max_w=raw.inverter_max_w,
        immersion_power_w=raw.immersion_wattage_w,
    )


def _water_state(raw: RawSensorValues) -> WaterState:
    return WaterState(
        temp=raw.immersion_temp,
        target_temp=raw.immersion_target_temp,
        min_temp=raw.immersion_min_temp,
        hysteresis_c=raw.immersion_hysteresis_c,
        temp_unavailable="immersion_temp" in raw.unavailable_inputs,
    )


def _divert_policy(data: CoordinatorData, cycle: _Cycle) -> DivertPolicy:
    cfg = cycle.cfg
    return DivertPolicy(
        soc_threshold=int(cfg.get(CONF_SURPLUS_DIVERT_SOC, SURPLUS_DIVERT_SOC_THRESHOLD)),
        min_surplus_w=float(cfg.get(CONF_SURPLUS_DIVERT_MIN_W, SURPLUS_DIVERT_MIN_POWER_W)),
        battery_cycle_cost_per_kwh=data.battery_cycle_cost_per_kwh,
        export_rate=cycle.tariff.export_rate,
        currency_symbol=data.currency_symbol,
    )


def _immersion_inputs(data: CoordinatorData, cycle: _Cycle) -> ImmersionInputs:
    raw = cycle.raw
    return ImmersionInputs(
        power=_power_readings(raw),
        water=_water_state(raw),
        policy=_divert_policy(data, cycle),
        run=ImmersionRun(
            currently_on=raw.immersion_on,
            unavailable_for_s=raw.unavailable_for_s,
            switch_configured=raw.immersion_switch_configured,
        ),
    )


def _set_immersion_decision(data: CoordinatorData, cycle: _Cycle) -> None:
    """Set immersion divert decision."""
    data.battery_cycle_cost_per_kwh = _battery_cycle_cost(cycle.cfg, cycle.raw.battery_capacity_kwh)
    if cycle.overrides.immersion is not None:
        data.should_divert_immersion = cycle.overrides.immersion
        data.divert_reason = "Manual override"
        return
    data.should_divert_immersion, data.divert_reason = should_divert_to_immersion(
        _immersion_inputs(data, cycle)
    )


def _configured_min_soc(cfg: dict[str, Any]) -> int:
    return int(cfg.get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC))


def _charge_inputs(cycle: _Cycle, avg_daily_kwh: float) -> ChargeInputs:
    raw, cfg = cycle.raw, cycle.cfg
    return ChargeInputs(
        current_soc=raw.battery_soc,
        battery_capacity_kwh=raw.battery_capacity_kwh,
        min_soc=_configured_min_soc(cfg),
        skip_charge_threshold=int(
            cfg.get(CONF_SKIP_CHARGE_SOC_THRESHOLD, DEFAULT_SKIP_CHARGE_SOC_THRESHOLD)
        ),
        car_plugged_in=raw.ev_plugged_in,
        inverter_max_kw=raw.inverter_max_w / 1000,
        average_daily_consumption_kwh=avg_daily_kwh,
        cheapest_rate=cycle.tariff.get_cheapest_rate().rate,
        load_profile=cycle.forecast.load_profile,
        solar_power_w=raw.solar_power_w,
    )


def _solar_forecast(cycle: _Cycle) -> SolarForecast:
    """The forecasts for the solar day the charge decision serves.

    Until sunrise that day is today and the sensors, which moved on at midnight, now report
    tomorrow. Today's forecast is the one remembered before midnight, and tomorrow's reading
    becomes the day after the one being charged for.
    """
    raw, forecast = cycle.raw, cycle.forecast
    if cycle.now.hour < SOLAR_SUNRISE_HOUR:
        forecast_kwh = forecast.today_raw_forecast_kwh
        forecast_kwh_p10 = forecast.today_raw_forecast_p10_kwh
        forecast_kwh_d2 = raw.forecast_kwh_tomorrow
    else:
        forecast_kwh = raw.forecast_kwh_tomorrow
        forecast_kwh_p10 = raw.forecast_kwh_p10
        forecast_kwh_d2 = raw.forecast_kwh_d2
    return SolarForecast(
        forecast_kwh=forecast_kwh,
        solar_fractions=forecast.solar_fractions,
        forecast_kwh_p10=forecast_kwh_p10,
        forecast_conservatism=float(
            cycle.cfg.get(CONF_FORECAST_CONSERVATISM, DEFAULT_FORECAST_CONSERVATISM)
        ),
        forecast_kwh_d2=forecast_kwh_d2,
        forecast_correction=forecast.forecast_correction,
    )


def _overnight_charge_decision(cycle: _Cycle, avg_daily_kwh: float) -> ChargeDecision:
    return calculate_overnight_charge_target(
        _charge_inputs(cycle, avg_daily_kwh),
        _solar_forecast(cycle),
        cycle.now,
    )


def _with_charge_overrides(
    decision: ChargeDecision,
    overrides: ManualOverrides,
    max_target: int,
) -> ChargeDecision:
    """The decision with any manual override and the configured maximum applied."""
    if overrides.skip_charge:
        return replace(
            decision,
            skip_charge=True,
            reason="Manual override: skip overnight charge",
        )
    if overrides.charge_target is not None:
        return replace(
            decision,
            target_soc=overrides.charge_target,
            skip_charge=False,
            reason=f"Manual override: charge to {overrides.charge_target}%",
        )
    if decision.target_soc > max_target and not decision.skip_charge:
        return replace(
            decision,
            target_soc=max_target,
            reason=decision.reason + f" (capped at configured max {max_target}%)",
        )
    return decision


def _set_overnight_charge(
    data: CoordinatorData, cycle: _Cycle, avg_daily_kwh: float, held: HeldCharge
) -> None:
    """
    Work out tonight's charge target, then apply any manual override and the cap.

    charge_decision is the fresh result and is what gets written to the inverter. The
    sensors read published_charge_decision, built from the held calculation so it only
    moves once the fresh target is a clear step away. Overrides and the cap apply to both.
    """
    fresh = _overnight_charge_decision(cycle, avg_daily_kwh)
    held.decision = next_held_recommendation(held.decision, fresh)
    max_target = int(cycle.cfg.get(CONF_OVERNIGHT_CHARGE_TARGET, DEFAULT_OVERNIGHT_CHARGE_TARGET))
    data.charge_decision = _with_charge_overrides(fresh, cycle.overrides, max_target)
    data.published_charge_decision = _with_charge_overrides(
        held.decision, cycle.overrides, max_target
    )
    data.charge_window = _plan_charge_window(data, cycle)


def _plan_charge_window(data: CoordinatorData, cycle: _Cycle) -> ChargeWindow | None:
    """The window sized to the charge decision, None when the tariff has no timed period."""
    decision = data.charge_decision
    if decision is None or not cycle.tariff.rate_periods:
        return None
    # A skipped night charges nothing, so the window stays the cheapest period.
    target = decision.current_soc if decision.skip_charge else decision.target_soc
    need = ChargeNeed(
        soc=decision.current_soc,
        target_soc=target,
        capacity_kwh=decision.battery_capacity,
        charge_power_w=cycle.raw.battery_charge_rate_w,
    )
    return plan_charge_window(cycle.tariff, need)


def _calculate_ev_km(data: CoordinatorData, acc: EnergyAccumulator, cfg: dict[str, Any]) -> None:
    car_efficiency = float(
        cfg.get(CONF_CAR_EFFICIENCY_KWH_PER_100KM, DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM)
    )
    if car_efficiency > 0 and acc.zappi_kwh > 0:
        km = acc.zappi_kwh / car_efficiency * 100
        data.ev_km_charged_today = round(km, 1)
        if acc.zappi_cost > 0:
            data.ev_cost_per_km_today = round(acc.zappi_cost / km, 4)


def _minutes_remaining_in_period(
    tariff: TariffConfig, current_period: RatePeriod, now: datetime
) -> float | None:
    if current_period.name == tariff.base_rate_name or not tariff.rate_periods:
        return None
    end = local_time_on(now, current_period.end)
    if elapsed_seconds(now, end) <= 0:
        end = local_time_on(now + timedelta(days=1), current_period.end)
    return round(elapsed_seconds(now, end) / 60, 1)


def _calculate_night_survival(data: CoordinatorData, cycle: _Cycle, avg_daily_kwh: float) -> None:
    """Calculate night survival metrics."""
    raw = cycle.raw
    min_soc = _configured_min_soc(cycle.cfg)
    data.battery_min_soc = min_soc
    (
        data.will_survive_night,
        data.estimated_soc_at_sunrise,
        data.survival_reason,
    ) = estimate_will_survive_night(
        NightEstimateInputs(
            current_soc=raw.battery_soc,
            battery_capacity_kwh=raw.battery_capacity_kwh,
            min_soc=float(min_soc),
            hours_until_solar=hours_until_solar(cycle.now.hour, raw.solar_power_w),
            average_hourly_consumption_kwh=avg_daily_kwh / 24,
        )
    )


def _live_grid_cost_rate(cycle: _Cycle) -> float:
    """Live grid cost/earning rate in €/hr, using the tariff rate for each direction."""
    grid_kw = cycle.raw.grid_power_w / 1000
    if grid_kw > 0:
        return round(grid_kw * cycle.current_period.rate, 4)
    return round(grid_kw * cycle.tariff.export_rate, 4)


def _set_tariff_fields(data: CoordinatorData, cycle: _Cycle) -> None:
    tariff, period, now = cycle.tariff, cycle.current_period, cycle.now
    data.current_rate_name = period.name
    data.current_rate = period.rate
    _set_next_cheap_rate(data, tariff, now)
    cheapest = tariff.get_cheapest_rate()
    data.cheapest_rate = cheapest.rate
    data.cheapest_rate_name = cheapest.name
    data.is_on_cheapest_rate = bool(tariff.rate_periods) and period.rate <= cheapest.rate
    data.is_on_base_rate = period.name == tariff.base_rate_name
    # Minutes remaining in the current timed rate period (None for base/daytime rate)
    data.minutes_remaining_in_period = _minutes_remaining_in_period(tariff, period, now)
    # Rate savings vs the base (daytime) rate — 0 when currently at base rate
    data.rate_savings_vs_daytime = round(max(0.0, tariff.base_rate - period.rate), 4)
    data.live_grid_cost_rate = _live_grid_cost_rate(cycle)


def _set_battery_stats(data: CoordinatorData, cycle: _Cycle, previous: PreviousCycle) -> None:
    raw = cycle.raw
    today = cycle.now.date()
    reading = BatteryReading(
        None if "battery_soc" in raw.unavailable_inputs else raw.battery_soc,
        previous.last_soc,
        raw.battery_lifetime_cycles,
    )
    update_battery_stats(previous.battery_stats, reading, today)
    data.battery_stats = previous.battery_stats
    data.battery_years_remaining = previous.battery_stats.years_remaining_estimate(today)


def _accumulate_energy_today(
    data: CoordinatorData,
    cycle: _Cycle,
    accumulators: Accumulators,
    last_update_time: datetime | None,
) -> None:
    window = AccumulationWindow(
        cycle.tariff, cycle.current_period.name, cycle.now, last_update_time
    )
    for rolling_acc in accumulators.rolling():
        accumulate_energy(rolling_acc, cycle.raw, window)
    # Override today's physical kWh with GivTCP's own daily counters when available.
    # GivTCP reads directly from the inverter's metering, which is more accurate than
    # integrating 30-second power readings. Financial fields (costs, earnings) remain
    # integration-based since GivTCP has no tariff knowledge.
    _apply_daily_counters(accumulators.today, cycle.raw)
    data.today = accumulators.today


def _set_bill_fields(data: CoordinatorData, cycle: _Cycle, accumulators: Accumulators) -> None:
    tariff, now = cycle.tariff, cycle.now
    days_in = tariff.days_in_current_bill_period(now)
    days_remaining = tariff.days_remaining_in_bill_period(now)
    period_days = days_in + days_remaining
    bill_acc = accumulators.month if accumulators.month is not None else accumulators.today
    bill = tariff.calculate_bill(
        tariff.energy_cost_from_import_cost(bill_acc.total_import_cost),
        days_in,
        period_days,
        bill_acc.export_earnings,
    )
    data.accrued_bill = bill.total
    data.projected_bill = bill.total / days_in * period_days if days_in > 0 else 0.0
    data.days_in_period = days_in
    data.days_remaining = days_remaining


def _set_savings_fields(data: CoordinatorData) -> None:
    """The saving is what the load would have cost from the grid at the time, less what was paid."""
    acc = data.today
    actual_net_cost = acc.total_import_cost - acc.export_earnings
    data.saving_vs_grid_today = round(acc.grid_equivalent_load_cost - actual_net_cost, 4)
    battery_wear_today = acc.battery_throughput_kwh * data.battery_cycle_cost_per_kwh
    data.net_saving_today = round(data.saving_vs_grid_today - battery_wear_today, 4)


def _carbon_intensity_status(intensity_gco2: float | None) -> str:
    if intensity_gco2 is None:
        return CARBON_STATUS_UNKNOWN
    if intensity_gco2 < CARBON_LOW_THRESHOLD:
        return CARBON_STATUS_LOW
    if intensity_gco2 < CARBON_HIGH_THRESHOLD:
        return CARBON_STATUS_MEDIUM
    return CARBON_STATUS_HIGH


def _set_carbon_intensity(data: CoordinatorData, raw: RawSensorValues) -> None:
    data.carbon_intensity_gco2 = raw.carbon_intensity_gco2
    data.carbon_intensity_status = _carbon_intensity_status(raw.carbon_intensity_gco2)


def _apply_daily_counters(acc: EnergyAccumulator, raw: RawSensorValues) -> None:
    """
    Override today's physical kWh fields with GivTCP daily energy counters.

    GivTCP reads energy directly from the inverter's own metering, avoiding the
    small rounding errors introduced by integrating 30-second power readings.
    Only fields where the counter is present (not None) are overridden.
    Financial fields (costs, earnings, per-period breakdown) are left unchanged
    — they require tariff knowledge that GivTCP doesn't have.
    """
    if raw.solar_energy_today_kwh is not None:
        acc.solar_kwh = raw.solar_energy_today_kwh
    if raw.import_energy_today_kwh is not None:
        acc.import_kwh = raw.import_energy_today_kwh
    if raw.export_energy_today_kwh is not None:
        acc.export_kwh = raw.export_energy_today_kwh
    if raw.charge_energy_today_kwh is not None:
        acc.battery_charge_kwh = raw.charge_energy_today_kwh
    if raw.discharge_energy_today_kwh is not None:
        acc.battery_discharge_kwh = raw.discharge_energy_today_kwh
    if raw.load_energy_today_kwh is not None:
        acc.house_kwh = raw.load_energy_today_kwh



def _start_cycle(inputs: CycleInputs, forecast: ForecastContext, now: datetime) -> _Cycle:
    tariff = build_tariff(inputs.cfg)
    return _Cycle(
        inputs.raw,
        inputs.cfg,
        now,
        tariff,
        tariff.get_current_rate(now),
        inputs.overrides,
        forecast,
    )


def _set_decisions(
    data: CoordinatorData, cycle: _Cycle, avg_daily_kwh: float, held: HeldCharge
) -> None:
    """The charge target and the immersion divert, both of which honour manual overrides."""
    _set_overnight_charge(data, cycle, avg_daily_kwh, held)
    _set_immersion_decision(data, cycle)
    _set_inverter_temperature(data, cycle.raw.inverter_temp)


def _set_money_fields(data: CoordinatorData, cycle: _Cycle, accumulators: Accumulators) -> None:
    """Bill, savings and battery budget; they read the decisions above."""
    _set_bill_fields(data, cycle, accumulators)
    _set_savings_fields(data)
    _set_throughput_budget(data, cycle.cfg)


def build_coordinator_data(
    inputs: CycleInputs,
    accumulators: Accumulators,
    previous: PreviousCycle,
    forecast: ForecastContext,
) -> tuple[CoordinatorData, str | None]:
    """
    Core engine: build a complete CoordinatorData snapshot from raw inputs.

    Pure Python with no HA dependency. accumulators.today and previous.battery_stats
    are mutated in place.

    Returns (CoordinatorData, ev_target_mode). ev_target_mode is the Zappi mode string
    to apply (e.g. "Stopped", "Eco+"), or None if no mode change is needed. The
    coordinator applies it via a HA service call.
    """
    now = inputs.now if inputs.now is not None else datetime.now(timezone.utc)
    data = CoordinatorData()
    _initialize_coordinator_data(data, inputs, accumulators, forecast)

    cycle = _start_cycle(inputs, forecast, now)
    _set_tariff_fields(data, cycle)
    _set_battery_stats(data, cycle, previous)
    _accumulate_energy_today(data, cycle, accumulators, previous.last_update_time)
    avg_daily_kwh = estimate_avg_daily_kwh(data.today.house_kwh, now)

    _set_decisions(data, cycle, avg_daily_kwh, previous.held_charge)
    _set_money_fields(data, cycle, accumulators)
    _calculate_ev_km(data, accumulators.today, inputs.cfg)
    _calculate_night_survival(data, cycle, avg_daily_kwh)
    _set_carbon_intensity(data, inputs.raw)

    if inputs.ev_charger is None:
        return data, None
    return data, _process_ev_charger(data, inputs.ev_charger, inputs.raw)
