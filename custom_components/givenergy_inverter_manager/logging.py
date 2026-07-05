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

from .const import CONF_VERBOSE_LOGGING, DEFAULT_VERBOSE_LOGGING

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

    def isEnabledFor(self, level: int) -> bool:
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
# individually and called without a logger instance.

def log_startup(log: GivLogger, cfg: dict) -> None:
    """
    Log all configured entity IDs at startup.

    Called once from async_setup_entry after first coordinator refresh.
    """
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
        DEFAULT_BASE_RATE,
        DEFAULT_BASE_RATE_NAME,
        DEFAULT_RATE_PERIODS,
    )

    lines = ["── Startup entity configuration ────────────────────────────────"]
    lines.append("  SENSOR ENTITIES (reads)")
    for label, key in [
        ("solar_power",   CONF_SOLAR_POWER),
        ("battery_soc",   CONF_BATTERY_SOC),
        ("battery_power", CONF_BATTERY_POWER),
        ("grid_power",    CONF_GRID_POWER),
        ("house_load",    CONF_HOUSE_LOAD),
        ("immersion_sw",  CONF_IMMERSION_SWITCH),
        ("immersion_tmp", CONF_IMMERSION_TEMP_SENSOR),
        ("forecast",      CONF_FORECAST_ENTITY),
    ]:
        val = cfg.get(key)
        lines.append(f"    {label:<14} {val or '(not configured)'}")

    lines.append("  GIVTCP CONTROL ENTITIES (writes)")
    for label, key in [
        ("target_soc",    CONF_TARGET_SOC_ENTITY),
        ("enable_tgt",    CONF_ENABLE_CHARGE_TARGET),
        ("enable_sched",  CONF_ENABLE_CHARGE_SCHEDULE),
        ("charge_start",  CONF_CHARGE_START_TIME_ENTITY),
        ("charge_end",    CONF_CHARGE_END_TIME_ENTITY),
    ]:
        val = cfg.get(key)
        lines.append(
            f"    {label:<14} {val or '(not configured — write-back disabled)'}"
        )

    lines.append("  TARIFF")
    base_rate = cfg.get(CONF_BASE_RATE, DEFAULT_BASE_RATE)
    base_name = cfg.get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)
    lines.append(f"    base_rate      {base_name!r} = {base_rate:.4f} €/kWh")
    for p in cfg.get(CONF_RATE_PERIODS, DEFAULT_RATE_PERIODS):
        lines.append(
            f"    timed          {p.get('name', '?'):<12} {p.get('rate', 0):.4f}"
            f"  {p.get('start', '?')} – {p.get('end', '?')}"
        )
    lines.append("── end startup config ──────────────────────────────────────────")

    log.verbose_block(lines)


def log_cycle(log: GivLogger, cycle: int, raw: object, data: object, now: object) -> None:
    """
    Log one structured block for a completed 30-second update cycle.

    Builds and emits nothing when verbose is off.
    """
    cd = data.charge_decision
    acc = data.today

    lines = [
        f"── Cycle {cycle} @ {now.strftime('%H:%M:%S')} ─────────────────────────────────────────",
        (
            f"  RAW SENSORS  solar={raw.solar_power_w:+.0f}W"
            f"  batt_soc={raw.battery_soc:.1f}%"
            f"  batt_power={raw.battery_power_w:+.0f}W"
            f"  grid={raw.grid_power_w:+.0f}W"
            f"  house={raw.house_load_w:.0f}W"
        ),
    ]

    if raw.ev_power_w > 0 or raw.ev_plugged_in:
        lines.append(
            f"  EV RAW        plugged={raw.ev_plugged_in}  power={raw.ev_power_w:.0f}W"
        )
    if raw.immersion_on or raw.immersion_temp is not None:
        temp_str = f"{raw.immersion_temp:.1f}°C" if raw.immersion_temp is not None else "unknown"
        lines.append(
            f"  IMMERSION RAW on={raw.immersion_on}"
            f"  wattage={raw.immersion_wattage_w:.0f}W"
            f"  temp={temp_str}"
        )
    if raw.forecast_kwh_tomorrow is not None:
        lines.append(f"  FORECAST      tomorrow={raw.forecast_kwh_tomorrow:.1f} kWh")

    lines.append(
        f"  LOADS         immersion={data.immersion_load_w:.0f}W"
        f"  rest_of_house={data.rest_of_house_w:.0f}W"
        f"  clipping={data.is_clipping}"
    )
    lines.append(
        f"  TARIFF        period={data.current_rate_name!r}"
        f"  rate={data.current_rate:.4f} {data.currency_symbol}/kWh"
    )

    if cd is not None:
        lines.append(
            f"  CHARGE        target={cd.target_soc}%"
            f"  skip={cd.skip_charge}"
            f"  reason={cd.reason!r}"
        )
        if cd.cost_to_charge > 0:
            lines.append(
                f"  CHARGE COST   estimated={cd.cost_to_charge:.3f} {data.currency_symbol}"
            )
    else:
        lines.append("  CHARGE        no decision yet")

    lines.append(
        f"  IMMERSION     divert={data.should_divert_immersion}"
        f"  reason={data.divert_reason!r}"
    )

    if data.ev_available:
        ev_state = data.ev_charger_state.value if data.ev_charger_state else "unknown"
        lines.append(
            f"  EV CHARGER    {data.ev_charger_name}"
            f"  state={ev_state}"
            f"  power={data.ev_power_w:.0f}W"
            f"  draining={data.ev_draining_battery}"
        )
        if data.ev_protection_reason:
            lines.append(f"  EV PROTECTION {data.ev_protection_reason!r}")
    else:
        lines.append("  EV CHARGER    not discovered")

    lines += [
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

    if data.dry_run:
        lines.append(f"  DRY RUN       ACTIVE — last skipped: {data.dry_run_last_skipped!r}")

    lines.append(f"── end cycle {cycle} ──────────────────────────────────────────────────")

    log.verbose_block(lines)


def log_givtcp_write(
    log: GivLogger,
    step: int,
    entity_id: str,
    value: object,
    read_back: object,
    accepted: bool,
) -> None:
    """Log one step of the GivTCP charge write-back sequence."""
    status = "✓ accepted" if accepted else "✗ MISMATCH — wrote but read back different value"
    log.verbose(
        "  GIVTCP WRITE  step=%d  entity=%s  wrote=%r  read_back=%r  %s",
        step, entity_id, value, read_back, status,
    )
