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
from datetime import datetime
from typing import TYPE_CHECKING

from .core.tariff import EnergyAccumulator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOG = logging.getLogger(__name__)
_STORAGE_KEY = "givenergy_inverter_manager.energy"
_STORAGE_VERSION = 1
_FORECAST_HISTORY_DAYS = 7


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
        "import_kwh_cheap": acc.import_kwh_cheap,
        "import_kwh_peak": acc.import_kwh_peak,
        "import_cost_cheap": acc.import_cost_cheap,
        "import_cost_peak": acc.import_cost_peak,
        "import_cost_by_period": dict(acc.import_cost_by_period),
        "export_earnings": acc.export_earnings,
        "zappi_cost": acc.zappi_cost,
        "immersion_cost": acc.immersion_cost,
        "house_cost": acc.house_cost,
        "immersion_solar_kwh": acc.immersion_solar_kwh,
        "immersion_savings": acc.immersion_savings,
        "battery_throughput_kwh": acc.battery_throughput_kwh,
    }


def _dict_to_acc(d: dict) -> EnergyAccumulator:
    """Deserialise a dict back into an EnergyAccumulator."""
    acc = EnergyAccumulator()
    for key, value in d.items():
        if hasattr(acc, key):
            setattr(acc, key, value)
    return acc


# ── Public state dataclass ────────────────────────────────────────────────────


@dataclass
class AccumulationState:
    """All accumulated energy state across time periods."""

    today: EnergyAccumulator = field(default_factory=EnergyAccumulator)
    week: EnergyAccumulator = field(default_factory=EnergyAccumulator)
    month: EnergyAccumulator = field(default_factory=EnergyAccumulator)
    yesterday: EnergyAccumulator = field(default_factory=EnergyAccumulator)

    # Forecast accuracy — recorded at midnight from the previous charge decision
    today_forecast_kwh: float = 0.0
    yesterday_forecast_accuracy_pct: float = 0.0
    forecast_accuracy_history: list = field(default_factory=list)  # last 7 days

    # Reset timestamps (ISO strings for JSON serialisation)
    week_start_iso: str = ""
    month_start_iso: str = ""
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
        from homeassistant.helpers.storage import Store  # lazy — not available in test env

        self._store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
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
    def yesterday(self) -> EnergyAccumulator:
        return self.state.yesterday

    @property
    def today_forecast_kwh(self) -> float:
        return self.state.today_forecast_kwh

    @property
    def yesterday_forecast_accuracy_pct(self) -> float:
        return self.state.yesterday_forecast_accuracy_pct

    @property
    def forecast_accuracy_7day_avg_pct(self) -> float:
        """Rolling 7-day average forecast accuracy (0 if no history)."""
        h = self.state.forecast_accuracy_history
        return round(sum(h) / len(h), 1) if h else 0.0

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
        """
        today_date = now.date()

        # 1. Snapshot
        self.state.yesterday = self.state.today

        # 2. Forecast accuracy for the completed day
        if self.state.today_forecast_kwh > 0:
            actual = self.state.today.solar_kwh
            accuracy = min(200.0, round(actual / self.state.today_forecast_kwh * 100, 1))
            self.state.yesterday_forecast_accuracy_pct = accuracy
            history = self.state.forecast_accuracy_history[-(_FORECAST_HISTORY_DAYS - 1) :]
            history.append(accuracy)
            self.state.forecast_accuracy_history = history
            _LOG.debug(
                "Forecast accuracy for completed day: %.1f%% (forecast %.1fkWh, actual %.1fkWh)",
                accuracy,
                self.state.today_forecast_kwh,
                actual,
            )

        # 3. Reset today
        self.state.today = EnergyAccumulator()
        self.state.today_forecast_kwh = 0.0
        self.state.last_reset_iso = now.isoformat()

        # 4. Weekly reset on Monday
        if today_date.isoweekday() == 1:
            self.state.week = EnergyAccumulator()
            self.state.week_start_iso = now.isoformat()
            _LOG.debug("Weekly accumulator reset (Monday)")

        # 5. Monthly reset on bill start day
        if today_date.day == self._bill_start_day:
            self.state.month = EnergyAccumulator()
            self.state.month_start_iso = now.isoformat()
            _LOG.debug("Monthly accumulator reset (bill day %d)", self._bill_start_day)

    def on_charge_decision(self, forecast_kwh: float) -> None:
        """
        Record the forecast kWh from tonight's charge decision.

        Called once per day when the charge decision is first made.
        The forecast is compared against actual solar at the next midnight
        to produce the accuracy metric.
        """
        if self.state.today_forecast_kwh == 0.0 and forecast_kwh > 0:
            self.state.today_forecast_kwh = forecast_kwh
            _LOG.debug("Today's solar forecast recorded: %.1fkWh", forecast_kwh)

    def update_bill_start_day(self, bill_start_day: int) -> None:
        """Update the bill start day (called when config changes via options flow)."""
        self._bill_start_day = bill_start_day


# ── Serialisation (module-level for testability) ──────────────────────────────


def _serialize(state: AccumulationState) -> dict:
    return {
        "version": _STORAGE_VERSION,
        "today": _acc_to_dict(state.today),
        "week": _acc_to_dict(state.week),
        "month": _acc_to_dict(state.month),
        "yesterday": _acc_to_dict(state.yesterday),
        "today_forecast_kwh": state.today_forecast_kwh,
        "yesterday_forecast_accuracy_pct": state.yesterday_forecast_accuracy_pct,
        "forecast_accuracy_history": list(state.forecast_accuracy_history),
        "week_start_iso": state.week_start_iso,
        "month_start_iso": state.month_start_iso,
        "last_reset_iso": state.last_reset_iso,
    }


def _deserialize(data: dict) -> AccumulationState:
    state = AccumulationState()
    state.today = _dict_to_acc(data.get("today", {}))
    state.week = _dict_to_acc(data.get("week", {}))
    state.month = _dict_to_acc(data.get("month", {}))
    state.yesterday = _dict_to_acc(data.get("yesterday", {}))
    state.today_forecast_kwh = float(data.get("today_forecast_kwh", 0.0))
    state.yesterday_forecast_accuracy_pct = float(data.get("yesterday_forecast_accuracy_pct", 0.0))
    state.forecast_accuracy_history = [float(x) for x in data.get("forecast_accuracy_history", [])]
    state.week_start_iso = data.get("week_start_iso", "")
    state.month_start_iso = data.get("month_start_iso", "")
    state.last_reset_iso = data.get("last_reset_iso", "")
    return state
