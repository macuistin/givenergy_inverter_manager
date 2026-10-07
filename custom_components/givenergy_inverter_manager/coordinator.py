"""
coordinator.py — Thin HA proxy coordinator for GivEnergy Inverter Manager.

This file contains ONLY Home Assistant-dependent code:
  1. Reading entity states from hass.states
  2. Registering time listeners (midnight reset, cheap-rate start)
  3. Calling HA services (EV charger mode changes, immersion switch,
     charge target write-back to GivTCP)
  4. Wiring the DataUpdateCoordinator lifecycle

All decision logic lives in engine.py, which is pure Python and fully
unit-testable without a running HA instance.

HA surface proxied through three methods
─────────────────────────────────────────
All access to Home Assistant goes through three coordinator methods:

  _get_state(entity_id)           wraps hass.states.get()
  _call_service(domain, service, data)
                                  wraps hass.services.async_call()
  _create_task(coro)              wraps entry.async_create_task()

No other method in this class touches hass directly. This means tests
can subclass GivEnergyCoordinator and override just these three methods
to fully control the HA surface without mocking the entire hass object.

Charge target write-back
────────────────────────
The integration calculates an overnight charge target every 30 seconds
(engine.build_coordinator_data → calculate_overnight_charge_target) but
to be effective this must be written to number.givtcp_{SERIAL}_target_soc
once at the start of the cheap rate window. We register a time listener
at __init__ that fires at the cheapest-rate-period start time, reads the
current charge decision, and calls number.set_value on the GivTCP entity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .accumulation import AccumulationStore
from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_CARBON_INTENSITY_ENTITY,
    CONF_CHARGE_END_TIME_ENTITY,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_CHEAP_RATE_FLOOR_SOC,
    CONF_DRY_RUN,
    CONF_ENABLE_CHARGE_SCHEDULE,
    CONF_ENABLE_CHARGE_TARGET,
    CONF_EXPORT_RATE,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_D2,
    CONF_FORECAST_ENTITY_P10,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_IMMERSION_HYSTERESIS,
    CONF_IMMERSION_MIN_TEMP,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TARGET_TEMP,
    CONF_IMMERSION_TEMP_SENSOR,
    CONF_IMMERSION_WATTAGE,
    CONF_INVERTER_MAX_OUTPUT,
    CONF_INVERTER_SERIAL,
    CONF_INVERTER_TEMP_ENTITY,
    CONF_SOLAR_POWER,
    CONF_TARGET_SOC_ENTITY,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_BATTERY_MIN_SOC,
    DEFAULT_CHEAP_RATE_FLOOR_SOC,
    DEFAULT_DRY_RUN,
    DEFAULT_IMMERSION_HYSTERESIS,
    DEFAULT_IMMERSION_MIN_TEMP,
    DEFAULT_IMMERSION_TARGET_TEMP,
    DEFAULT_IMMERSION_WATTAGE,
    DEFAULT_INVERTER_MAX_OUTPUT,
    DEFAULT_OVERNIGHT_CHARGE_TARGET,
    DOMAIN,
    FORECAST_P10_ATTRIBUTE,
    GIVTCP_MAX_CHARGE_TARGET_PCT,
    GIVTCP_MIN_CHARGE_TARGET_PCT,
    UPDATE_INTERVAL_SECONDS,
)
from .core.battery import BatteryStats
from .core.charge_hold import HeldCharge
from .core.engine import (
    Accumulators,
    CoordinatorData,
    CycleInputs,
    ForecastContext,
    ManualOverrides,
    PreviousCycle,
    RawSensorValues,
    build_coordinator_data,
)
from .core.rules import monthly_solar_fractions
from .core.tariff import build_tariff
from .core.timeutil import elapsed_seconds
from .discovery import (
    UNUSED_SLOT_TIME,
    ActiveChargeSlot,
    EVCharger,
    describe_charge_slots,
    discover_battery_cycle_entities,
    discover_ev_chargers,
    find_other_active_charge_slots,
    update_charger_state,
)
from .givtcp_writer import GivTCPWriter, SwitchState, state_as_int
from .immersion_actuator import ImmersionActuator, ImmersionPorts
from .logging import CycleSnapshot, GivLogger, get_logger, log_cycle
from .repairs import (
    MIN_SOC_HIGH_THRESHOLD,
    ClearOutcome,
    async_create_givtcp_missing_issue,
    async_create_min_soc_issue,
    async_create_other_charge_slots_issue,
    async_delete_givtcp_missing_issue,
    async_delete_min_soc_issue,
    async_delete_other_charge_slots_issue,
)
from .write_audit import WriteAudit

_LOG = get_logger(__name__)

_REDISCOVER_EVERY_N_CYCLES = 10  # 10 × 30s ≈ 5 minutes


def _clamp_charge_target(target_soc: float) -> int:
    """Limit a charge target to the range GivTCP accepts."""
    return max(
        GIVTCP_MIN_CHARGE_TARGET_PCT, min(GIVTCP_MAX_CHARGE_TARGET_PCT, int(target_soc))
    )


def _clamp_and_report(target_soc: int) -> int:
    """Clamp a charge target to what GivTCP accepts, warning when it had to change."""
    clamped = _clamp_charge_target(target_soc)
    if clamped != target_soc:
        _LOG.warning(
            "Charge target %s%% is outside the range GivTCP accepts (%d-%d%%), using %d%%",
            target_soc,
            GIVTCP_MIN_CHARGE_TARGET_PCT,
            GIVTCP_MAX_CHARGE_TARGET_PCT,
            clamped,
        )
    return clamped


@dataclass(frozen=True)
class _FloorCheck:
    """What the cheap rate floor decided this cycle."""

    status: str
    # The SoC to write, or None when no write is due.
    top_up_to: int | None = None


def _non_negative_float(value: object) -> float | None:
    """A number of zero or more from a state attribute, else None."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _waiting_for_cheapest_text(soc: float, period, cheapest) -> str:
    return (
        f"Battery at {soc:.0f}% during {period.name} — "
        f"waiting for cheapest rate ({cheapest.name} "
        f"{cheapest.start.strftime('%H:%M')}–{cheapest.end.strftime('%H:%M')})"
    )


def _is_stale(state) -> bool:
    """True when an entity is missing or reports unavailable or unknown."""
    return state is None or state.state in ("unavailable", "unknown")


def _cheapest_period(tariff):
    """The timed rate period with the lowest rate."""
    return min(tariff.rate_periods, key=lambda p: p.rate)


class GivEnergyCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """
    Thin HA coordinator — reads entity states, calls engine, applies HA effects.

    The actual energy management logic is in engine.py. This class only:
      - Reads raw values from hass.states via _get_state()
      - Passes them to build_coordinator_data()
      - Applies any HA service calls the engine requests via _call_service()
      - Manages time listeners (midnight reset, cheap-rate charge write-back)

    All HA surface access is proxied through _get_state, _call_service, and
    _create_task so this class is fully testable by subclassing.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOG._logger,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
            config_entry=entry,
        )
        self.entry = entry
        # Register live config accessor so all GivLogger.verbose() calls
        # read the current CONF_VERBOSE_LOGGING flag without a restart.
        GivLogger.register(self._effective_cfg)
        self._init_cycle_state()
        self._init_manual_overrides()
        self._init_immersion(entry.data)
        self._init_writer()
        self._register_time_listeners()

    def _init_cycle_state(self) -> None:
        """State threaded across update cycles."""
        self._solar_fractions: dict[int, float] = monthly_solar_fractions(self.hass.config.latitude)
        self._last_reset_time: str = ""
        self._acc = AccumulationStore(self.hass, self._configured_bill_start_day())
        self._battery_stats = BatteryStats()
        self._held_charge = HeldCharge()
        self._last_soc: float | None = None
        self._last_update: datetime | None = None
        self._update_cycle: int = 0
        self._floor_top_up_applied: bool = False
        self.export_rate: float = 0.0
        self._ev_charger: EVCharger | None = None
        self._battery_cycle_entities: list[str] = []
        self._givtcp_was_unavailable: bool = False
        self._inputs_unavailable_since: datetime | None = None
        # Last action dry run skipped. The engine builds a fresh snapshot each cycle,
        # so the value lives here and is copied onto every new snapshot.
        self._dry_run_last_skipped: str = ""
        # EMA-smoothed solar power (α=0.5) for surplus divert decisions, so they do not
        # chase transient cloud gaps. The raw value is used for accumulation.
        self._smoothed_solar_w: float = 0.0

    def _init_manual_overrides(self) -> None:
        """Overrides set by switches and numbers, read by the engine."""
        # The switch sets the flag, the number sets the value. override_charge_target
        # (property) is the only thing the engine sees.
        self.override_charge_enabled: bool = False
        self.override_charge_value: int = DEFAULT_OVERNIGHT_CHARGE_TARGET
        self.override_skip_charge: bool = False

    def _init_immersion(self, cfg: Mapping) -> None:
        """Temperature controls (set by number entities, read in _collect_raw) and the actuator."""
        self.immersion_target_temp: float = float(
            cfg.get(CONF_IMMERSION_TARGET_TEMP, DEFAULT_IMMERSION_TARGET_TEMP)
        )
        self.immersion_min_temp: float = float(
            cfg.get(CONF_IMMERSION_MIN_TEMP, DEFAULT_IMMERSION_MIN_TEMP)
        )
        self.immersion_hysteresis_c: float = float(
            cfg.get(CONF_IMMERSION_HYSTERESIS, DEFAULT_IMMERSION_HYSTERESIS)
        )
        # Decides when the real immersion switch is turned on or off. Runs every cycle, so
        # diversion works whether or not the managed switch entity is enabled.
        self.immersion = ImmersionActuator(self._immersion_ports())

    def _init_writer(self) -> None:
        # Every inverter register write goes through the writer: read-before-write, cooldown,
        # retry, write counting and one lock so writes never interleave. The lambdas look the
        # proxies up at call time so a test that swaps _call_service takes effect.
        self._audit = WriteAudit(self._acc, now=lambda: self._now())
        self._writer = GivTCPWriter(
            get_state=lambda entity_id: self._get_state(entity_id),
            call_service=lambda domain, service, data: self._call_service(domain, service, data),
            on_count_change=self._save_register_write_count,
            observer=self._audit,
        )

    def _register_time_listeners(self) -> None:
        self.entry.async_on_unload(
            async_track_time_change(self.hass, self._midnight_reset, hour=0, minute=0, second=0)
        )
        # Cheap-rate start listener (writes charge target to GivTCP). The start time comes
        # from the configured tariff, one minute before, so the target is set before charging.
        self._register_charge_target_listener()
        self._watch_managed_entities()

    def _watch_managed_entities(self) -> None:
        """Log any change to the charge target or window that the manager did not send."""
        cfg = self._effective_cfg()
        keys = (CONF_TARGET_SOC_ENTITY, CONF_CHARGE_START_TIME_ENTITY, CONF_CHARGE_END_TIME_ENTITY)
        watched = [cfg[key] for key in keys if cfg.get(key)]
        if watched:
            self.entry.async_on_unload(self._audit.watch(self.hass, watched))

    @property
    def update_cycle(self) -> int:
        """Current update cycle count — useful for diagnostics."""
        return self._update_cycle

    @property
    def solar_fractions(self) -> dict[int, float]:
        """Monthly solar generation fractions derived from HA location latitude."""
        return self._solar_fractions

    @property
    def ev_charger_brand(self) -> str | None:
        """Brand name of the discovered EV charger, or None if no charger configured."""
        return self._ev_charger.brand.value if self._ev_charger else None

    @property
    def override_charge_target(self) -> int | None:
        """Effective charge target override: the value while enabled, else None (automatic)."""
        return self.override_charge_value if self.override_charge_enabled else None

    @property
    def override_immersion(self) -> bool | None:
        """Manual immersion override: True forces on, False forces off, None is automatic."""
        return self.immersion.override

    @override_immersion.setter
    def override_immersion(self, value: bool | None) -> None:
        self.immersion.override = value

    @property
    def is_dry_run(self) -> bool:
        """True when dry-run mode is active — no commands sent to GivTCP or chargers."""
        return bool(self._effective_cfg().get(CONF_DRY_RUN, DEFAULT_DRY_RUN))

    def _immersion_ports(self) -> ImmersionPorts:
        """Wire the actuator to this coordinator. Lambdas look the proxies up at call time."""
        return ImmersionPorts(
            switch_entity=lambda: self.entry.data.get(CONF_IMMERSION_SWITCH),
            read_state=lambda entity_id: self._get_state(entity_id),
            send=lambda service, entity_id: self._call_service(
                "switch", service, {"entity_id": entity_id}
            ),
            send_in_background=self._send_switch_in_background,
            is_dry_run=lambda: self.is_dry_run,
            record_skipped=lambda action: self._record_skipped(action),
            target_temp=lambda: self.immersion_target_temp,
            now=self._now,
        )

    def _send_switch_in_background(self, service: str, entity_id: str) -> None:
        self._create_task(self._call_service("switch", service, {"entity_id": entity_id}))

    @staticmethod
    def _now() -> datetime:
        return dt_util.as_local(datetime.now(timezone.utc))

    def _record_skipped(self, action: str) -> None:
        """Remember the action dry run skipped and show it on the current snapshot."""
        self._dry_run_last_skipped = action
        if self.data is not None:
            self.data.dry_run_last_skipped = action

    # ── HA surface proxies ────────────────────────────────────────────────────
    # All Home Assistant access goes through these three methods.
    # Override them in a subclass to test the coordinator without HA.

    def _get_state(self, entity_id: str):
        """Return the HA state object for entity_id, or None."""
        return self.hass.states.get(entity_id)

    def _get_optional_state(self, entity_id: str | None):
        """Like _get_state, but an unconfigured entity id gives None."""
        return self._get_state(entity_id) if entity_id else None

    def _get_all_states(self) -> dict:
        """Return a dict of all current HA entity states keyed by entity_id."""
        return {s.entity_id: s for s in self.hass.states.async_all()}

    async def _call_service(self, domain: str, service: str, data: dict) -> None:
        """Call an HA service and wait for it to finish."""
        await self.hass.services.async_call(domain, service, data, blocking=True)

    def _create_task(self, coro) -> None:
        """Schedule a fire-and-forget coroutine as a task owned by the config entry.

        Home Assistant tracks the task on the entry and waits for it on unload
        (up to 10 seconds), so an inverter write sequence is not cut off half way.
        A failure is logged and never raised, because nothing awaits the task.
        """
        self.entry.async_create_task(self.hass, self._run_background(coro))

    async def _run_background(self, coro) -> None:
        """Await a fire-and-forget coroutine, logging any failure at warning level."""
        try:
            await coro
        except Exception as err:  # noqa: BLE001
            _LOG.warning(
                "Background task %s failed: %s",
                getattr(coro, "__qualname__", "task"),
                err,
            )

    # ── State read helpers ────────────────────────────────────────────────────

    def _read_float(self, entity_id: str | None, default: float = 0.0) -> float:
        """Read a numeric entity state safely, returning default if unavailable."""
        if not entity_id:
            return default
        state = self._get_state(entity_id)
        if state is None:
            _LOG.debug("Entity %s not found in HA state machine", entity_id)
            return default
        if state.state in ("unavailable", "unknown", ""):
            _LOG.debug("Entity %s is %s", entity_id, state.state or "empty")
            return default
        try:
            return float(state.state)
        except (ValueError, TypeError):
            _LOG.warning("Entity %s has non-numeric state %r", entity_id, state.state)
            return default

    def _read_optional_float(self, entity_id: str | None) -> float | None:
        """Read a float state, returning None if entity missing, unavailable, or unknown."""
        if not entity_id:
            return None
        state = self._get_state(entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _read_first_optional_float(self, *entity_ids: str) -> float | None:
        """Return the first entity id that has a numeric state, else None."""
        for entity_id in entity_ids:
            value = self._read_optional_float(entity_id)
            if value is not None:
                return value
        return None

    def _read_tracked(self, entity_id: str | None, name: str, unavailable: list[str]) -> float:
        """Read a float state, recording name in unavailable and returning 0.0 if it is missing."""
        value = self._read_optional_float(entity_id)
        if value is None:
            unavailable.append(name)
            return 0.0
        return value

    def _read_bool(self, entity_id: str | None, on_state: str = "on") -> bool:
        """Read a boolean entity state safely."""
        if not entity_id:
            return False
        state = self._get_state(entity_id)
        if state is None:
            _LOG.debug("Entity %s not found in HA state machine", entity_id)
            return False
        return state.state.lower() == on_state.lower()

    # ── GivTCP write helpers ──────────────────────────────────────────────────
    #
    # Thin delegates to the GivTCPWriter. Each returns True when the entity is at,
    # or was sent, the requested value, and False when the service call raised or
    # the entity is unusable.

    def _save_register_write_count(self, count: int) -> None:
        self._acc.state.register_write_count = count

    async def _givtcp_set_switch(
        self, entity_id: str | None, state: SwitchState, name: str, step: int = 0
    ) -> bool:
        return await self._writer.set_switch(entity_id, state, name, step)

    async def _givtcp_set_select(
        self, entity_id: str | None, value: str, name: str, step: int = 0
    ) -> bool:
        return await self._writer.set_select(entity_id, value, name, step)

    async def _givtcp_set_number(
        self, entity_id: str | None, value: int, name: str, step: int = 0
    ) -> bool:
        return await self._writer.set_number(entity_id, value, name, step)

    # ── Listener registration ─────────────────────────────────────────────────

    def _register_charge_target_listener(self) -> None:
        """Register a time listener to write the charge target at cheap-rate start.

        Only registers when there is at least one timed rate period configured.
        A flat-rate tariff has no cheap window to target — no write-back needed.
        """
        cfg = self._effective_cfg()
        try:
            tariff = build_tariff(cfg)
            if not tariff.rate_periods:
                _LOG.debug(
                    "No timed rate periods configured — skipping charge target "
                    "write-back listener (flat-rate tariff)"
                )
                return
            cheap_start: dtime = tariff.get_cheapest_rate_start()
            trigger_minute = (cheap_start.minute - 1) % 60
            trigger_hour = (
                cheap_start.hour if cheap_start.minute > 0 else (cheap_start.hour - 1) % 24
            )
            _LOG.debug(
                "Registering charge target write-back at %02d:%02d (cheap rate starts %s)",
                trigger_hour,
                trigger_minute,
                cheap_start.strftime("%H:%M"),
            )
            self.entry.async_on_unload(
                async_track_time_change(
                    self.hass,
                    self._write_charge_target_to_inverter,
                    hour=trigger_hour,
                    minute=trigger_minute,
                    second=0,
                )
            )
        except (ValueError, TypeError, AttributeError) as err:
            _LOG.warning("Could not register charge target listener: %s", err)

    async def async_restore_state(self) -> None:
        """Load stored accumulators and apply any resets missed while HA was down."""
        await self._acc.async_load()
        self._acc.restore_battery_stats(self._battery_stats)
        self._writer.write_count = self._acc.state.register_write_count
        now = dt_util.as_local(datetime.now(timezone.utc))
        if self._acc.roll_forward(now):
            await self._acc.async_save()
        self._last_reset_time = self._acc.state.last_reset_iso
        self.entry.async_on_unload(self.async_flush)
        self.entry.async_on_unload(
            self.hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, self._queue_final_write)
        )

    async def async_flush(self) -> None:
        """Write the accumulators and battery statistics to storage now."""
        self._acc.save_battery_stats(self._battery_stats)
        await self._acc.async_save()

    @callback
    def _queue_final_write(self, _event: Event) -> None:
        """Hand the shutdown write to the store, which runs it at the final-write stage.

        Writing from our own final-write listener cancels the store's pending listener while
        HA is still dispatching it, and HA logs an error. The store serialises the state lazily,
        so energy added between stop and final write is still saved.
        """
        self._acc.save_battery_stats(self._battery_stats)
        self._acc.schedule_save()

    # ── Time-triggered callbacks ──────────────────────────────────────────────

    @callback
    def _midnight_reset(self, now: datetime) -> None:
        midnight = dt_util.as_local(now).replace(hour=0, minute=0, second=0, microsecond=0)
        self._last_reset_time = midnight.isoformat()
        self._floor_top_up_applied = False
        self._acc.on_midnight(midnight)
        self.hass.async_create_task(self._acc.async_save())
        self._last_update = None
        _LOG.debug("Midnight reset: daily, weekly, and monthly accumulators updated")

    @callback
    def _write_charge_target_to_inverter(self, _now: datetime) -> None:
        """
        Write tonight's charge target and charge window to GivTCP entities.

        Called once per day one minute before the cheap rate window starts.
        Performs the full sequence that batpred and givenergy-local both
        identify as necessary for GivEnergy inverters:

          1. Enable the charge schedule  (switch.givtcp_{S}_enable_charge_schedule)
          2. Set the charge window start  (select.givtcp_{S}_charge_start_time_slot_1)
          3. Set the charge window end    (select.givtcp_{S}_charge_end_time_slot_1)
          4. Set the target SoC           (number.givtcp_{S}_target_soc)
          5. Enable the charge target     (switch.givtcp_{S}_enable_charge_target)

        Step 5 is critical: without switch.givtcp_{S}_enable_charge_target being ON,
        the inverter silently ignores the target_soc register entirely.
        We set it ON for any target < 100%, and OFF for 100% to avoid the
        charge-bounce bug (battery oscillates 99-100% when limit switch is on at 100%).
        """
        cfg = self._effective_cfg()
        if not cfg.get(CONF_TARGET_SOC_ENTITY):
            _LOG.debug("No target SoC entity configured — skipping charge target write-back")
            return
        if self.data is None or self.data.charge_decision is None:
            _LOG.warning("No charge decision available yet — skipping charge target write-back")
            return
        decision = self.data.charge_decision
        # The sensors catch up with what is written on the next cycle.
        self._held_charge.decision = None
        if decision.skip_charge:
            self._write_minimum_target(cfg, decision)
        else:
            self._write_overnight_target(cfg, decision)

    def _write_minimum_target(self, cfg: dict, decision) -> None:
        """Write the minimum SoC as the target on a night the charge is skipped.

        If the old target (for example 80%) stays in GivTCP, the inverter holds the
        battery at that level and imports from the grid instead of discharging.
        """
        tariff = build_tariff(cfg)
        if not tariff.rate_periods:
            _LOG.info(
                "skip_charge=True (%s) — no rate periods, leaving GivTCP unchanged",
                decision.reason,
            )
            return
        min_soc = int(cfg.get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC))
        if self.is_dry_run:
            _LOG.info(
                "DRY RUN: skip_charge=True — would write min target %d%% (%s)",
                min_soc,
                decision.reason,
            )
            return
        _LOG.info(
            "skip_charge=True — writing min target %d%% to allow free discharge (%s)",
            min_soc,
            decision.reason,
        )
        self._create_task(
            self._async_apply_charge_target(cfg, min_soc, _cheapest_period(tariff))
        )

    def _write_overnight_target(self, cfg: dict, decision) -> None:
        """Write the calculated charge target and the cheapest window to GivTCP."""
        tariff = build_tariff(cfg)
        if not tariff.rate_periods:
            _LOG.warning(
                "No timed rate periods configured — cannot determine charge window. "
                "Add at least one rate period (e.g. Night) in Settings → Configure."
            )
            return
        cheap = _cheapest_period(tariff)
        window = f"{cheap.start.strftime('%H:%M')}–{cheap.end.strftime('%H:%M')}"
        if self.is_dry_run:
            action = (
                f"Would write charge target {decision.target_soc}% for {cheap.name} window "
                f"{window} ({decision.reason})"
            )
            _LOG.info("DRY RUN: %s", action)
            self._record_skipped(action)
            return
        _LOG.info(
            "Writing charge target %d%% for %s window %s (reason: %s)",
            decision.target_soc,
            cheap.name,
            window,
            decision.reason,
        )
        self._create_task(self._async_apply_charge_target(cfg, decision.target_soc, cheap))

    async def _async_apply_charge_target(self, cfg: dict, target_soc: int, cheap_period) -> None:
        """
        Apply charge target and window to GivTCP in the correct order.

        Runs as an async task so it can await each service call.
        Each write is followed by a brief read-back to verify acceptance.
        The charge target is not enabled when writing the target number failed,
        because the inverter would then limit charging to a stale target.
        """
        target_soc = _clamp_and_report(target_soc)
        await self._givtcp_set_switch(
            cfg.get(CONF_ENABLE_CHARGE_SCHEDULE),
            SwitchState.ON,
            "enable charge schedule",
            step=1,
        )
        start_str, end_str = await self._write_charge_window(cfg, cheap_period)
        target_written = await self._givtcp_set_number(
            cfg.get(CONF_TARGET_SOC_ENTITY), target_soc, "charge target", step=4
        )
        enable_target = target_soc < 100
        if enable_target and not target_written:
            _LOG.warning(
                "Charge target %d%% could not be written — not enabling the charge target",
                target_soc,
            )
            return
        await self._givtcp_set_switch(
            cfg.get(CONF_ENABLE_CHARGE_TARGET),
            SwitchState.ON if enable_target else SwitchState.OFF,
            "enable charge target",
            step=5,
        )
        _LOG.info(
            "Charge target write-back complete: %d%% window %s–%s enable_target=%s",
            target_soc,
            start_str,
            end_str,
            enable_target,
        )

    async def _write_charge_window(self, cfg: dict, cheap_period) -> tuple[str, str]:
        """Write the charge window start and end times, returning them as written."""
        start_str = cheap_period.start.strftime("%H:%M:%S")
        end_str = cheap_period.end.strftime("%H:%M:%S")
        await self._givtcp_set_select(
            cfg.get(CONF_CHARGE_START_TIME_ENTITY), start_str, "charge window start", step=2
        )
        await self._givtcp_set_select(
            cfg.get(CONF_CHARGE_END_TIME_ENTITY), end_str, "charge window end", step=3
        )
        return start_str, end_str

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _effective_cfg(self) -> dict:
        """Merge options over data so tariff edits take immediate effect."""
        cfg = dict(self.entry.data)
        cfg.update(self.entry.options)
        return cfg

    def _configured_bill_start_day(self, cfg: dict | None = None) -> int:
        """Return the bill start day from the effective config (options over data)."""
        from .const import CONF_BILL_START_DAY, DEFAULT_BILL_START_DAY

        cfg = cfg if cfg is not None else self._effective_cfg()
        return int(cfg.get(CONF_BILL_START_DAY, DEFAULT_BILL_START_DAY))

    def _read_power_inputs(self, cfg: dict, raw: RawSensorValues, unavailable: list[str]) -> None:
        """Read solar, battery and house power, recording any unavailable inputs."""
        raw.solar_power_w = self._read_tracked(
            cfg.get(CONF_SOLAR_POWER), "solar_power", unavailable
        )
        # EMA smoothing (α=0.5) — prevents divert decisions from chasing transient cloud gaps.
        # The smoothed value converges to steady state in ~4 cycles (2 minutes at 30s intervals).
        # An unavailable reading is not fed in, so a dropout does not drag the average to zero.
        if "solar_power" not in unavailable:
            self._smoothed_solar_w = 0.5 * self._smoothed_solar_w + 0.5 * raw.solar_power_w
        raw.smoothed_solar_power_w = self._smoothed_solar_w
        raw.battery_soc = self._read_tracked(cfg.get(CONF_BATTERY_SOC), "battery_soc", unavailable)
        # GivTCP reports battery power as positive=discharging, negative=charging.
        # Negate to match internal convention (positive=charging, negative=discharging).
        # Subtracting from 0.0 avoids a -0.0 reading when the sensor is idle or missing.
        raw.battery_power_w = 0.0 - self._read_tracked(
            cfg.get(CONF_BATTERY_POWER), "battery_power", unavailable
        )
        # GivTCP v3 uses positive=export, negative=import.
        # Negate to match internal convention (positive=import, negative=export).
        raw.grid_power_w = -self._read_float(cfg.get(CONF_GRID_POWER))
        raw.house_load_w = self._read_tracked(cfg.get(CONF_HOUSE_LOAD), "house_load", unavailable)

    def _collect_raw(self, cfg: dict) -> RawSensorValues:
        """Read all sensor entity states and return as a plain-Python struct."""
        raw = RawSensorValues()
        unavailable: list[str] = []
        self._read_power_inputs(cfg, raw, unavailable)
        self._read_system_limits(cfg, raw)
        self._read_immersion_inputs(cfg, raw, unavailable)
        raw.unavailable_inputs = tuple(unavailable)
        self._read_forecasts(cfg, raw)
        raw.carbon_intensity_gco2 = self._read_optional_float(
            cfg.get(CONF_CARBON_INTENSITY_ENTITY)
        )
        raw.inverter_temp = self._read_optional_float(cfg.get(CONF_INVERTER_TEMP_ENTITY))
        self._copy_ev_state(raw)
        raw.battery_lifetime_cycles = self._read_battery_lifetime_cycles()
        self._read_daily_counters(cfg, raw)
        return raw

    @staticmethod
    def _read_system_limits(cfg: dict, raw: RawSensorValues) -> None:
        raw.inverter_max_w = cfg.get(CONF_INVERTER_MAX_OUTPUT, DEFAULT_INVERTER_MAX_OUTPUT) * 1000
        raw.battery_capacity_kwh = float(cfg.get(CONF_BATTERY_CAPACITY, DEFAULT_BATTERY_CAPACITY))

    def _read_immersion_inputs(
        self, cfg: dict, raw: RawSensorValues, unavailable: list[str]
    ) -> None:
        raw.immersion_wattage_w = float(cfg.get(CONF_IMMERSION_WATTAGE, DEFAULT_IMMERSION_WATTAGE))
        raw.immersion_on = self._read_bool(cfg.get(CONF_IMMERSION_SWITCH))
        raw.immersion_target_temp = self.immersion_target_temp
        raw.immersion_min_temp = self.immersion_min_temp
        raw.immersion_hysteresis_c = self.immersion_hysteresis_c
        temp_eid = cfg.get(CONF_IMMERSION_TEMP_SENSOR)
        if temp_eid:
            raw.immersion_temp = self._read_optional_float(temp_eid)
            if raw.immersion_temp is None:
                unavailable.append("immersion_temp")

    def _read_forecasts(self, cfg: dict, raw: RawSensorValues) -> None:
        raw.forecast_kwh_tomorrow = self._read_forecast_kwh(cfg.get(CONF_FORECAST_ENTITY))
        raw.forecast_kwh_p10 = self._read_p10_forecast(cfg)
        raw.forecast_kwh_d2 = self._read_forecast_kwh(cfg.get(CONF_FORECAST_ENTITY_D2))

    def _read_p10_forecast(self, cfg: dict) -> float | None:
        """The pessimistic forecast: the configured P10 sensor, else the forecast sensor's own.

        Solcast puts the P10 total in an attribute of its forecast sensors, so it needs no
        setup. A sensor chosen in the options takes precedence.
        """
        configured = self._read_forecast_kwh(cfg.get(CONF_FORECAST_ENTITY_P10))
        if configured is not None:
            return configured
        state = self._get_optional_state(cfg.get(CONF_FORECAST_ENTITY))
        if state is None:
            return None
        return _non_negative_float(state.attributes.get(FORECAST_P10_ATTRIBUTE))

    def _read_forecast_kwh(self, entity_id: str | None) -> float | None:
        """A forecast reading in kWh, or None when it is missing or negative."""
        value = self._read_optional_float(entity_id)
        return value if value is not None and value >= 0 else None

    def _copy_ev_state(self, raw: RawSensorValues) -> None:
        if self._ev_charger is not None:
            raw.ev_power_w = self._ev_charger.power_w
            raw.ev_plugged_in = self._ev_charger.is_plugged_in

    def _read_daily_counters(self, cfg: dict, raw: RawSensorValues) -> None:
        """GivTCP daily energy counters, present on GivTCP v2.1+ and v3.

        Entity IDs are derived from the inverter serial stored in config. A missing or
        unavailable entity reads as None, and the engine then falls back to power integration.
        """
        serial = cfg.get(CONF_INVERTER_SERIAL)
        if not serial:
            return
        pfx = f"sensor.givtcp_{serial}"
        raw.solar_energy_today_kwh = self._read_optional_float(f"{pfx}_pv_energy_today_kwh")
        raw.import_energy_today_kwh = self._read_optional_float(f"{pfx}_import_energy_today_kwh")
        raw.export_energy_today_kwh = self._read_optional_float(f"{pfx}_export_energy_today_kwh")
        # GivTCP names these battery_charge_energy_today_kwh and
        # battery_discharge_energy_today_kwh. The unprefixed names are kept
        # as a fallback for older GivTCP versions.
        raw.charge_energy_today_kwh = self._read_first_optional_float(
            f"{pfx}_battery_charge_energy_today_kwh", f"{pfx}_charge_energy_today_kwh"
        )
        raw.discharge_energy_today_kwh = self._read_first_optional_float(
            f"{pfx}_battery_discharge_energy_today_kwh", f"{pfx}_discharge_energy_today_kwh"
        )
        raw.load_energy_today_kwh = self._read_optional_float(f"{pfx}_load_energy_today_kwh")

    def _track_input_outage(self, raw: RawSensorValues, now: datetime) -> None:
        """Record how long the required inputs have been continuously unavailable."""
        if not raw.unavailable_inputs:
            self._inputs_unavailable_since = None
            raw.unavailable_for_s = 0.0
            return
        if self._inputs_unavailable_since is None:
            self._inputs_unavailable_since = now
        raw.unavailable_for_s = max(0.0, elapsed_seconds(self._inputs_unavailable_since, now))
    def _read_battery_lifetime_cycles(self) -> float | None:
        """Highest BMS cycle counter across the battery packs, None if none is readable.

        Each pack counts its own cycles, so the packs are not summed.
        """
        values = [self._read_optional_float(eid) for eid in self._battery_cycle_entities]
        readable = [v for v in values if v is not None and v > 0]
        return max(readable) if readable else None

    def _maybe_rediscover_battery_cycles(self) -> None:
        """Look for GivTCP battery cycle counters every 5 minutes so new packs are picked up."""
        if self._update_cycle % _REDISCOVER_EVERY_N_CYCLES == 1:
            self._battery_cycle_entities = discover_battery_cycle_entities(
                self._get_all_states()
            )

    def _maybe_rediscover_ev(self) -> None:
        """Re-run EV charger discovery every 5 minutes when none is cached."""
        needs_discovery = self._ev_charger is None or self._ev_charger.power_entity is None
        if needs_discovery and (self._update_cycle % _REDISCOVER_EVERY_N_CYCLES == 1):
            found = discover_ev_chargers(self._get_all_states())
            if found:
                self._ev_charger = found[0]
                _LOG.info("Discovered EV charger: %s", self._ev_charger.display_name)
            else:
                _LOG.debug("No EV charger found (cycle %d)", self._update_cycle)

    def _apply_ev_action(self, target_mode: str | None) -> None:
        """Apply an EV charger mode change via HA service call.

        Skips the write when the charger is already in the target mode and honours
        the same per-entity write cooldown as the GivTCP writes.
        """
        charger = self._ev_charger
        if target_mode is None or charger is None or not charger.charge_mode_entity:
            return
        current = (charger.charge_mode or "").strip()
        if current == target_mode:
            return
        if self.is_dry_run:
            self._record_ev_dry_run(charger, target_mode, current)
        elif not self._writer.cooldown_active(
            charger.charge_mode_entity, charger.display_name, target_mode
        ):
            self._writer.start_cooldown(charger.charge_mode_entity, target_mode)
            self._send_ev_mode(charger, target_mode)

    def _record_ev_dry_run(self, charger: EVCharger, target_mode: str, current: str) -> None:
        action = f"Would set {charger.display_name} → {target_mode} (currently {current!r})"
        _LOG.info("DRY RUN: %s", action)
        self._record_skipped(action)

    def _send_ev_mode(self, charger: EVCharger, target_mode: str) -> None:
        _LOG.info("EV charger action: %s → %s", charger.display_name, target_mode)
        self._create_task(
            self._call_service(
                "select",
                "select_option",
                {"entity_id": charger.charge_mode_entity, "option": target_mode},
            )
        )

    async def _write_floor_target(self, cfg: dict, target_entity: str, soc: int) -> bool:
        """Write SoC target and enable charge target switch for cheap rate floor top-up.

        Uses the same read-before-write, cooldown, write counting and read-back
        helpers as the overnight charge target so the inverter registers are not
        written more often than necessary. The floor only raises the target. A
        higher target already on the inverter, such as the overnight charge
        target, is kept. Returns False, without enabling the charge target,
        when the target could not be written.
        """
        current = state_as_int(self._get_state(target_entity))
        soc = _clamp_charge_target(max(soc, current) if current is not None else soc)
        if not await self._givtcp_set_number(target_entity, soc, "floor top-up"):
            return False
        return await self._givtcp_set_switch(
            cfg.get(CONF_ENABLE_CHARGE_TARGET),
            SwitchState.ON,
            "floor top-up enable",
        )

    # ── Main update cycle ─────────────────────────────────────────────────────

    async def _maybe_apply_cheap_rate_floor(self, now: datetime, raw, cfg: dict) -> str:
        """During cheap rate hours, top up battery if it drops below the floor.

        Optimises for the cheapest available window (e.g. Nightboost over Night):
        - In the cheapest timed period: apply the full floor (default 40%).
        - In a cheaper-than-base but not cheapest period: only top up if battery
          is near the minimum SoC — otherwise wait for the cheapest window.

        Called every 30s cycle. Only writes to the inverter once per night
        (flag resets at midnight). Returns the text for the Cheap Rate Floor sensor.
        """
        check = self._check_cheap_rate_floor(now, raw, cfg)
        if check.top_up_to is None:
            return check.status
        _LOG.info("Cheap rate floor: %s", check.status)
        return await self._top_up_to_floor(cfg, check)

    def _check_cheap_rate_floor(self, now: datetime, raw, cfg: dict) -> _FloorCheck:
        """Decide whether the battery needs a top-up now, and what to tell the sensor."""
        floor_soc = int(cfg.get(CONF_CHEAP_RATE_FLOOR_SOC, DEFAULT_CHEAP_RATE_FLOOR_SOC))
        if floor_soc <= 0:
            return _FloorCheck("")
        tariff = build_tariff(cfg)
        period = tariff.get_current_rate(now)
        # Only active during a timed period cheaper than the base rate
        if period.rate >= tariff.base_rate:
            return _FloorCheck("")
        cheapest = tariff.get_cheapest_rate() if tariff.rate_periods else period
        if period.rate <= cheapest.rate:
            effective_floor = floor_soc
        else:
            # A better rate is coming or was available. Only top up for genuine
            # emergencies (near minimum SoC).
            effective_floor = int(cfg.get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC)) + 5
            if raw.battery_soc >= effective_floor:
                return _FloorCheck(_waiting_for_cheapest_text(raw.battery_soc, period, cheapest))
        if raw.battery_soc >= effective_floor:
            return _FloorCheck("")
        return self._floor_top_up_check(raw.battery_soc, period, effective_floor)

    def _floor_top_up_check(self, soc: float, period, effective_floor: int) -> _FloorCheck:
        if self._floor_top_up_applied:
            return _FloorCheck(
                f"Floor already applied this window — battery at {soc:.0f}%, "
                f"floor {effective_floor}%"
            )
        status = f"Battery at {soc:.0f}% during {period.name} — topping up to {effective_floor}%"
        return _FloorCheck(status, top_up_to=effective_floor)

    async def _top_up_to_floor(self, cfg: dict, check: _FloorCheck) -> str:
        """Write the floor target, or report why it was not written."""
        target_entity = cfg.get(CONF_TARGET_SOC_ENTITY)
        if not target_entity:
            _LOG.warning("Cheap rate floor triggered but no target SoC entity configured")
            return check.status
        if self.is_dry_run:
            _LOG.info("DRY RUN: %s", check.status)
            return f"DRY RUN: {check.status}"
        if not await self._write_floor_target(cfg, target_entity, check.top_up_to):
            return f"Error writing floor — {check.status}"
        self._floor_top_up_applied = True
        return check.status

    def _check_config_repair_issues(self, cfg: dict) -> None:
        """Raise or clear repair issues for misconfigured values that won't self-heal."""
        min_soc = int(cfg.get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC))
        if min_soc > MIN_SOC_HIGH_THRESHOLD:
            async_create_min_soc_issue(self.hass, min_soc)
        else:
            async_delete_min_soc_issue(self.hass)
        self._check_other_charge_slots(cfg)

    def _other_charge_slots(self, cfg: dict[str, Any]) -> list[ActiveChargeSlot]:
        """Charge slots other than the managed one that have a window set. Reads only."""
        start_entity = cfg.get(CONF_CHARGE_START_TIME_ENTITY)
        end_entity = cfg.get(CONF_CHARGE_END_TIME_ENTITY)
        if not (start_entity and end_entity):
            return []
        return find_other_active_charge_slots(start_entity, end_entity, self._get_state)

    def _check_other_charge_slots(self, cfg: dict[str, Any]) -> None:
        """Raise the repair issue while another slot can charge the battery, else clear it."""
        slots = self._other_charge_slots(cfg)
        if slots:
            async_create_other_charge_slots_issue(self.hass, slots)
        else:
            async_delete_other_charge_slots_issue(self.hass)

    async def async_clear_other_charge_slots(self) -> ClearOutcome:
        """Set each other active charge slot back to 00:00 to 00:00, then re-check the issue.

        Called by the repair fix flow. The integration owns one slot, and a leftover
        slot charges the battery outside the cheapest period. Dry run only records
        what it would have cleared.
        """
        cfg = self._effective_cfg()
        slots = self._other_charge_slots(cfg)
        if slots and self.is_dry_run:
            self._record_skipped(f"Would clear other charge slots: {describe_charge_slots(slots)}")
            return ClearOutcome.DRY_RUN
        if slots:
            _LOG.info("Clearing other charge slots: %s", describe_charge_slots(slots))
        results = [await self._clear_charge_slot(slot) for slot in slots]
        self._check_other_charge_slots(cfg)
        return ClearOutcome.CLEARED if all(results) else ClearOutcome.FAILED

    async def _clear_charge_slot(self, slot: ActiveChargeSlot) -> bool:
        """Write 00:00:00 to the slot's start, then its end. Stops at the first failed write."""
        name = f"clear other slot {slot.number}"
        return await self._givtcp_set_select(
            slot.start_entity_id, UNUSED_SLOT_TIME, f"{name} start"
        ) and await self._givtcp_set_select(slot.end_entity_id, UNUSED_SLOT_TIME, f"{name} end")

    async def _async_update_data(self) -> CoordinatorData:
        """Run one cycle: read inputs, build the snapshot, apply decisions, persist."""
        self._begin_cycle()
        cfg = self._effective_cfg()
        self._require_givtcp_publishing(cfg)
        now = self._now()
        raw = self._read_inputs(cfg, now)
        data, ev_target_mode = build_coordinator_data(
            CycleInputs(
                raw=raw,
                cfg=cfg,
                now=now,
                ev_charger=self._ev_charger,
                overrides=ManualOverrides(
                    charge_target=self.override_charge_target,
                    immersion=self.override_immersion,
                    skip_charge=self.override_skip_charge,
                ),
            ),
            Accumulators(
                today=self._acc.today,
                week=self._acc.week,
                month=self._acc.month,
                year=self._acc.year,
                yesterday=self._acc.yesterday,
                last_reset_time=self._last_reset_time,
            ),
            PreviousCycle(
                battery_stats=self._battery_stats,
                last_soc=self._last_soc,
                last_update_time=self._last_update,
                held_charge=self._held_charge,
            ),
            ForecastContext(
                solar_fractions=self._solar_fractions,
                solar_forecast_kwh_today=self._acc.today_forecast_kwh,
                yesterday_forecast_accuracy_pct=self._acc.yesterday_forecast_accuracy_pct,
                forecast_accuracy_7day_avg_pct=self._acc.forecast_accuracy_7day_avg_pct,
                load_profile=self._acc.slot_load_profile((now + timedelta(days=1)).weekday()),
                forecast_correction=self._acc.forecast_correction_factor,
                today_raw_forecast_kwh=self._acc.today_raw_forecast_kwh,
                today_raw_forecast_p10_kwh=self._acc.today_raw_forecast_p10_kwh,
            ),
        )
        self._attach_stored_totals(data)
        self.immersion.annotate_divert_reason(data, raw.immersion_temp)
        self._record_forecast(raw, data)
        data.cheap_rate_floor_status = await self._maybe_apply_cheap_rate_floor(now, raw, cfg)
        log_cycle(_LOG, CycleSnapshot(self._update_cycle, now, raw, data))
        self._remember_cycle(raw, now)
        self._apply_decisions(data, ev_target_mode, now)
        return data

    def _begin_cycle(self) -> None:
        """Count the cycle, save the stored state every tenth, and apply the live config."""
        self._update_cycle += 1
        if self._update_cycle % 10 == 0:
            self._acc.save_battery_stats(self._battery_stats)
            self._acc.schedule_save()
        cfg = self._effective_cfg()
        self._acc.update_bill_start_day(self._configured_bill_start_day(cfg))
        self.export_rate = float(cfg.get(CONF_EXPORT_RATE, 0.0))
        self._check_config_repair_issues(cfg)

    def _require_givtcp_publishing(self, cfg: dict) -> None:
        """Fail the cycle when GivTCP's solar and battery sensors are both stale.

        Both must be stale before raising, so a single brief interruption does not mark
        the whole integration unavailable.
        """
        solar = self._get_optional_state(cfg.get(CONF_SOLAR_POWER))
        battery = self._get_optional_state(cfg.get(CONF_BATTERY_SOC))
        if _is_stale(solar) and _is_stale(battery):
            self._note_givtcp_silent(solar, battery)
            raise UpdateFailed(
                translation_domain="givenergy_inverter_manager",
                translation_key="givtcp_unavailable",
            )
        self._note_givtcp_publishing()

    def _note_givtcp_silent(self, solar, battery) -> None:
        if not self._givtcp_was_unavailable:
            _LOG.warning(
                "GivTCP has stopped publishing data — solar and battery sensors "
                "are unavailable. Check GivTCP is running and MQTT is connected."
            )
            self._givtcp_was_unavailable = True
        if solar is None and battery is None:
            async_create_givtcp_missing_issue(self.hass)

    def _note_givtcp_publishing(self) -> None:
        if self._givtcp_was_unavailable:
            _LOG.info("GivTCP is publishing data again — resuming normal operation.")
            self._givtcp_was_unavailable = False
        async_delete_givtcp_missing_issue(self.hass)

    def _read_inputs(self, cfg: dict, now: datetime) -> RawSensorValues:
        """Refresh discovery, read every input and note outages and the baseline load."""
        self._maybe_rediscover_ev()
        self._maybe_rediscover_battery_cycles()
        raw = self._collect_raw(cfg)
        self._refresh_ev_charger(raw)
        self.immersion.release_if_at_target(raw.immersion_temp)
        self._track_input_outage(raw, now)
        self._record_baseline_load(raw, now)
        return raw

    def _refresh_ev_charger(self, raw: RawSensorValues) -> None:
        """Update the charger state now that battery_power_w is known."""
        if self._ev_charger is not None:
            update_charger_state(self._get_state, self._ev_charger, raw.battery_power_w)
            self._copy_ev_state(raw)

    def _record_baseline_load(self, raw: RawSensorValues, now: datetime) -> None:
        """Add this slot's house load, less the immersion and EV, to the baseline profile."""
        if self._last_update is None:
            return
        elapsed_h = elapsed_seconds(self._last_update, now) / 3600
        slot = now.hour * 2 + now.minute // 30
        immersion_w = raw.immersion_wattage_w if raw.immersion_on else 0.0
        baseline_w = max(0.0, raw.house_load_w - immersion_w - raw.ev_power_w)
        self._acc.record_slot_load(now, slot, (baseline_w / 1000) * elapsed_h, elapsed_h)

    def _attach_stored_totals(self, data: CoordinatorData) -> None:
        """Copy the period start times, write count and trailing totals onto the snapshot."""
        data.week_start_time = self._acc.state.week_start_iso
        data.month_start_time = self._acc.state.month_start_iso
        data.year_start_time = self._acc.state.year_start_iso
        data.register_write_count = self._writer.write_count
        data.register_write_log = list(self._acc.state.register_write_log)
        data.trailing_12m_export_kwh = self._acc.trailing_12m_export_kwh
        data.trailing_12m_solar_kwh = self._acc.trailing_12m_solar_kwh
        data.trailing_12m_import_kwh = self._acc.trailing_12m_import_kwh
        data.trailing_12m_import_cost = self._acc.trailing_12m_import_cost
        data.trailing_12m_export_earnings = self._acc.trailing_12m_export_earnings

    def _record_forecast(self, raw: RawSensorValues, data: CoordinatorData) -> None:
        """Feed the forecast accuracy tracking and note whether the inverter is clipping."""
        self._acc.on_raw_forecast(raw.forecast_kwh_tomorrow, raw.forecast_kwh_p10)
        if data.is_clipping:
            self._acc.note_clipping()
        if data.charge_decision is not None and data.charge_decision.forecast_kwh > 0:
            self._acc.on_charge_decision(data.charge_decision.forecast_kwh)

    def _remember_cycle(self, raw: RawSensorValues, now: datetime) -> None:
        """Keep what the next cycle needs: the last SoC and the cycle time."""
        self._last_soc = None if "battery_soc" in raw.unavailable_inputs else raw.battery_soc
        self._last_update = now

    def _apply_decisions(
        self, data: CoordinatorData, ev_target_mode: str | None, now: datetime
    ) -> None:
        """Send the EV and immersion commands the engine asked for."""
        self._apply_ev_action(ev_target_mode)
        if self.data is not None:
            # The first cycle only observes. At startup the real switch may not be up yet.
            self.immersion.actuate(data, now)
        # The engine's snapshot starts empty. Copy after the actions so a skip
        # recorded in this cycle shows up in this snapshot.
        data.dry_run_last_skipped = self._dry_run_last_skipped


# The config entry type for this integration. Platforms and __init__ use it so
# entry.runtime_data is typed as the coordinator.
GivEnergyConfigEntry = ConfigEntry[GivEnergyCoordinator]
