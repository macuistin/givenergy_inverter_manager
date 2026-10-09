"""
accumulation.py — Multi-period energy accumulation with HA Storage persistence.

Owns all energy accumulator instances (today/week/month/yesterday) and forecast
accuracy tracking. Persists state across HA restarts using
homeassistant.helpers.storage.Store.

Architecture note: this module imports from HA (for Storage) and therefore
lives in the HA layer. The engine receives plain EnergyAccumulator objects
and has no dependency here.

Resets:
  today   — midnight every day
  week    — Monday midnight (ISO week start)
  month   — bill_start_day midnight (from config)
  yesterday — snapshot of today taken at midnight before reset
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from .const import REGISTER_WRITE_LOG_MAX_ENTRIES
from .core.immersion_rate import keep_run
from .core.oil_schedule import ImmersionHeatLog
from .core.rules import (
    ForecastAccuracy,
    build_load_profile,
    forecast_accuracy,
    forecast_correction_factor,
)
from .core.tariff import CounterMemory, EnergyAccumulator
from .core.write_log import restore_entries

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOG = logging.getLogger(__name__)
_STORAGE_KEY = "givenergy_inverter_manager.energy"
_STORAGE_VERSION = 4
# Version 1 counted battery cycles in both directions (charge and discharge).
# Version 2 counts discharge only, so stored cycle figures are halved once.
_CYCLE_FIELDS_HALVED_AT_V2 = ("battery_cycles", "battery_tracking_start_cycles")
# Version 2 divided actual solar by the blended forecast the first charge decision of the day
# used, which can be for another day. Version 3 divides by the raw forecast for the day, so the
# stored accuracy history is rebuilt from forecast_ratio_history, which holds that pair.
# Version 4 adds grid_to_battery_kwh to every accumulator, the grid energy stored in the battery.
# Older periods did not track it, so they start at 0 and read as import only.
_ACCUMULATOR_KEYS = ("today", "week", "month", "year", "yesterday")
# The record of the immersion's grid heating is read with .get and stored only once it holds a
# day, so it needs no storage version and an install without an oil price never stores it.
_HEAT_LOG_KEY = "immersion_heat_history"
_FORECAST_HISTORY_DAYS = 7
_FORECAST_RATIO_HISTORY_DAYS = 14
_SLOT_HISTORY_DAYS = 28
_SLOTS_PER_DAY = 48
_SLOT_HOURS = 0.5
_SAVE_DELAY_SECONDS = 15


# ── Serialisation helpers ─────────────────────────────────────────────────────


def _acc_to_dict(acc: EnergyAccumulator) -> dict:
    """Serialise an EnergyAccumulator to a JSON-safe dict."""
    return {
        "import_kwh": acc.import_kwh,
        "export_kwh": acc.export_kwh,
        "solar_kwh": acc.solar_kwh,
        "battery_discharge_kwh": acc.battery_discharge_kwh,
        "battery_charge_kwh": acc.battery_charge_kwh,
        "zappi_kwh": acc.zappi_kwh,
        "immersion_kwh": acc.immersion_kwh,
        "house_kwh": acc.house_kwh,
        "grid_to_battery_kwh": acc.grid_to_battery_kwh,
        "import_kwh_cheap": acc.import_kwh_cheap,
        "import_kwh_peak": acc.import_kwh_peak,
        "import_cost_cheap": acc.import_cost_cheap,
        "import_cost_peak": acc.import_cost_peak,
        "import_cost_by_period": dict(acc.import_cost_by_period),
        "export_earnings": acc.export_earnings,
        "zappi_cost": acc.zappi_cost,
        "immersion_cost": acc.immersion_cost,
        "house_cost": acc.house_cost,
        "grid_equivalent_load_cost": acc.grid_equivalent_load_cost,
        "immersion_solar_kwh": acc.immersion_solar_kwh,
        "immersion_savings": acc.immersion_savings,
        "battery_throughput_kwh": acc.battery_throughput_kwh,
        "missed_solar_kwh": acc.missed_solar_kwh,
        "inverter_derating_minutes": acc.inverter_derating_minutes,
    }


def _dict_to_acc(d: dict) -> EnergyAccumulator:
    """Deserialise a dict back into an EnergyAccumulator."""
    acc = EnergyAccumulator()
    for key, value in d.items():
        if hasattr(acc, key):
            setattr(acc, key, value)
    if "grid_equivalent_load_cost" not in d:
        acc.grid_equivalent_load_cost = _estimated_grid_equivalent_load_cost(acc)
    return acc


def _estimated_grid_equivalent_load_cost(acc: EnergyAccumulator) -> float:
    """Price data saved before the cost was tracked at the average rate actually paid.

    Without it the saving would read low until the day the cost starts accumulating ends.
    """
    if acc.import_kwh <= 0:
        return 0.0
    return acc.house_kwh * acc.total_import_cost / acc.import_kwh


def _midnight_of(now: datetime, day: date) -> datetime:
    """Local midnight at the start of *day*, in the timezone of *now*."""
    return now.replace(
        year=day.year, month=day.month, day=day.day, hour=0, minute=0, second=0, microsecond=0
    )


def _stored_date(iso: str) -> date | None:
    """Date part of a stored ISO timestamp, or None when empty or unreadable."""
    try:
        return datetime.fromisoformat(iso).date()
    except (TypeError, ValueError):
        return None
def _as_count(value) -> int:
    """Return value as a non-negative int, or 0 if it is not a number."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def migrate_storage(old_version: int, data: dict) -> dict:
    """Bring a stored payload up to the current storage version.

    Version 1 -> 2 converts the battery cycle figures from the old both-directions
    definition to discharge only by halving them. Version 2 -> 3 rebuilds the forecast
    accuracy figures. Version 3 -> 4 gives each period a grid-to-battery figure of 0. The
    inner "version" key makes each conversion safe to call twice on the same payload.
    """
    migrated = dict(data)
    if old_version < 2 and int(migrated.get("version", 1)) < 2:
        for key in _CYCLE_FIELDS_HALVED_AT_V2:
            try:
                migrated[key] = float(migrated.get(key, 0.0)) / 2
            except (TypeError, ValueError):
                migrated[key] = 0.0
        migrated.setdefault("register_write_count", 0)
        migrated["version"] = 2
    if old_version < 3 and int(migrated.get("version", 1)) < 3:
        _rebuild_forecast_accuracy(migrated)
        migrated["version"] = 3
    if old_version < 4 and int(migrated.get("version", 1)) < 4:
        _add_grid_to_battery(migrated)
        migrated["version"] = 4
    return migrated


def _with_grid_to_battery(stored: dict) -> dict:
    """A copy of one stored period with a grid-to-battery figure, 0 unless it already has one."""
    return {"grid_to_battery_kwh": 0.0, **stored}


def _add_grid_to_battery(payload: dict) -> None:
    """Give every stored period, and every monthly snapshot, a grid-to-battery figure of 0.

    A figure already there is kept, so running the step twice changes nothing. The nested
    dicts are copied, so the payload the caller passed in is left as it was.
    """
    for key in _ACCUMULATOR_KEYS:
        if isinstance(payload.get(key), dict):
            payload[key] = _with_grid_to_battery(payload[key])
    snapshots = payload.get("monthly_snapshots")
    if isinstance(snapshots, list):
        payload["monthly_snapshots"] = [
            _with_grid_to_battery(entry) if isinstance(entry, dict) else entry
            for entry in snapshots
        ]


def _forecast_accuracy_pct(forecast_kwh: float, actual_kwh: float) -> float:
    """Actual solar as a percentage of the forecast. It has no upper limit."""
    return round(actual_kwh / forecast_kwh * 100, 1)


def _rebuild_forecast_accuracy(payload: dict) -> None:
    """Replace the stored accuracy figures with ones measured against the raw forecast.

    forecast_ratio_history holds the raw forecast and the actual solar of each completed day.
    A day with no actual solar is skipped, because it can be a day Home Assistant was down.
    With no usable days the history starts empty and the sensors read 0 until the next midnight.
    """
    records = payload.get("forecast_ratio_history", [])
    history = []
    for record in records if isinstance(records, list) else []:
        try:
            forecast, actual = float(record["forecast"]), float(record["actual"])
        except (KeyError, TypeError, ValueError):
            continue
        if forecast > 0 and actual > 0:
            history.append(_forecast_accuracy_pct(forecast, actual))
    payload["forecast_accuracy_history"] = history[-_FORECAST_HISTORY_DAYS:]
    payload["yesterday_forecast_accuracy_pct"] = history[-1] if history else 0.0


def _create_store(hass: HomeAssistant):
    """Build the HA Store with a version migration hook."""
    from homeassistant.helpers.storage import Store  # lazy — not available in test env

    class _AccumulationStorage(Store):
        async def _async_migrate_func(self, old_major_version, old_minor_version, old_data):
            return migrate_storage(old_major_version, old_data)

    return _AccumulationStorage(hass, _STORAGE_VERSION, _STORAGE_KEY)


# ── Public state dataclass ────────────────────────────────────────────────────


@dataclass
class AccumulationState:
    """All accumulated energy state across time periods."""

    today: EnergyAccumulator = field(default_factory=EnergyAccumulator)
    week: EnergyAccumulator = field(default_factory=EnergyAccumulator)
    month: EnergyAccumulator = field(default_factory=EnergyAccumulator)
    year: EnergyAccumulator = field(default_factory=EnergyAccumulator)
    yesterday: EnergyAccumulator = field(default_factory=EnergyAccumulator)
    # Last GivTCP counter readings, kept across midnight. See CounterMemory.
    counters: CounterMemory = field(default_factory=CounterMemory)

    # First forecast the charge decision used today. Feeds the "Solar forecast today" sensor
    # and today's solar against forecast, not the accuracy history.
    today_forecast_kwh: float = 0.0
    battery_cycles: float = 0.0
    last_full_charge_date: str = ""  # ISO date string, "" = never
    battery_tracking_start: str = ""  # ISO date cycle tracking began, "" = not started
    battery_tracking_start_cycles: float = 0.0
    register_write_count: int = 0  # lifetime GivTCP register writes made by this integration
    # Newest-last log of recent writes and outside changes, see core/write_log.py.
    register_write_log: list = field(default_factory=list)
    yesterday_forecast_accuracy_pct: float = 0.0
    forecast_accuracy_history: list = field(default_factory=list)  # last 7 days

    # Raw P50 forecast (before P10 blend or seasonal fallback) used for the forecast accuracy
    # and its correction. pending is the latest value seen today; at midnight it becomes
    # the forecast for the new day. ratio history holds {"forecast", "actual", "clipped"}.
    # The P10 pair follows the same path so a charge decision made after midnight can
    # still read the forecast for the day it serves.
    pending_raw_forecast_kwh: float = 0.0
    today_raw_forecast_kwh: float = 0.0
    pending_raw_forecast_p10_kwh: float = 0.0
    today_raw_forecast_p10_kwh: float = 0.0
    today_clipping: bool = False
    forecast_ratio_history: list = field(default_factory=list)

    # Per-slot (30 min) baseline house load. History entries are
    # {"date", "slots", "coverage"}, oldest first, capped at _SLOT_HISTORY_DAYS.
    slot_load_today: list = field(default_factory=lambda: [0.0] * _SLOTS_PER_DAY)
    slot_hours_today: list = field(default_factory=lambda: [0.0] * _SLOTS_PER_DAY)
    slot_load_date: str = ""
    slot_load_history: list = field(default_factory=list)

    # Heating rates (degrees per hour) of the last few immersion runs, oldest first. The
    # ready-by plan reads their median. See core/immersion_rate.py.
    immersion_heating_rates: list = field(default_factory=list)

    # The immersion's grid heating by local hour for the last 14 complete days and today, with
    # what it cost. Filled only while an oil price is set. See core/oil_schedule.py.
    immersion_heat_log: ImmersionHeatLog = field(default_factory=ImmersionHeatLog)

    # Rolling 12-month export snapshots — one entry per completed billing month,
    # oldest first, capped at 12. Populated at each monthly reset before clearing.
    monthly_export_snapshots: list = field(default_factory=list)

    # Rolling 12-month snapshots — one dict per completed billing month (oldest first).
    # Each entry is the full _acc_to_dict() output of state.month at reset.
    monthly_snapshots: list = field(default_factory=list)

    # Reset timestamps (ISO strings for JSON serialisation)
    week_start_iso: str = ""
    month_start_iso: str = ""
    year_start_iso: str = ""
    last_reset_iso: str = ""


# ── Main store class ──────────────────────────────────────────────────────────


class AccumulationStore:
    """
    Manages multi-period energy accumulation with HA Storage persistence.

    Usage in coordinator:
        store = AccumulationStore(hass, bill_start_day=1)
        await store.async_load()
        # each update cycle:
        accumulate_energy(store.today, raw, tariff, period, now, last)
        accumulate_energy(store.week,  raw, tariff, period, now, last)
        accumulate_energy(store.month, raw, tariff, period, now, last)
        # after charge decision:
        store.on_charge_decision(charge_decision.forecast_kwh)
        # at midnight:
        store.on_midnight(now, bill_start_day)
        await store.async_save()
    """

    def __init__(self, hass: HomeAssistant, bill_start_day: int) -> None:
        self._store = _create_store(hass)
        self._bill_start_day = bill_start_day
        self.state = AccumulationState()

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def today(self) -> EnergyAccumulator:
        return self.state.today

    @property
    def week(self) -> EnergyAccumulator:
        return self.state.week

    @property
    def month(self) -> EnergyAccumulator:
        return self.state.month

    @property
    def year(self) -> EnergyAccumulator:
        return self.state.year

    @property
    def yesterday(self) -> EnergyAccumulator:
        return self.state.yesterday

    @property
    def counters(self) -> CounterMemory:
        return self.state.counters

    @property
    def today_forecast_kwh(self) -> float:
        return self.state.today_forecast_kwh

    @property
    def today_raw_forecast_kwh(self) -> float | None:
        """Today's raw P50 forecast as it stood before midnight, None when none was seen."""
        return self.state.today_raw_forecast_kwh or None

    @property
    def today_raw_forecast_p10_kwh(self) -> float | None:
        """Today's raw P10 forecast as it stood before midnight, None when none was seen."""
        return self.state.today_raw_forecast_p10_kwh or None

    @property
    def yesterday_forecast_accuracy_pct(self) -> float:
        return self.state.yesterday_forecast_accuracy_pct

    @property
    def forecast_accuracy_7day_avg_pct(self) -> float:
        """Rolling 7-day average forecast accuracy (0 if no history)."""
        h = self.state.forecast_accuracy_history
        return round(sum(h) / len(h), 1) if h else 0.0

    @property
    def forecast_correction_factor(self) -> float | None:
        """Median actual/forecast ratio of recent days, or None until enough usable days."""
        return forecast_correction_factor(self.state.forecast_ratio_history)

    @property
    def forecast_history_days(self) -> int:
        """How many days of forecast and solar pairs the store keeps."""
        return _FORECAST_RATIO_HISTORY_DAYS

    @property
    def forecast_history_is_empty(self) -> bool:
        return not self.state.forecast_ratio_history

    @property
    def forecast_accuracy(self) -> ForecastAccuracy:
        """The measured correction, its usable days and whether it is applied yet."""
        return forecast_accuracy(self.state.forecast_ratio_history)

    def slot_load_profile(self, target_weekday: int) -> list[float] | None:
        """48-slot baseline load profile for target_weekday (Monday=0), or None."""
        return build_load_profile(self.state.slot_load_history, target_weekday)

    @property
    def trailing_12m_export_kwh(self) -> float:
        """Sum of the last 12 completed billing months' export kWh."""
        return round(sum(self.state.monthly_export_snapshots), 3)

    @property
    def monthly_export_snapshots(self) -> list[float]:
        """Export kWh for each of the last 12 completed billing months, oldest first."""
        return list(self.state.monthly_export_snapshots)

    @property
    def monthly_snapshots(self) -> list[dict]:
        """Snapshots of completed billing months, oldest first (max 12)."""
        return list(self.state.monthly_snapshots)

    def _trailing_12m(self, field: str) -> float:
        """Sum a numeric field across the last 12 monthly snapshots."""
        return round(sum(s.get(field, 0.0) for s in self.state.monthly_snapshots), 3)

    @property
    def trailing_12m_solar_kwh(self) -> float:
        return self._trailing_12m("solar_kwh")

    @property
    def trailing_12m_import_kwh(self) -> float:
        return self._trailing_12m("import_kwh")

    @property
    def trailing_12m_import_cost(self) -> float:
        total = sum(
            sum(s.get("import_cost_by_period", {}).values())
            for s in self.state.monthly_snapshots
        )
        return round(total, 4)

    @property
    def trailing_12m_export_earnings(self) -> float:
        return self._trailing_12m("export_earnings")

    # ── HA Storage ────────────────────────────────────────────────────────────

    async def async_load(self) -> None:
        """Restore state from HA storage. Safe to call even if no data exists."""
        data = await self._store.async_load()
        if data is None:
            _LOG.debug("No stored accumulation data — starting fresh")
            return
        try:
            self.state = _deserialize(data)
            _LOG.debug(
                "Restored accumulation: today=%.2fkWh solar, week=%.2fkWh, month=%.2fkWh",
                self.state.today.solar_kwh,
                self.state.week.solar_kwh,
                self.state.month.solar_kwh,
            )
        except Exception as err:
            _LOG.warning("Could not restore accumulation state: %s — starting fresh", err)
            self.state = AccumulationState()

    async def async_save(self) -> None:
        """Persist current state to HA storage."""
        try:
            await self._store.async_save(_serialize(self.state))
        except Exception as err:
            _LOG.warning("Could not save accumulation state: %s", err)

    def schedule_save(self) -> None:
        """Queue a save. HA writes it after a short delay, or at shutdown if still pending."""
        self._store.async_delay_save(lambda: _serialize(self.state), _SAVE_DELAY_SECONDS)

    # ── Event handlers ────────────────────────────────────────────────────────

    def on_midnight(self, now: datetime) -> None:
        """
        Handle midnight reset.

        Order of operations:
          1. Snapshot today → yesterday (before clearing today)
          2. Calculate forecast accuracy for the completed day
          3. Reset today accumulator
          4. Reset week accumulator if today is Monday (ISO week start)
          5. Reset month accumulator if today is bill_start_day
          6. Reset year accumulator on 1 January
        """
        today_date = now.date()
        self.state.yesterday = self.state.today
        self._record_forecast_accuracy()
        self._record_forecast_ratio()
        if self.state.slot_load_date and self.state.slot_load_date < today_date.isoformat():
            self._archive_slot_day()
        self._reset_today(now)
        if today_date.isoweekday() == 1:
            self._reset_week(now)
        if today_date.day == self._bill_start_day:
            self._reset_month(now)
        if today_date.month == 1 and today_date.day == 1:
            self._reset_year(now)

    def _record_forecast_accuracy(self) -> None:
        """Forecast accuracy for the completed day, kept for the last seven days.

        Measured against the raw forecast remembered for that day, the figure the accuracy
        correction uses. A day with no raw forecast, or with nothing accumulated, is skipped.
        """
        forecast = self.state.today_raw_forecast_kwh
        if forecast <= 0 or self.state.today == EnergyAccumulator():
            return
        actual = self.state.today.solar_kwh
        accuracy = _forecast_accuracy_pct(forecast, actual)
        self.state.yesterday_forecast_accuracy_pct = accuracy
        history = self.state.forecast_accuracy_history[-(_FORECAST_HISTORY_DAYS - 1) :]
        history.append(accuracy)
        self.state.forecast_accuracy_history = history
        _LOG.debug(
            "Forecast accuracy for completed day: %.1f%% (forecast %.1fkWh, actual %.1fkWh)",
            accuracy,
            forecast,
            actual,
        )

    def _reset_today(self, now: datetime) -> None:
        self.state.today = EnergyAccumulator()
        self.state.today_forecast_kwh = 0.0
        self.state.today_raw_forecast_kwh = self.state.pending_raw_forecast_kwh
        self.state.pending_raw_forecast_kwh = 0.0
        self.state.today_raw_forecast_p10_kwh = self.state.pending_raw_forecast_p10_kwh
        self.state.pending_raw_forecast_p10_kwh = 0.0
        self.state.today_clipping = False
        self.state.last_reset_iso = now.isoformat()

    def _reset_week(self, now: datetime) -> None:
        self.state.week = EnergyAccumulator()
        self.state.week_start_iso = now.isoformat()
        _LOG.debug("Weekly accumulator reset (Monday)")

    def _reset_month(self, now: datetime) -> None:
        """Snapshot the completed month for the trailing 12 month totals, then clear it."""
        self.state.monthly_export_snapshots = self.state.monthly_export_snapshots[-11:] + [
            round(self.state.month.export_kwh, 3)
        ]
        full_snapshots = self.state.monthly_snapshots[-11:] + [_acc_to_dict(self.state.month)]
        self.state.monthly_snapshots = full_snapshots
        self.state.month = EnergyAccumulator()
        self.state.month_start_iso = now.isoformat()
        _LOG.debug(
            "Monthly accumulator reset (bill day %d) — snapshot saved, %d total",
            self._bill_start_day,
            len(full_snapshots),
        )

    def _reset_year(self, now: datetime) -> None:
        self.state.year = EnergyAccumulator()
        self.state.year_start_iso = now.isoformat()
        _LOG.debug("Yearly accumulator reset (Jan 1)")

    def roll_forward(self, now: datetime) -> bool:
        """
        Apply the midnight resets that passed while Home Assistant was not running.

        Compares the stored last_reset_iso date with today and runs on_midnight once
        for every missed day, so the day, week, bill period and year all reset as
        they would have done live. Also fills empty period start stamps with the
        start of the current period. Returns True when the state changed.
        """
        today = now.date()
        changed = False
        last = _stored_date(self.state.last_reset_iso)
        if last is None:
            self.state.last_reset_iso = _midnight_of(now, today).isoformat()
            changed = True
        else:
            for offset in range(1, (today - last).days + 1):
                self.on_midnight(_midnight_of(now, last + timedelta(days=offset)))
                changed = True
            if changed:
                # The remembered counter readings belong to a day that has ended.
                self.state.counters = CounterMemory()
        return self._fill_period_starts(now) or changed

    def _fill_period_starts(self, now: datetime) -> bool:
        today = now.date()
        state = self.state
        changed = False
        if not state.week_start_iso:
            monday = today - timedelta(days=today.isoweekday() - 1)
            state.week_start_iso = _midnight_of(now, monday).isoformat()
            changed = True
        if not state.month_start_iso:
            if today.day >= self._bill_start_day:
                bill_day = today.replace(day=self._bill_start_day)
            else:
                last_of_previous = today.replace(day=1) - timedelta(days=1)
                bill_day = last_of_previous.replace(day=self._bill_start_day)
            state.month_start_iso = _midnight_of(now, bill_day).isoformat()
            changed = True
        if not state.year_start_iso:
            state.year_start_iso = _midnight_of(now, today.replace(month=1, day=1)).isoformat()
            changed = True
        return changed

    def restore_battery_stats(self, stats) -> None:
        """Restore BatteryStats from persisted state after an HA restart."""
        if self.state.battery_cycles > 0:
            stats.total_cycles = self.state.battery_cycles
        if self.state.last_full_charge_date:
            try:
                stats.last_full_charge_date = date.fromisoformat(self.state.last_full_charge_date)
            except ValueError:
                pass
        if self.state.battery_tracking_start:
            try:
                stats.tracking_start_date = date.fromisoformat(self.state.battery_tracking_start)
                stats.tracking_start_cycles = self.state.battery_tracking_start_cycles
            except ValueError:
                pass

    def save_battery_stats(self, stats) -> None:
        """Persist BatteryStats so it survives HA restarts."""
        self.state.battery_cycles = stats.total_cycles
        self.state.last_full_charge_date = (
            stats.last_full_charge_date.isoformat() if stats.last_full_charge_date else ""
        )
        self.state.battery_tracking_start = (
            stats.tracking_start_date.isoformat() if stats.tracking_start_date else ""
        )
        self.state.battery_tracking_start_cycles = stats.tracking_start_cycles

    def on_charge_decision(self, forecast_kwh: float) -> None:
        """
        Record the forecast kWh from the first charge decision of the day.

        It feeds the "Solar forecast today" sensor. Forecast accuracy does not use it,
        because it can be blended toward the P10 or belong to another day.
        """
        if self.state.today_forecast_kwh == 0.0 and forecast_kwh > 0:
            self.state.today_forecast_kwh = forecast_kwh
            _LOG.debug("Today's solar forecast recorded: %.1fkWh", forecast_kwh)

    def on_raw_forecast(self, forecast_kwh: float | None, p10_kwh: float | None = None) -> None:
        """Remember the latest raw "tomorrow" forecasts (P50 and P10) from the forecast sensors.

        The values seen last before midnight are the forecasts for the day that starts.
        """
        if forecast_kwh is not None and forecast_kwh > 0:
            self.state.pending_raw_forecast_kwh = forecast_kwh
        if p10_kwh is not None and p10_kwh > 0:
            self.state.pending_raw_forecast_p10_kwh = p10_kwh

    def seed_forecast_history(self, records: list[dict]) -> None:
        """Fill an empty forecast history with days rebuilt from the recorder.

        Does nothing once the history holds a day, so a night recorded in the meantime is
        never overwritten.
        """
        if self.state.forecast_ratio_history:
            return
        self.state.forecast_ratio_history = [
            dict(r) for r in records[-_FORECAST_RATIO_HISTORY_DAYS:]
        ]

    @property
    def immersion_heating_rates(self) -> list[float]:
        return self.state.immersion_heating_rates

    @property
    def immersion_heat_log(self) -> ImmersionHeatLog:
        return self.state.immersion_heat_log

    def record_immersion_rate(self, rate_c_per_h: float) -> None:
        """Keep the heating rate of a finished immersion run and queue a save."""
        self.state.immersion_heating_rates = keep_run(
            self.state.immersion_heating_rates, rate_c_per_h
        )
        self.schedule_save()

    def note_clipping(self) -> None:
        """Flag today as clipping so it is left out of the forecast correction."""
        self.state.today_clipping = True

    def _record_forecast_ratio(self) -> None:
        if self.state.today_raw_forecast_kwh <= 0:
            return
        record = {
            "forecast": self.state.today_raw_forecast_kwh,
            "actual": self.state.today.solar_kwh,
            "clipped": self.state.today_clipping,
        }
        self.state.forecast_ratio_history = (
            self.state.forecast_ratio_history[-(_FORECAST_RATIO_HISTORY_DAYS - 1) :] + [record]
        )

    def record_slot_load(self, now: datetime, slot: int, kwh: float, hours: float) -> None:
        """Add baseline house load for the 30-minute slot containing now.

        Intervals longer than one slot are ignored (HA downtime or a stalled update).
        A new calendar day archives whatever the previous day collected.
        """
        if not 0 < hours <= _SLOT_HOURS or not 0 <= slot < _SLOTS_PER_DAY:
            return
        day = now.date().isoformat()
        if self.state.slot_load_date != day:
            if self.state.slot_load_date:
                self._archive_slot_day()
            self.state.slot_load_date = day
        self.state.slot_load_today[slot] += kwh
        self.state.slot_hours_today[slot] += hours

    def _archive_slot_day(self) -> None:
        """Move today's slot data into history with its coverage, then clear it."""
        hours = self.state.slot_hours_today
        if self.state.slot_load_date and sum(hours) > 0:
            coverage = sum(min(h, _SLOT_HOURS) for h in hours) / 24
            entry = {
                "date": self.state.slot_load_date,
                "slots": [round(v, 5) for v in self.state.slot_load_today],
                "coverage": round(coverage, 3),
            }
            self.state.slot_load_history = (
                self.state.slot_load_history[-(_SLOT_HISTORY_DAYS - 1) :] + [entry]
            )
        self.state.slot_load_today = [0.0] * _SLOTS_PER_DAY
        self.state.slot_hours_today = [0.0] * _SLOTS_PER_DAY
        self.state.slot_load_date = ""

    def update_bill_start_day(self, bill_start_day: int) -> None:
        """Update the bill start day (called when config changes via options flow)."""
        self._bill_start_day = bill_start_day


# ── Serialisation (module-level for testability) ──────────────────────────────


def _serialize(state: AccumulationState) -> dict:
    payload = _serialize_state(state)
    if state.immersion_heat_log.days:
        payload[_HEAT_LOG_KEY] = state.immersion_heat_log.to_storage()
    return payload


def _serialize_state(state: AccumulationState) -> dict:
    return {
        "version": _STORAGE_VERSION,
        "today": _acc_to_dict(state.today),
        "week": _acc_to_dict(state.week),
        "month": _acc_to_dict(state.month),
        "year": _acc_to_dict(state.year),
        "yesterday": _acc_to_dict(state.yesterday),
        "ac_charge_counter_kwh": state.counters.ac_charge_kwh,
        "today_forecast_kwh": state.today_forecast_kwh,
        "battery_cycles": state.battery_cycles,
        "last_full_charge_date": state.last_full_charge_date,
        "battery_tracking_start": state.battery_tracking_start,
        "battery_tracking_start_cycles": state.battery_tracking_start_cycles,
        "register_write_count": state.register_write_count,
        "register_write_log": [dict(e) for e in state.register_write_log],
        "yesterday_forecast_accuracy_pct": state.yesterday_forecast_accuracy_pct,
        "forecast_accuracy_history": list(state.forecast_accuracy_history),
        "pending_raw_forecast_kwh": state.pending_raw_forecast_kwh,
        "today_raw_forecast_kwh": state.today_raw_forecast_kwh,
        "pending_raw_forecast_p10_kwh": state.pending_raw_forecast_p10_kwh,
        "today_raw_forecast_p10_kwh": state.today_raw_forecast_p10_kwh,
        "today_clipping": state.today_clipping,
        "forecast_ratio_history": [dict(r) for r in state.forecast_ratio_history],
        "slot_load_today": list(state.slot_load_today),
        "slot_hours_today": list(state.slot_hours_today),
        "slot_load_date": state.slot_load_date,
        "slot_load_history": [dict(e) for e in state.slot_load_history],
        "week_start_iso": state.week_start_iso,
        "month_start_iso": state.month_start_iso,
        "year_start_iso": state.year_start_iso,
        "last_reset_iso": state.last_reset_iso,
        "immersion_heating_rates": list(state.immersion_heating_rates),
        "monthly_export_snapshots": list(state.monthly_export_snapshots),
        "monthly_snapshots": list(state.monthly_snapshots),
    }


def _restore_accumulators(state: AccumulationState, data: dict) -> None:
    state.today = _dict_to_acc(data.get("today", {}))
    state.week = _dict_to_acc(data.get("week", {}))
    state.month = _dict_to_acc(data.get("month", {}))
    state.year = _dict_to_acc(data.get("year", {}))
    state.yesterday = _dict_to_acc(data.get("yesterday", {}))


def _restore_battery_and_forecast(state: AccumulationState, data: dict) -> None:
    state.counters = CounterMemory(float(data.get("ac_charge_counter_kwh", 0.0)))
    state.today_forecast_kwh = float(data.get("today_forecast_kwh", 0.0))
    state.battery_cycles = float(data.get("battery_cycles", 0.0))
    state.last_full_charge_date = str(data.get("last_full_charge_date", ""))
    state.battery_tracking_start = str(data.get("battery_tracking_start", ""))
    state.battery_tracking_start_cycles = float(data.get("battery_tracking_start_cycles", 0.0))
    state.register_write_count = _as_count(data.get("register_write_count", 0))
    state.register_write_log = restore_entries(
        data.get("register_write_log"), REGISTER_WRITE_LOG_MAX_ENTRIES
    )
    state.yesterday_forecast_accuracy_pct = float(data.get("yesterday_forecast_accuracy_pct", 0.0))
    state.forecast_accuracy_history = [float(x) for x in data.get("forecast_accuracy_history", [])]
    state.pending_raw_forecast_kwh = float(data.get("pending_raw_forecast_kwh", 0.0))
    state.today_raw_forecast_kwh = float(data.get("today_raw_forecast_kwh", 0.0))
    state.pending_raw_forecast_p10_kwh = float(data.get("pending_raw_forecast_p10_kwh", 0.0))
    state.today_raw_forecast_p10_kwh = float(data.get("today_raw_forecast_p10_kwh", 0.0))
    state.today_clipping = bool(data.get("today_clipping", False))
    state.forecast_ratio_history = [
        dict(r) for r in data.get("forecast_ratio_history", []) if isinstance(r, dict)
    ]


def _restore_slot_load(state: AccumulationState, data: dict) -> None:
    state.slot_load_history = [
        dict(e) for e in data.get("slot_load_history", []) if isinstance(e, dict)
    ]
    state.slot_load_date = str(data.get("slot_load_date", ""))
    for key in ("slot_load_today", "slot_hours_today"):
        values = data.get(key)
        if isinstance(values, list) and len(values) == _SLOTS_PER_DAY:
            setattr(state, key, [float(v) for v in values])


def _restore_immersion_rates(state: AccumulationState, data: dict) -> None:
    rates = data.get("immersion_heating_rates", [])
    state.immersion_heating_rates = [
        float(r) for r in rates if isinstance(r, (int, float)) and r > 0
    ]


def _restore_heat_log(state: AccumulationState, data: dict) -> None:
    state.immersion_heat_log = ImmersionHeatLog.from_storage(data.get(_HEAT_LOG_KEY))


def _restore_period_history(state: AccumulationState, data: dict) -> None:
    state.week_start_iso = data.get("week_start_iso", "")
    state.month_start_iso = data.get("month_start_iso", "")
    state.year_start_iso = data.get("year_start_iso", "")
    state.last_reset_iso = data.get("last_reset_iso", "")
    state.monthly_export_snapshots = [
        float(x) for x in data.get("monthly_export_snapshots", [])
    ]
    state.monthly_snapshots = [
        dict(entry) for entry in data.get("monthly_snapshots", [])
        if isinstance(entry, dict)
    ]


def _deserialize(data: dict) -> AccumulationState:
    state = AccumulationState()
    _restore_accumulators(state, data)
    _restore_battery_and_forecast(state, data)
    _restore_slot_load(state, data)
    _restore_immersion_rates(state, data)
    _restore_heat_log(state, data)
    _restore_period_history(state, data)
    return state
