"""
logging.py — Logger for GivEnergy Inverter Manager.

Provides one logger for the entire integration and owns the verbose-mode
decision.  All other modules import from here instead of calling
logging.getLogger(__name__) individually.

Usage in other modules
──────────────────────
    from .logging import get_logger
    _LOG = get_logger(__name__)

    _LOG.info("Something happened")
    _LOG.debug("Low-level detail")
    _LOG.verbose("Per-cycle sensor dump: %s", data)   # only emits when verbose ON

The .verbose() method is identical to .debug() except it is gated by
the integration's CONF_VERBOSE_LOGGING config option.  Callers do not
need to check the flag themselves.

Verbose mode
────────────
Set via Settings → Integrations → GivEnergy Inverter Manager → Configure.
Takes effect on the next 30-second cycle — no restart needed because the
coordinator reads _effective_cfg() each cycle.

The coordinator registers the config accessor once on startup:
    from .logging import GivLogger
    GivLogger.register(self._effective_cfg)

After that, every GivLogger instance created anywhere in the integration
reads the flag from the same live config.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from .const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_CHARGE_END_TIME_ENTITY,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_ENABLE_CHARGE_SCHEDULE,
    CONF_ENABLE_CHARGE_TARGET,
    CONF_FORECAST_ENTITY,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    CONF_RATE_PERIODS,
    CONF_SOLAR_POWER,
    CONF_TARGET_SOC_ENTITY,
    CONF_VERBOSE_LOGGING,
    DEFAULT_BASE_RATE,
    DEFAULT_BASE_RATE_NAME,
    DEFAULT_RATE_PERIODS,
    DEFAULT_VERBOSE_LOGGING,
)

if TYPE_CHECKING:
    from .core.engine import CoordinatorData, RawSensorValues

# The single integration-level logger name.
_ROOT = "custom_components.givenergy_inverter_manager"


class GivLogger:
    """
    Thin wrapper around a standard Python logger that adds .verbose().

    One GivLogger is created per module (matching stdlib convention) but
    they all share a single config accessor registered by the coordinator.
    """

    # Class-level accessor, set by the coordinator on startup.
    # Returns the merged cfg dict (entry.data | entry.options).
    # NOTE: class-level means a second coordinator (e.g. during reload)
    # will overwrite this — acceptable for a single-entry integration.
    _cfg_fn: Callable[[], dict] | None = None

    @classmethod
    def register(cls, cfg_fn: Callable[[], dict]) -> None:
        """
        Register the config accessor.

        Call this once from async_setup_entry (or the coordinator __init__)
        after the config entry is available.  All GivLogger instances
        created before or after this call will use it.
        """
        cls._cfg_fn = cfg_fn

    @classmethod
    def _verbose_enabled(cls) -> bool:
        """Return True if CONF_VERBOSE_LOGGING is set in the live config."""
        if cls._cfg_fn is None:
            return False
        try:
            return bool(cls._cfg_fn().get(CONF_VERBOSE_LOGGING, DEFAULT_VERBOSE_LOGGING))
        except Exception:
            return False

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    # ── Standard levels (direct pass-through) ────────────────────────────────

    def debug(self, msg: str, *args: object, **kwargs: object) -> None:
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args: object, **kwargs: object) -> None:
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: object, **kwargs: object) -> None:
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: object, **kwargs: object) -> None:
        self._logger.error(msg, *args, **kwargs)

    def exception(self, msg: str, *args: object, **kwargs: object) -> None:
        self._logger.exception(msg, *args, **kwargs)

    # ── Verbose level ─────────────────────────────────────────────────────────

    def verbose(self, msg: str, *args: object, **kwargs: object) -> None:
        """
        Emit msg at DEBUG level, but only when CONF_VERBOSE_LOGGING is True.

        This is the correct place to put per-cycle diagnostics, sensor dumps,
        and GivTCP write-back details that would flood the log during normal
        operation.
        """
        if self._verbose_enabled():
            self._logger.debug(msg, *args, **kwargs)

    def is_verbose(self) -> bool:
        """True when verbose logging is on. Callers check it before building log text."""
        return self._verbose_enabled()

    def verbose_block(self, lines: list[str]) -> None:
        """
        Emit multiple lines as a single verbose block.

        More efficient than calling verbose() per line — does the enabled
        check once and avoids building the joined string if verbose is off.
        """
        if self._verbose_enabled():
            for line in lines:
                self._logger.debug(line)

    # ── Convenience ──────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self._logger.name

    def is_enabled_for(self, level: int) -> bool:
        return self._logger.isEnabledFor(level)


def get_logger(name: str) -> GivLogger:
    """
    Return a GivLogger for the given module name.

    Drop-in replacement for logging.getLogger(__name__) across the integration.

    Example:
        from .logging import get_logger
        _LOG = get_logger(__name__)
    """
    return GivLogger(name)


# ── Verbose log helpers ───────────────────────────────────────────────────────
# These are module-level functions rather than methods so they can be imported
# individually and called without a logger instance. Each public one checks
# is_verbose() first, so nothing is formatted while verbose logging is off.

_SENSOR_ENTITIES = (
    ("solar_power", CONF_SOLAR_POWER),
    ("battery_soc", CONF_BATTERY_SOC),
    ("battery_power", CONF_BATTERY_POWER),
    ("grid_power", CONF_GRID_POWER),
    ("house_load", CONF_HOUSE_LOAD),
    ("immersion_sw", CONF_IMMERSION_SWITCH),
    ("immersion_tmp", CONF_IMMERSION_TEMP_SENSOR),
    ("forecast", CONF_FORECAST_ENTITY),
)

_CONTROL_ENTITIES = (
    ("target_soc", CONF_TARGET_SOC_ENTITY),
    ("enable_tgt", CONF_ENABLE_CHARGE_TARGET),
    ("enable_sched", CONF_ENABLE_CHARGE_SCHEDULE),
    ("charge_start", CONF_CHARGE_START_TIME_ENTITY),
    ("charge_end", CONF_CHARGE_END_TIME_ENTITY),
)


def log_startup(log: GivLogger, cfg: dict) -> None:
    """
    Log all configured entity IDs at startup.

    Called once from async_setup_entry after first coordinator refresh.
    """
    if not log.is_verbose():
        return
    log.verbose_block(
        [
            "── Startup entity configuration ────────────────────────────────",
            "  SENSOR ENTITIES (reads)",
            *_entity_lines(cfg, _SENSOR_ENTITIES, "(not configured)"),
            "  GIVTCP CONTROL ENTITIES (writes)",
            *_entity_lines(cfg, _CONTROL_ENTITIES, "(not configured — write-back disabled)"),
            "  TARIFF",
            *_tariff_lines(cfg),
            "── end startup config ──────────────────────────────────────────",
        ]
    )


def _entity_lines(cfg: dict, entities: tuple, missing: str) -> list[str]:
    return [f"    {label:<14} {cfg.get(key) or missing}" for label, key in entities]


def _tariff_lines(cfg: dict) -> list[str]:
    base_rate = cfg.get(CONF_BASE_RATE, DEFAULT_BASE_RATE)
    base_name = cfg.get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)
    lines = [f"    base_rate      {base_name!r} = {base_rate:.4f} €/kWh"]
    for p in cfg.get(CONF_RATE_PERIODS, DEFAULT_RATE_PERIODS):
        lines.append(
            f"    timed          {p.get('name', '?'):<12} {p.get('rate', 0):.4f}"
            f"  {p.get('start', '?')} – {p.get('end', '?')}"
        )
    return lines


@dataclass(frozen=True)
class CycleSnapshot:
    """One completed update cycle: what was read and what the engine decided."""

    cycle: int
    now: datetime
    raw: RawSensorValues
    data: CoordinatorData


def log_cycle(log: GivLogger, snapshot: CycleSnapshot) -> None:
    """
    Log one structured block for a completed 30-second update cycle.

    Builds and emits nothing when verbose is off.
    """
    if not log.is_verbose():
        return
    log.verbose_block(_cycle_lines(snapshot))


def _cycle_lines(snapshot: CycleSnapshot) -> list[str]:
    raw, data = snapshot.raw, snapshot.data
    return [
        *_cycle_header_lines(snapshot),
        *_raw_extra_lines(raw),
        *_load_and_tariff_lines(data),
        *_charge_lines(data),
        f"  IMMERSION     divert={data.should_divert_immersion}  reason={data.divert_reason!r}",
        *_ev_lines(data),
        *_today_lines(data),
        *_bill_and_night_lines(data),
        *_dry_run_lines(data),
        f"── end cycle {snapshot.cycle} ──────────────────────────────────────────────────",
    ]


def _cycle_header_lines(snapshot: CycleSnapshot) -> list[str]:
    raw = snapshot.raw
    stamp = snapshot.now.strftime("%H:%M:%S")
    return [
        f"── Cycle {snapshot.cycle} @ {stamp} ─────────────────────────────────────────",
        (
            f"  RAW SENSORS  solar={raw.solar_power_w:+.0f}W"
            f"  batt_soc={raw.battery_soc:.1f}%"
            f"  batt_power={raw.battery_power_w:+.0f}W"
            f"  grid={raw.grid_power_w:+.0f}W"
            f"  house={raw.house_load_w:.0f}W"
        ),
    ]


def _raw_extra_lines(raw: RawSensorValues) -> list[str]:
    """The optional raw readings: EV, immersion and forecast, each only when present."""
    lines = []
    if raw.ev_power_w > 0 or raw.ev_plugged_in:
        lines.append(f"  EV RAW        plugged={raw.ev_plugged_in}  power={raw.ev_power_w:.0f}W")
    if raw.immersion_on or raw.immersion_temp is not None:
        temp_str = f"{raw.immersion_temp:.1f}°C" if raw.immersion_temp is not None else "unknown"
        lines.append(
            f"  IMMERSION RAW on={raw.immersion_on}"
            f"  wattage={raw.immersion_wattage_w:.0f}W"
            f"  temp={temp_str}"
        )
    if raw.forecast_kwh_tomorrow is not None:
        lines.append(f"  FORECAST      tomorrow={raw.forecast_kwh_tomorrow:.1f} kWh")
    return lines


def _load_and_tariff_lines(data: CoordinatorData) -> list[str]:
    return [
        (
            f"  LOADS         immersion={data.immersion_load_w:.0f}W"
            f"  rest_of_house={data.rest_of_house_w:.0f}W"
            f"  clipping={data.is_clipping}"
        ),
        (
            f"  TARIFF        period={data.current_rate_name!r}"
            f"  rate={data.current_rate:.4f} {data.currency_symbol}/kWh"
        ),
    ]


def _charge_lines(data: CoordinatorData) -> list[str]:
    cd = data.charge_decision
    if cd is None:
        return ["  CHARGE        no decision yet"]
    lines = [
        f"  CHARGE        target={cd.target_soc}%  skip={cd.skip_charge}  reason={cd.reason!r}"
    ]
    if cd.cost_to_charge > 0:
        lines.append(f"  CHARGE COST   estimated={cd.cost_to_charge:.3f} {data.currency_symbol}")
    return lines


def _ev_lines(data: CoordinatorData) -> list[str]:
    if not data.ev_available:
        return ["  EV CHARGER    not discovered"]
    ev_state = data.ev_charger_state.value if data.ev_charger_state else "unknown"
    lines = [
        f"  EV CHARGER    {data.ev_charger_name}"
        f"  state={ev_state}"
        f"  power={data.ev_power_w:.0f}W"
        f"  draining={data.ev_draining_battery}"
    ]
    if data.ev_protection_reason:
        lines.append(f"  EV MODE       {data.ev_protection_reason!r}")
    return lines


def _today_lines(data: CoordinatorData) -> list[str]:
    acc = data.today
    return [
        (
            f"  TODAY kWh     solar={acc.solar_kwh:.3f}"
            f"  import={acc.import_kwh:.3f}"
            f"  export={acc.export_kwh:.3f}"
            f"  zappi={acc.zappi_kwh:.3f}"
            f"  immersion={acc.immersion_kwh:.3f}"
            f"  batt_discharge={acc.battery_discharge_kwh:.3f}"
        ),
        (
            f"  TODAY COST    import={acc.total_import_cost:.4f}"
            f"  export_earn={acc.export_earnings:.4f}"
            f"  zappi={acc.zappi_cost:.4f}"
            f"  immersion={acc.immersion_cost:.4f}"
            f"  house={acc.house_cost:.4f}"
            f"  {data.currency_symbol}"
        ),
        (
            f"  SELF-SUFFIC.  sufficiency={acc.self_sufficiency_pct:.1f}%"
            f"  consumption={acc.self_consumption_pct:.1f}%"
        ),
    ]


def _bill_and_night_lines(data: CoordinatorData) -> list[str]:
    return [
        (
            f"  BILL          accrued={data.accrued_bill:.2f}"
            f"  projected={data.projected_bill:.2f}"
            f"  days_remaining={data.days_remaining}"
            f"  {data.currency_symbol}"
        ),
        (
            f"  NIGHT         survive={data.will_survive_night}"
            f"  soc_at_sunrise={data.estimated_soc_at_sunrise:.1f}%"
            f"  reason={data.survival_reason!r}"
        ),
    ]


def _dry_run_lines(data: CoordinatorData) -> list[str]:
    if not data.dry_run:
        return []
    return [f"  DRY RUN       ACTIVE — last skipped: {data.dry_run_last_skipped!r}"]


@dataclass(frozen=True)
class WriteOutcome:
    """One GivTCP write and what the entity read back afterwards."""

    step: int
    entity_id: str
    wrote: object
    read_back: object
    accepted: bool


def log_givtcp_write(log: GivLogger, outcome: WriteOutcome) -> None:
    """Log one step of the GivTCP charge write-back sequence."""
    if not log.is_verbose():
        return
    mismatch = "✗ MISMATCH — wrote but read back different value"
    status = "✓ accepted" if outcome.accepted else mismatch
    log.verbose(
        "  GIVTCP WRITE  step=%d  entity=%s  wrote=%r  read_back=%r  %s",
        outcome.step,
        outcome.entity_id,
        outcome.wrote,
        outcome.read_back,
        status,
    )
