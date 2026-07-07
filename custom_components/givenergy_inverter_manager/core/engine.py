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
  ┌─────────────────────────────────────────────────────────────┐
  │  coordinator.py  (HA wiring — thin, ~80 lines)              │
  │    reads hass.states → calls engine → calls hass.services   │
  ├─────────────────────────────────────────────────────────────┤
  │  engine.py  (pure logic — fully testable, ~300 lines)       │
  │    all accumulation, decisions, predictions, derived values  │
  ├─────────────────────────────────────────────────────────────┤
  │  optimizer.py / tariff.py / battery.py / ev_charger_...     │
  │    individual algorithms, independently tested               │
  └─────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone

from ..const import (
    CONF_BATTERY_MIN_SOC,
    CONF_CURRENCY,
    CONF_DRY_RUN,
    CONF_EV_BATTERY_PROTECT_SOC,
    CONF_IMMERSION_MIN_TEMP,
    CONF_IMMERSION_TARGET_TEMP,
    CONF_OVERNIGHT_CHARGE_TARGET,
    CONF_SKIP_CHARGE_SOC_THRESHOLD,
    CONF_SURPLUS_DIVERT_MIN_W,
    CONF_SURPLUS_DIVERT_SOC,
    CURRENCIES,
    DEFAULT_BATTERY_MIN_SOC,
    DEFAULT_CURRENCY,
    DEFAULT_DRY_RUN,
    DEFAULT_EV_BATTERY_PROTECT_SOC,
    DEFAULT_IMMERSION_MIN_TEMP,
    DEFAULT_IMMERSION_TARGET_TEMP,
    DEFAULT_INVERTER_MAX_OUTPUT,
    DEFAULT_OVERNIGHT_CHARGE_TARGET,
    DEFAULT_SKIP_CHARGE_SOC_THRESHOLD,
    SOLAR_SUNRISE_HOUR,
    SURPLUS_DIVERT_MIN_POWER_W,
    SURPLUS_DIVERT_SOC_THRESHOLD,
)
from ..discovery import EVCharger, EVChargerState
from ..logging import get_logger
from .battery import BatteryStats, calculate_cycle_increment, estimate_will_survive_night
from .optimizer import (
    ChargeDecision,
    calculate_overnight_charge_target,
    should_divert_to_immersion,
)
from .rules import decide_ev_charger_action
from .tariff import EnergyAccumulator, TariffConfig, build_tariff

_LOG = get_logger(__name__)


@dataclass
class RawSensorValues:
    """
    Plain-Python container for all values read from HA entity states.

    Populated by the coordinator (HA layer) and passed into the engine.
    All values are primitives — no HA objects.
    """

    solar_power_w: float = 0.0
    battery_soc: float = 0.0
    battery_power_w: float = 0.0  # positive=charging, negative=discharging
    grid_power_w: float = 0.0  # positive=import, negative=export
    house_load_w: float = 0.0
    inverter_max_w: float = DEFAULT_INVERTER_MAX_OUTPUT * 1000
    battery_capacity_kwh: float = 10.0
    immersion_on: bool = False
    immersion_wattage_w: float = 3000.0
    immersion_temp: float | None = None
    forecast_kwh_tomorrow: float | None = None
    ev_power_w: float = 0.0
    ev_plugged_in: bool = False


class CoordinatorData:
    """
    Immutable-style snapshot produced by the engine each update cycle.

    Sensor entities read from this via value_fn lambdas. Using __slots__
    prevents accidental attribute creation and makes the data footprint clear.
    """

    __slots__ = (
        "accrued_bill",
        "battery_capacity_kwh",
        "battery_power_w",
        "battery_soc",
        "battery_stats",
        "charge_decision",
        "currency_symbol",
        "current_rate",
        "current_rate_name",
        "days_in_period",
        "days_remaining",
        "divert_reason",
        "dry_run",
        "dry_run_last_skipped",
        "estimated_soc_at_sunrise",
        "ev_available",
        "ev_charger_brand",
        "ev_charger_name",
        "ev_charger_state",
        "ev_draining_battery",
        "ev_power_w",
        "ev_protection_active",
        "ev_protection_reason",
        "ev_session_kwh",
        "forecast_kwh_tomorrow",
        "grid_power_w",
        "house_load_w",
        "immersion_load_w",
        "immersion_temp",
        "inverter_max_w",
        "is_clipping",
        "projected_bill",
        "rest_of_house_w",
        "should_divert_immersion",
        "solar_power_w",
        "survival_reason",
        "today",
        "week",
        "month",
        "yesterday",
        "last_reset_time",
        "solar_forecast_kwh_today",
        "yesterday_forecast_accuracy_pct",
        "forecast_accuracy_7day_avg_pct",
        "will_survive_night",
    )

    def __init__(self):
        self.solar_power_w: float = 0.0
        self.battery_soc: float = 0.0
        self.battery_power_w: float = 0.0
        self.grid_power_w: float = 0.0
        self.house_load_w: float = 0.0
        self.inverter_max_w: float = DEFAULT_INVERTER_MAX_OUTPUT * 1000
        self.battery_capacity_kwh: float = 0.0
        self.immersion_temp: float | None = None
        self.forecast_kwh_tomorrow: float | None = None
        self.immersion_load_w: float = 0.0
        self.rest_of_house_w: float = 0.0
        self.current_rate_name: str = ""
        self.current_rate: float = 0.0
        self.currency_symbol: str = "€"
        self.is_clipping: bool = False
        self.charge_decision: ChargeDecision | None = None
        self.should_divert_immersion: bool = False
        self.divert_reason: str = ""
        self.today: EnergyAccumulator = EnergyAccumulator()
        self.week: EnergyAccumulator = EnergyAccumulator()
        self.month: EnergyAccumulator = EnergyAccumulator()
        self.yesterday: EnergyAccumulator = EnergyAccumulator()
        self.battery_stats: BatteryStats = BatteryStats()
        self.accrued_bill: float = 0.0
        self.projected_bill: float = 0.0
        self.days_in_period: int = 0
        self.days_remaining: int = 0
        self.will_survive_night: bool = True
        self.estimated_soc_at_sunrise: float = 0.0
        self.survival_reason: str = ""
        self.ev_charger_brand: str = ""
        self.ev_charger_name: str = ""
        self.ev_charger_state: EVChargerState = EVChargerState.UNKNOWN
        self.ev_power_w: float = 0.0
        self.ev_session_kwh: float = 0.0
        self.ev_draining_battery: bool = False
        self.ev_protection_active: bool = False
        self.ev_protection_reason: str = ""
        self.ev_available: bool = False
        self.dry_run: bool = False
        self.dry_run_last_skipped: str = ""
        self.last_reset_time: str = ""
        self.solar_forecast_kwh_today: float = 0.0
        self.yesterday_forecast_accuracy_pct: float = 0.0
        self.forecast_accuracy_7day_avg_pct: float = 0.0


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


def _accumulate_import(
    acc: EnergyAccumulator,
    raw: RawSensorValues,
    tariff: TariffConfig,
    current_period_name: str,
    now: datetime,
    immersion_w: float,
    elapsed_h: float,
) -> None:
    """Handle import accumulation and cost apportionment."""
    kwh = (raw.grid_power_w / 1000) * elapsed_h
    period_cost = tariff.calculate_import_cost(kwh, now)
    acc.import_kwh += kwh
    acc.import_cost_by_period[current_period_name] = (
        acc.import_cost_by_period.get(current_period_name, 0.0) + period_cost
    )
    if current_period_name != tariff.base_rate_name:
        acc.import_kwh_cheap += kwh
        acc.import_cost_cheap += period_cost
    else:
        acc.import_kwh_peak += kwh
        acc.import_cost_peak += period_cost
    _apportion_import_cost(acc, period_cost, raw, immersion_w)


def _accumulate_immersion_savings(
    acc: EnergyAccumulator,
    raw: RawSensorValues,
    tariff: TariffConfig,
    now: datetime,
    immersion_w: float,
    elapsed_h: float,
) -> None:
    """Handle immersion savings when there is solar surplus."""
    if immersion_w <= 0:
        return
    solar_surplus_w = max(0.0, raw.solar_power_w - raw.house_load_w - max(0.0, raw.battery_power_w))
    solar_to_immersion_w = min(immersion_w, solar_surplus_w)
    if solar_to_immersion_w > 0:
        solar_diverted_kwh = (solar_to_immersion_w / 1000) * elapsed_h
        saving_per_kwh = max(0.0, tariff.get_current_rate(now).rate - tariff.export_rate)
        acc.immersion_solar_kwh += solar_diverted_kwh
        acc.immersion_savings += solar_diverted_kwh * saving_per_kwh


def accumulate_energy(
    acc: EnergyAccumulator,
    raw: RawSensorValues,
    tariff: TariffConfig,
    current_period_name: str,
    now: datetime,
    last_update_time: datetime | None,
) -> None:
    """
    Update energy accumulator in-place for one update interval.

    Only runs if last_update_time is set (i.e. not the first update).
    Uses elapsed wall-clock time between updates rather than assuming a
    fixed interval, so it stays accurate if the coordinator is delayed.

    Modifies acc in place; returns None.
    """
    if last_update_time is None:
        return

    elapsed_h = (now - last_update_time).total_seconds() / 3600
    # Guard against clock skew, HA restart with stale timestamp, or very long gaps
    # (>1 hour implies a restart; don't accumulate a huge energy spike)
    if elapsed_h <= 0 or elapsed_h > 1.0:
        return

    immersion_w = raw.immersion_wattage_w if raw.immersion_on else 0.0
    acc.solar_kwh += (raw.solar_power_w / 1000) * elapsed_h
    acc.zappi_kwh += (raw.ev_power_w / 1000) * elapsed_h
    acc.immersion_kwh += (immersion_w / 1000) * elapsed_h
    acc.house_kwh += (raw.house_load_w / 1000) * elapsed_h

    # Battery discharge/charge tracking (for self-sufficiency calculation)
    # Battery discharge/charge tracking (for self-sufficiency calculation)
    if raw.battery_power_w != 0:
        battery_kwh_this_step = abs(raw.battery_power_w / 1000) * elapsed_h
        acc.battery_throughput_kwh += battery_kwh_this_step
        if raw.battery_power_w < 0:
            acc.battery_discharge_kwh += battery_kwh_this_step
        else:
            acc.battery_charge_kwh += battery_kwh_this_step

    if raw.grid_power_w > 0:
        _accumulate_import(acc, raw, tariff, current_period_name, now, immersion_w, elapsed_h)
    elif raw.grid_power_w < 0:
        kwh = abs(raw.grid_power_w / 1000) * elapsed_h
        acc.export_kwh += kwh
        acc.export_earnings += tariff.calculate_export_earnings(kwh)

    _accumulate_immersion_savings(acc, raw, tariff, now, immersion_w, elapsed_h)


def estimate_avg_daily_kwh(
    house_kwh_today: float,
    now: datetime,
    fallback_kwh: float = 15.0,
    min_minutes: int = 30,
    absolute_min: float = 5.0,
) -> float:
    """
    Estimate average daily household consumption from today's partial data.

    Uses elapsed time since midnight rather than elapsed time since HA restart,
    so the estimate is stable even if HA restarts mid-day.

    Returns fallback_kwh if fewer than min_minutes have elapsed (too early to
    extrapolate reliably). Always returns at least absolute_min kWh.
    """
    minutes_since_midnight = now.hour * 60 + now.minute
    if minutes_since_midnight < min_minutes:
        return max(absolute_min, fallback_kwh)
    estimated = house_kwh_today * (1440 / minutes_since_midnight)
    return max(absolute_min, estimated)


def update_battery_stats(
    stats: BatteryStats,
    current_soc: float,
    last_soc: float | None,
) -> BatteryStats:
    """
    Update battery stats for the current SoC reading.

    Tracks cycle increments and records the date of the last full charge.
    Mutates stats in place and also returns it for convenience.
    """
    if last_soc is not None and current_soc != last_soc:
        increment = calculate_cycle_increment(current_soc - last_soc)
        stats.total_cycles += increment
        if current_soc >= 99.0:
            stats.last_full_charge_date = date.today()
    return stats


def _process_ev_charger(
    data: CoordinatorData,
    ev_charger: EVCharger,
    raw: RawSensorValues,
    cfg: dict,
) -> str | None:
    """Process EV charger state and return target mode."""
    data.ev_available = True
    data.ev_charger_brand = ev_charger.brand.value
    data.ev_charger_name = ev_charger.display_name
    data.ev_charger_state = ev_charger.state
    data.ev_power_w = ev_charger.power_w
    data.ev_session_kwh = ev_charger.session_kwh
    data.ev_draining_battery = ev_charger.is_draining_battery

    solar_surplus_w = max(0.0, raw.solar_power_w - raw.house_load_w - data.immersion_load_w)
    protect_threshold = float(cfg.get(CONF_EV_BATTERY_PROTECT_SOC, DEFAULT_EV_BATTERY_PROTECT_SOC))

    ev_target_mode, reason = decide_ev_charger_action(
        charger=ev_charger,
        battery_soc=raw.battery_soc,
        battery_power_w=raw.battery_power_w,
        solar_surplus_w=solar_surplus_w,
        protection_threshold=protect_threshold,
    )
    data.ev_protection_reason = reason
    data.ev_protection_active = ev_target_mode is not None
    return ev_target_mode


def _initialize_coordinator_data(
    data: CoordinatorData,
    raw: RawSensorValues,
    cfg: dict,
    acc_week: EnergyAccumulator | None,
    acc_month: EnergyAccumulator | None,
    acc_yesterday: EnergyAccumulator | None,
    last_reset_time: str,
    solar_forecast_kwh_today: float,
    yesterday_forecast_accuracy_pct: float,
    forecast_accuracy_7day_avg_pct: float,
) -> None:
    """Initialize CoordinatorData with base values."""
    data.last_reset_time = last_reset_time
    data.solar_forecast_kwh_today = solar_forecast_kwh_today
    data.yesterday_forecast_accuracy_pct = yesterday_forecast_accuracy_pct
    data.forecast_accuracy_7day_avg_pct = forecast_accuracy_7day_avg_pct
    if acc_week is not None:
        data.week = acc_week
    if acc_month is not None:
        data.month = acc_month
    if acc_yesterday is not None:
        data.yesterday = acc_yesterday

    data.dry_run = bool(cfg.get(CONF_DRY_RUN, DEFAULT_DRY_RUN))
    currency_code = cfg.get(CONF_CURRENCY, DEFAULT_CURRENCY)
    data.currency_symbol = CURRENCIES.get(currency_code, "€")
    data.solar_power_w = raw.solar_power_w
    data.battery_soc = raw.battery_soc
    data.battery_power_w = raw.battery_power_w
    data.grid_power_w = raw.grid_power_w
    data.house_load_w = raw.house_load_w
    data.inverter_max_w = raw.inverter_max_w
    data.battery_capacity_kwh = raw.battery_capacity_kwh
    data.immersion_temp = raw.immersion_temp
    data.forecast_kwh_tomorrow = raw.forecast_kwh_tomorrow
    data.immersion_load_w = raw.immersion_wattage_w if raw.immersion_on else 0.0
    data.rest_of_house_w = max(
        0.0,
        raw.house_load_w - raw.ev_power_w - data.immersion_load_w,
    )
    data.is_clipping = raw.solar_power_w >= (raw.inverter_max_w * 0.95)


def _apply_charge_overrides(
    data: CoordinatorData,
    override_skip_charge: bool,
    override_charge_target: int | None,
    max_target: int,
) -> None:
    """Apply charge target overrides to charge decision."""
    if override_skip_charge:
        data.charge_decision = replace(
            data.charge_decision,
            skip_charge=True,
            reason="Manual override: skip overnight charge",
        )
    elif override_charge_target is not None:
        data.charge_decision = replace(
            data.charge_decision,
            target_soc=override_charge_target,
            skip_charge=False,
            reason=f"Manual override: charge to {override_charge_target}%",
        )
    elif data.charge_decision.target_soc > max_target and not data.charge_decision.skip_charge:
        data.charge_decision = replace(
            data.charge_decision,
            target_soc=max_target,
            reason=data.charge_decision.reason + f" (capped at configured max {max_target}%)",
        )


def _set_immersion_decision(
    data: CoordinatorData,
    raw: RawSensorValues,
    cfg: dict,
    override_immersion: bool | None,
) -> None:
    """Set immersion divert decision."""
    if override_immersion is not None:
        data.should_divert_immersion = override_immersion
        data.divert_reason = "Manual override"
    else:
        data.should_divert_immersion, data.divert_reason = should_divert_to_immersion(
            solar_power_w=raw.solar_power_w,
            house_load_w=raw.house_load_w,
            battery_soc=raw.battery_soc,
            battery_power_w=raw.battery_power_w,
            inverter_max_w=raw.inverter_max_w,
            immersion_temp=raw.immersion_temp,
            immersion_target_temp=cfg.get(
                CONF_IMMERSION_TARGET_TEMP, DEFAULT_IMMERSION_TARGET_TEMP
            ),
            immersion_min_temp=float(cfg.get(CONF_IMMERSION_MIN_TEMP, DEFAULT_IMMERSION_MIN_TEMP)),
            soc_threshold=int(cfg.get(CONF_SURPLUS_DIVERT_SOC, SURPLUS_DIVERT_SOC_THRESHOLD)),
            min_surplus_w=float(cfg.get(CONF_SURPLUS_DIVERT_MIN_W, SURPLUS_DIVERT_MIN_POWER_W)),
        )


def _calculate_night_survival(
    data: CoordinatorData,
    raw: RawSensorValues,
    now: datetime,
    min_soc: int,
    avg_daily_kwh: float,
) -> None:
    """Calculate night survival metrics."""
    if now.hour < SOLAR_SUNRISE_HOUR:
        hours_until_solar = max(1, SOLAR_SUNRISE_HOUR - now.hour)
    else:
        hours_until_solar = (24 - now.hour) + SOLAR_SUNRISE_HOUR
    avg_hourly = avg_daily_kwh / 24
    (
        data.will_survive_night,
        data.estimated_soc_at_sunrise,
        data.survival_reason,
    ) = estimate_will_survive_night(
        current_soc=raw.battery_soc,
        battery_capacity_kwh=raw.battery_capacity_kwh,
        min_soc=float(min_soc),
        hours_until_solar=float(hours_until_solar),
        average_hourly_consumption_kwh=avg_hourly,
    )


def build_coordinator_data(
    raw: RawSensorValues,
    cfg: dict,
    acc: EnergyAccumulator,
    battery_stats: BatteryStats,
    last_soc: float | None,
    last_update_time: datetime | None,
    acc_week: EnergyAccumulator | None = None,
    acc_month: EnergyAccumulator | None = None,
    acc_yesterday: EnergyAccumulator | None = None,
    now: datetime | None = None,
    ev_charger: EVCharger | None = None,
    override_charge_target: int | None = None,
    override_immersion: bool | None = None,
    override_skip_charge: bool = False,
    solar_fractions: dict[int, float] | None = None,
    last_reset_time: str = "",
    solar_forecast_kwh_today: float = 0.0,
    yesterday_forecast_accuracy_pct: float = 0.0,
    forecast_accuracy_7day_avg_pct: float = 0.0,
) -> tuple[CoordinatorData, str | None]:
    """
    Core engine: build a complete CoordinatorData snapshot from raw inputs.

    This is the central function of the engine. It is pure Python with no HA
    dependency and can be called directly in unit tests.

    Args:
        raw:                   Sensor readings collected by the coordinator
        cfg:                   Merged config dict (entry.data | entry.options)
        acc:                   Today's energy accumulator (mutated in place)
        battery_stats:         Lifetime battery stats (mutated in place)
        last_soc:              Battery SoC from previous cycle (for cycle counting)
        last_update_time:      Datetime of previous update (for energy accumulation)
        now:                   Current datetime (injectable for testing)
        ev_charger:            Discovered EV charger with current state, or None
        override_charge_target: Manual charge target % override, or None for auto
        override_immersion:    Manual immersion override, or None for auto
        override_skip_charge:  When True, force skip_charge=True regardless of forecast

    Returns:
        (CoordinatorData, ev_target_mode)
        ev_target_mode is the Zappi mode string to apply (e.g. "Stopped", "Eco+"),
        or None if no mode change is needed. The coordinator applies this via
        a HA service call.
    """
    if now is None:
        # Fallback for tests only — production always passes local now from coordinator.
        now = datetime.now(timezone.utc)

    data = CoordinatorData()
    _initialize_coordinator_data(
        data,
        raw,
        cfg,
        acc_week,
        acc_month,
        acc_yesterday,
        last_reset_time,
        solar_forecast_kwh_today,
        yesterday_forecast_accuracy_pct,
        forecast_accuracy_7day_avg_pct,
    )

    # ── Tariff ────────────────────────────────────────────────────────────────
    tariff = build_tariff(cfg)
    current_period = tariff.get_current_rate(now)
    data.current_rate_name = current_period.name
    data.current_rate = current_period.rate

    # ── Battery stats ─────────────────────────────────────────────────────────
    update_battery_stats(battery_stats, raw.battery_soc, last_soc)
    data.battery_stats = battery_stats

    # ── Energy accumulation ───────────────────────────────────────────────────
    for rolling_acc in (acc, acc_week, acc_month):
        if rolling_acc is not None:
            accumulate_energy(rolling_acc, raw, tariff, current_period.name, now, last_update_time)
    data.today = acc

    # ── Average daily consumption ─────────────────────────────────────────────
    avg_daily_kwh = estimate_avg_daily_kwh(acc.house_kwh, now)

    # ── Overnight charge decision ─────────────────────────────────────────────
    min_soc = int(cfg.get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC))
    skip_threshold = int(cfg.get(CONF_SKIP_CHARGE_SOC_THRESHOLD, DEFAULT_SKIP_CHARGE_SOC_THRESHOLD))

    data.charge_decision = calculate_overnight_charge_target(
        current_soc=raw.battery_soc,
        battery_capacity_kwh=raw.battery_capacity_kwh,
        forecast_kwh=raw.forecast_kwh_tomorrow,
        inverter_max_kw=raw.inverter_max_w / 1000,
        car_plugged_in=raw.ev_plugged_in,
        min_soc=min_soc,
        skip_charge_threshold=skip_threshold,
        average_daily_consumption_kwh=avg_daily_kwh,
        cheapest_rate=tariff.get_cheapest_rate().rate,
        solar_fractions=solar_fractions,
        dt=now,
    )

    max_target = int(cfg.get(CONF_OVERNIGHT_CHARGE_TARGET, DEFAULT_OVERNIGHT_CHARGE_TARGET))
    _apply_charge_overrides(
        data,
        override_skip_charge,
        override_charge_target,
        max_target,
    )

    # ── Immersion divert decision ─────────────────────────────────────────────
    _set_immersion_decision(data, raw, cfg, override_immersion)

    # ── Bill prediction ───────────────────────────────────────────────────────
    days_in = tariff.days_in_current_bill_period(now)
    days_remaining = tariff.days_remaining_in_bill_period(now)
    standing = tariff.calculate_standing_charges(days_in)
    data.accrued_bill = acc.total_import_cost + standing
    data.projected_bill = (
        (data.accrued_bill / max(1, days_in)) * (days_in + days_remaining) if days_in > 0 else 0.0
    )
    data.days_in_period = days_in
    data.days_remaining = days_remaining

    # ── Night survival ────────────────────────────────────────────────────────
    _calculate_night_survival(data, raw, now, min_soc, avg_daily_kwh)

    # ── EV charger state ─────────────────────────────────────────────────────
    ev_target_mode: str | None = None
    if ev_charger is not None:
        ev_target_mode = _process_ev_charger(data, ev_charger, raw, cfg)

    return data, ev_target_mode
