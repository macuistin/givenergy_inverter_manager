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
  _call_service(domain, service, data, blocking)
                                  wraps hass.services.async_call()
  _create_task(coro)              wraps hass.async_create_task()

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

import asyncio
from datetime import datetime, timedelta, timezone
from datetime import time as dtime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .accumulation import AccumulationStore
from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_CHARGE_END_TIME_ENTITY,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_CHEAP_RATE_FLOOR_SOC,
    CONF_DRY_RUN,
    CONF_ENABLE_CHARGE_SCHEDULE,
    CONF_ENABLE_CHARGE_TARGET,
    CONF_FORECAST_ENTITY,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_IMMERSION_HYSTERESIS,
    CONF_IMMERSION_MIN_TEMP,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TARGET_TEMP,
    CONF_IMMERSION_TEMP_SENSOR,
    CONF_IMMERSION_WATTAGE,
    CONF_INVERTER_MAX_OUTPUT,
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
    DOMAIN,
    UPDATE_INTERVAL_SECONDS,
)
from .core.battery import BatteryStats
from .core.engine import (
    CoordinatorData,
    RawSensorValues,
    build_coordinator_data,
)
from .core.rules import monthly_solar_fractions
from .core.tariff import build_tariff
from .discovery import (
    EVCharger,
    discover_ev_chargers,
    update_charger_state,
)
from .logging import GivLogger, get_logger, log_cycle, log_givtcp_write

_LOG = get_logger(__name__)

_REDISCOVER_EVERY_N_CYCLES = 10  # 10 × 30s ≈ 5 minutes


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

        # Mutable state threaded across update cycles
        self._solar_fractions: dict[int, float] = monthly_solar_fractions(
            getattr(hass.config, "latitude", 51.5)  # 51.5N = reasonable mid-Europe fallback
        )
        self._last_reset_time: str = ""
        from .const import CONF_BILL_START_DAY, DEFAULT_BILL_START_DAY

        _bill_start = int(entry.data.get(CONF_BILL_START_DAY, DEFAULT_BILL_START_DAY))
        self._acc = AccumulationStore(hass, _bill_start)
        self._battery_stats = BatteryStats()
        self._last_soc: float | None = None
        self._last_update: datetime | None = None
        self._update_cycle: int = 0
        self._floor_top_up_applied: bool = False
        self.export_rate: float = 0.0
        self._ev_charger: EVCharger | None = None

        # Manual overrides set by switch/number entities
        self.override_charge_target: int | None = None
        # Immersion temperature controls — set by number entities, read in _collect_raw
        cfg = entry.data
        self.immersion_target_temp: float = float(
            cfg.get(CONF_IMMERSION_TARGET_TEMP, DEFAULT_IMMERSION_TARGET_TEMP)
        )
        self.immersion_min_temp: float = float(
            cfg.get(CONF_IMMERSION_MIN_TEMP, DEFAULT_IMMERSION_MIN_TEMP)
        )
        self.immersion_hysteresis_c: float = float(
            cfg.get(CONF_IMMERSION_HYSTERESIS, DEFAULT_IMMERSION_HYSTERESIS)
        )
        self.override_immersion: bool | None = None
        self.override_skip_charge: bool = False

        # Register midnight accumulator reset
        entry.async_on_unload(
            async_track_time_change(hass, self._midnight_reset, hour=0, minute=0, second=0)
        )

        # Register cheap-rate start listener (writes charge target to GivTCP).
        # We derive the start time from the configured tariff and register
        # one minute before so the target is set before charging begins.
        self._register_charge_target_listener()

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
    def is_dry_run(self) -> bool:
        """True when dry-run mode is active — no commands sent to GivTCP or chargers."""
        return bool(self._effective_cfg().get(CONF_DRY_RUN, DEFAULT_DRY_RUN))

    # ── HA surface proxies ────────────────────────────────────────────────────
    # All Home Assistant access goes through these three methods.
    # Override them in a subclass to test the coordinator without HA.

    def _get_state(self, entity_id: str):
        """Return the HA state object for entity_id, or None."""
        return self.hass.states.get(entity_id)

    def _get_all_states(self) -> dict:
        """Return a dict of all current HA entity states keyed by entity_id."""
        return {s.entity_id: s for s in self.hass.states.async_all()}

    async def _call_service(
        self,
        domain: str,
        service: str,
        data: dict,
        blocking: bool = True,
    ) -> None:
        """Call an HA service."""
        await self.hass.services.async_call(domain, service, data, blocking=blocking)

    def _create_task(self, coro) -> None:
        """Schedule a coroutine as an HA task."""
        self.hass.async_create_task(coro)

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

    async def _givtcp_set_switch(
        self,
        entity_id: str | None,
        state: bool,
        name: str,
        step: int = 0,
    ) -> None:
        """Set a GivTCP switch entity, verify the write, and log both."""
        if not entity_id:
            return
        service = "turn_on" if state else "turn_off"
        await self._call_service("switch", service, {"entity_id": entity_id})
        await asyncio.sleep(1)
        actual = self._get_state(entity_id)
        actual_on = actual is not None and actual.state == "on"
        accepted = actual_on == state
        log_givtcp_write(
            _LOG,
            step,
            entity_id,
            "on" if state else "off",
            actual.state if actual else "unknown",
            accepted,
        )
        if not accepted:
            _LOG.warning(
                "%s: wrote %s but read back %s — GivTCP may not have accepted the write",
                name,
                "on" if state else "off",
                actual.state if actual else "unknown",
            )

    async def _givtcp_set_select(
        self,
        entity_id: str | None,
        value: str,
        name: str,
        step: int = 0,
    ) -> None:
        """Set a GivTCP select entity, verify the write, and log both."""
        if not entity_id:
            return
        await self._call_service(
            "select", "select_option", {"entity_id": entity_id, "option": value}
        )
        await asyncio.sleep(1)
        actual = self._get_state(entity_id)
        if actual is None:
            _LOG.warning(
                "%s: entity %s vanished from HA state machine after write", name, entity_id
            )
            log_givtcp_write(_LOG, step, entity_id, value, "unavailable", False)
            return
        accepted = actual.state == value
        log_givtcp_write(_LOG, step, entity_id, value, actual.state, accepted)
        if not accepted:
            _LOG.warning("%s: wrote %r but read back %r", name, value, actual.state)

    async def _givtcp_set_number(
        self,
        entity_id: str | None,
        value: int,
        name: str,
        step: int = 0,
    ) -> None:
        """Set a GivTCP number entity, verify the write, and log both."""
        if not entity_id:
            return
        await self._call_service("number", "set_value", {"entity_id": entity_id, "value": value})
        await asyncio.sleep(1)
        actual = self._get_state(entity_id)
        try:
            actual_val = int(float(actual.state)) if actual else None
        except (ValueError, TypeError):
            actual_val = None
        accepted = actual_val == value
        log_givtcp_write(
            _LOG, step, entity_id, value, actual.state if actual else "unknown", accepted
        )
        if not accepted:
            _LOG.warning(
                "%s: wrote %d but read back %s",
                name,
                value,
                actual.state if actual else "unknown",
            )

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
        target_entity = cfg.get(CONF_TARGET_SOC_ENTITY)

        if not target_entity:
            _LOG.debug("No target SoC entity configured — skipping charge target write-back")
            return

        if self.data is None or self.data.charge_decision is None:
            _LOG.warning("No charge decision available yet — skipping charge target write-back")
            return

        decision = self.data.charge_decision

        if decision.skip_charge:
            _LOG.info(
                "Charge target write-back: skip_charge=True (%s) — leaving GivTCP unchanged",
                decision.reason,
            )
            return

        target_soc = decision.target_soc
        tariff = build_tariff(cfg)
        if not tariff.rate_periods:
            _LOG.warning(
                "No timed rate periods configured — cannot determine charge window. "
                "Add at least one rate period (e.g. Night) in Settings → Configure."
            )
            return
        cheap = min(tariff.rate_periods, key=lambda p: p.rate)

        if bool(cfg.get(CONF_DRY_RUN, DEFAULT_DRY_RUN)):
            action = (
                f"Would write charge target {target_soc}% for {cheap.name} window "
                f"{cheap.start.strftime('%H:%M')}–{cheap.end.strftime('%H:%M')} "
                f"({decision.reason})"
            )
            _LOG.info("DRY RUN: %s", action)
            if self.data is not None:
                self.data.dry_run_last_skipped = action
            return

        _LOG.info(
            "Writing charge target %d%% for %s window %s–%s (reason: %s)",
            target_soc,
            cheap.name,
            cheap.start.strftime("%H:%M"),
            cheap.end.strftime("%H:%M"),
            decision.reason,
        )

        self._create_task(self._async_apply_charge_target(cfg, target_soc, cheap))

    async def _async_apply_charge_target(self, cfg: dict, target_soc: int, cheap_period) -> None:
        """
        Apply charge target and window to GivTCP in the correct order.

        Runs as an async task so it can await each service call.
        Each write is followed by a brief read-back to verify acceptance.
        """
        await self._givtcp_set_switch(
            cfg.get(CONF_ENABLE_CHARGE_SCHEDULE),
            True,
            "enable_charge_schedule",
            step=1,
        )
        start_str = cheap_period.start.strftime("%H:%M:%S")
        end_str = cheap_period.end.strftime("%H:%M:%S")
        await self._givtcp_set_select(
            cfg.get(CONF_CHARGE_START_TIME_ENTITY),
            start_str,
            "charge_start_time",
            step=2,
        )
        await self._givtcp_set_select(
            cfg.get(CONF_CHARGE_END_TIME_ENTITY),
            end_str,
            "charge_end_time",
            step=3,
        )
        await self._givtcp_set_number(
            cfg.get(CONF_TARGET_SOC_ENTITY),
            target_soc,
            "target_soc",
            step=4,
        )
        enable_target = target_soc < 100
        await self._givtcp_set_switch(
            cfg.get(CONF_ENABLE_CHARGE_TARGET),
            enable_target,
            "enable_charge_target",
            step=5,
        )
        _LOG.info(
            "Charge target write-back complete: %d%% window %s–%s enable_target=%s",
            target_soc,
            start_str,
            end_str,
            enable_target,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _effective_cfg(self) -> dict:
        """Merge options over data so tariff edits take immediate effect."""
        cfg = dict(self.entry.data)
        cfg.update(self.entry.options)
        return cfg

    def _collect_raw(self, cfg: dict) -> RawSensorValues:
        """Read all sensor entity states and return as a plain-Python struct."""
        raw = RawSensorValues()
        raw.solar_power_w = self._read_float(cfg.get(CONF_SOLAR_POWER))
        raw.battery_soc = self._read_float(cfg.get(CONF_BATTERY_SOC))
        raw.battery_power_w = self._read_float(cfg.get(CONF_BATTERY_POWER))
        # GivTCP v3 uses positive=export, negative=import.
        # Negate to match internal convention (positive=import, negative=export).
        raw.grid_power_w = -self._read_float(cfg.get(CONF_GRID_POWER))
        raw.house_load_w = self._read_float(cfg.get(CONF_HOUSE_LOAD))
        raw.inverter_max_w = cfg.get(CONF_INVERTER_MAX_OUTPUT, DEFAULT_INVERTER_MAX_OUTPUT) * 1000
        raw.battery_capacity_kwh = float(cfg.get(CONF_BATTERY_CAPACITY, DEFAULT_BATTERY_CAPACITY))

        raw.immersion_wattage_w = float(cfg.get(CONF_IMMERSION_WATTAGE, DEFAULT_IMMERSION_WATTAGE))
        raw.immersion_on = self._read_bool(cfg.get(CONF_IMMERSION_SWITCH))
        raw.immersion_target_temp = self.immersion_target_temp
        raw.immersion_min_temp = self.immersion_min_temp
        raw.immersion_hysteresis_c = self.immersion_hysteresis_c

        temp_eid = cfg.get(CONF_IMMERSION_TEMP_SENSOR)
        if temp_eid:
            raw.immersion_temp = self._read_optional_float(temp_eid)

        forecast_eid = cfg.get(CONF_FORECAST_ENTITY)
        if forecast_eid:
            v = self._read_optional_float(forecast_eid)
            raw.forecast_kwh_tomorrow = v if v is not None and v >= 0 else None

        if self._ev_charger is not None:
            raw.ev_power_w = self._ev_charger.power_w
            raw.ev_plugged_in = self._ev_charger.is_plugged_in

        return raw

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
        """Apply an EV charger mode change via HA service call."""
        if (
            target_mode is None
            or self._ev_charger is None
            or not self._ev_charger.charge_mode_entity
        ):
            return
        current = (self._ev_charger.charge_mode or "").strip()
        if current == target_mode:
            return

        cfg = self._effective_cfg()
        action = (
            f"Would set {self._ev_charger.display_name} → {target_mode} (currently {current!r})"
        )
        if bool(cfg.get(CONF_DRY_RUN, DEFAULT_DRY_RUN)):
            _LOG.info("DRY RUN: %s", action)
            if self.data is not None:
                self.data.dry_run_last_skipped = action
            return

        _LOG.info(
            "EV charger action: %s → %s",
            self._ev_charger.display_name,
            target_mode,
        )
        self._create_task(
            self._call_service(
                "select",
                "select_option",
                {"entity_id": self._ev_charger.charge_mode_entity, "option": target_mode},
                blocking=False,
            )
        )

    # ── Main update cycle ─────────────────────────────────────────────────────

    async def _maybe_apply_cheap_rate_floor(
        self,
        now: datetime,
        raw,
        cfg: dict,
    ) -> str:
        """During cheap rate hours, top up battery if it drops below the floor.

        Optimises for the cheapest available window (e.g. Nightboost over Night):
        - In the cheapest timed period: apply the full floor (default 40%).
        - In a cheaper-than-base but not cheapest period: only top up if battery
          is near the minimum SoC — otherwise wait for the cheapest window.

        Called every 30s cycle. Only writes to the inverter once per night
        (flag resets at midnight).
        """
        floor_soc = int(cfg.get(CONF_CHEAP_RATE_FLOOR_SOC, DEFAULT_CHEAP_RATE_FLOOR_SOC))
        if floor_soc <= 0:
            return ""

        tariff = build_tariff(cfg)
        current_period = tariff.get_current_rate(now)

        # Only active during a timed period cheaper than the base rate
        if current_period.rate >= tariff.base_rate:
            return ""

        # Determine whether we are in the cheapest available window
        cheapest = tariff.get_cheapest_rate() if tariff.rate_periods else current_period
        in_cheapest = current_period.rate <= cheapest.rate

        if in_cheapest:
            # Cheapest window — apply full floor
            effective_floor = floor_soc
        else:
            # Cheaper than base but a better rate is coming or was available.
            # Only top up for genuine emergencies (near minimum SoC).
            min_soc = int(cfg.get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC))
            emergency_floor = min_soc + 5
            if raw.battery_soc >= emergency_floor:
                # Not critical — tell the sensor we are waiting
                return (
                    f"Battery at {raw.battery_soc:.0f}% during {current_period.name} — "
                    f"waiting for cheapest rate ({cheapest.name} "
                    f"{cheapest.start.strftime('%H:%M')}–{cheapest.end.strftime('%H:%M')})"
                )
            effective_floor = emergency_floor

        if raw.battery_soc >= effective_floor:
            return ""

        if self._floor_top_up_applied:
            return (
                f"Floor already applied this window — battery at {raw.battery_soc:.0f}%, "
                f"floor {effective_floor}%"
            )

        status = (
            f"Battery at {raw.battery_soc:.0f}% during {current_period.name} — "
            f"topping up to {effective_floor}%"
        )
        _LOG.info("Cheap rate floor: %s", status)

        target_entity = cfg.get(CONF_TARGET_SOC_ENTITY)
        if not target_entity:
            _LOG.warning("Cheap rate floor triggered but no target SoC entity configured")
            return status

        if bool(cfg.get(CONF_DRY_RUN, DEFAULT_DRY_RUN)):
            _LOG.info("DRY RUN: %s", status)
            return f"DRY RUN: {status}"

        # Write the new target — charge schedule already set by the nightly write-back,
        # so we only need to update the target SoC value.
        try:
            await self._call_service(
                "number",
                "set_value",
                {"entity_id": target_entity, "value": str(effective_floor)},
            )
            enable_entity = target_entity.replace("target_soc", "enable_charge_target").replace(
                "number.", "switch."
            )
            await self._call_service("switch", "turn_on", {"entity_id": enable_entity})
        except Exception:
            _LOG.exception("Cheap rate floor: failed to write target to inverter")
            return f"Error writing floor — {status}"

        self._floor_top_up_applied = True
        return status

    async def _async_update_data(self) -> CoordinatorData:
        """
        Called every UPDATE_INTERVAL_SECONDS by the HA coordinator framework.

        Reads HA state → calls engine → applies HA side-effects.
        """
        self._update_cycle += 1
        if self._update_cycle % 10 == 0:
            self.hass.async_create_task(self._acc.async_save())
        cfg = self._effective_cfg()

        # 1. Refresh EV charger discovery
        self._maybe_rediscover_ev()

        # 2. Read all sensor values from HA
        raw = self._collect_raw(cfg)

        # 3. Update EV charger state now we have battery_power_w
        if self._ev_charger is not None:
            update_charger_state(self._get_state, self._ev_charger, raw.battery_power_w)
            raw.ev_power_w = self._ev_charger.power_w
            raw.ev_plugged_in = self._ev_charger.is_plugged_in

        # 4. Run the pure logic engine
        now = dt_util.as_local(datetime.now(timezone.utc))
        data, ev_target_mode = build_coordinator_data(
            raw=raw,
            cfg=cfg,
            acc=self._acc.today,
            battery_stats=self._battery_stats,
            last_soc=self._last_soc,
            last_update_time=self._last_update,
            now=now,
            ev_charger=self._ev_charger,
            override_charge_target=self.override_charge_target,
            override_immersion=self.override_immersion,
            override_skip_charge=self.override_skip_charge,
            solar_fractions=self._solar_fractions,
            last_reset_time=self._last_reset_time,
            acc_week=self._acc.week,
            acc_month=self._acc.month,
            acc_yesterday=self._acc.yesterday,
            solar_forecast_kwh_today=self._acc.today_forecast_kwh,
            yesterday_forecast_accuracy_pct=self._acc.yesterday_forecast_accuracy_pct,
            forecast_accuracy_7day_avg_pct=self._acc.forecast_accuracy_7day_avg_pct,
        )

        # 5. Cheap rate floor — top up if battery drops below minimum during cheap hours
        data.cheap_rate_floor_status = await self._maybe_apply_cheap_rate_floor(now, raw, cfg)

        # 6. Verbose logging (debug-level, opt-in via config)
        log_cycle(_LOG, self._update_cycle, raw, data, now)

        # 7. Update coordinator state for next cycle
        self._last_soc = raw.battery_soc
        self._last_update = now

        # 8. Apply HA side-effects requested by the engine
        self._apply_ev_action(ev_target_mode)

        return data
