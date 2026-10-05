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
import time
from datetime import datetime, timedelta, timezone
from datetime import time as dtime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
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
    GIVTCP_MAX_CHARGE_TARGET_PCT,
    GIVTCP_MAX_WRITE_RETRIES,
    GIVTCP_MIN_CHARGE_TARGET_PCT,
    GIVTCP_MIN_WRITE_INTERVAL_S,
    GIVTCP_WRITE_LIFETIME_WARN,
    GIVTCP_WRITE_RETRY_SLEEP_S,
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
    discover_battery_cycle_entities,
    discover_ev_chargers,
    update_charger_state,
)
from .logging import GivLogger, get_logger, log_cycle, log_givtcp_write
from .repairs import (
    MIN_SOC_HIGH_THRESHOLD,
    async_create_givtcp_missing_issue,
    async_create_min_soc_issue,
    async_delete_givtcp_missing_issue,
    async_delete_min_soc_issue,
)

_LOG = get_logger(__name__)

_REDISCOVER_EVERY_N_CYCLES = 10  # 10 × 30s ≈ 5 minutes


def _state_as_int(state) -> int | None:
    """Return a state object's value as an int, or None if absent or not numeric."""
    try:
        return int(float(state.state)) if state else None
    except (ValueError, TypeError):
        return None


def _clamp_charge_target(target_soc: float) -> int:
    """Limit a charge target to the range GivTCP accepts."""
    return max(
        GIVTCP_MIN_CHARGE_TARGET_PCT, min(GIVTCP_MAX_CHARGE_TARGET_PCT, int(target_soc))
    )


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
        self._acc = AccumulationStore(hass, self._configured_bill_start_day())
        self._battery_stats = BatteryStats()
        self._last_soc: float | None = None
        self._last_update: datetime | None = None
        self._update_cycle: int = 0
        self._floor_top_up_applied: bool = False
        self.export_rate: float = 0.0
        self._ev_charger: EVCharger | None = None
        self._battery_cycle_entities: list[str] = []

        # Manual charge target override. The switch sets the flag, the number sets the
        # value. override_charge_target (property) is the only thing the engine sees.
        self.override_charge_enabled: bool = False
        self.override_charge_value: int = DEFAULT_OVERNIGHT_CHARGE_TARGET
        # Register write tracking — GivEnergy inverters have ~1M lifetime writes
        self._register_write_count: int = 0
        # Timestamp of last write per (entity, value) — enforces GIVTCP_MIN_WRITE_INTERVAL_S
        self._last_write_time: dict[tuple[str, object], float] = {}
        # EMA-smoothed solar power (α=0.5) — used for surplus divert decisions
        # to prevent chasing transient cloud gaps. Raw value used for accumulation.
        self._smoothed_solar_w: float = 0.0
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
        self._givtcp_was_unavailable: bool = False
        self._inputs_unavailable_since: datetime | None = None
        # When True, manual override stays on until water reaches target temp, then releases.
        self._immersion_manual_run_to_target: bool = False
        # Cooldown: timestamp until which auto switch decisions are suppressed.
        # Manual on/off via the managed switch bypasses this and resets the timer.
        self._immersion_cooldown_until: datetime | None = None
        # Tracks what the coordinator last wrote to the real switch so external
        # state changes (automation, physical button) can be detected.
        self._last_immersion_coordinator_write: bool | None = None

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
    def override_charge_target(self) -> int | None:
        """Effective charge target override: the value while enabled, else None (automatic)."""
        return self.override_charge_value if self.override_charge_enabled else None

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
    # Each helper:
    #   1. Reads current state — skips the write if already at the target value
    #   2. Writes and retries up to GIVTCP_MAX_WRITE_RETRIES times on failure
    #   3. Increments the register write counter (hardware lifetime tracking)
    #
    # Each helper returns True when the entity is at, or was sent, the requested
    # value, and False when the service call raised or the entity is unusable.
    # A read-back that never matches is logged but still counts as sent, because
    # GivTCP can be slow to publish the new state.
    #
    # GivEnergy inverters have ~1M total register write capacity. The counter
    # is surfaced as a diagnostic sensor so users can monitor it.

    def _increment_write_count(self) -> None:
        count = getattr(self, "_register_write_count", 0) + 1
        self._register_write_count = count
        self._acc.state.register_write_count = count
        if count == GIVTCP_WRITE_LIFETIME_WARN:
            _LOG.warning(
                "GivTCP register write count has reached %d — approximately 50%% of the "
                "inverter's rated lifetime. Review automation frequency.",
                self._register_write_count,
            )

    def _write_cooldown_active(self, entity_id: str, name: str, value) -> bool:
        """Return True if this value was written to the entity inside the cooldown window."""
        last = self._last_write_time.get((entity_id, value))
        if last is None:
            return False
        elapsed = time.monotonic() - last
        if elapsed < GIVTCP_MIN_WRITE_INTERVAL_S:
            _LOG.debug(
                "%s: write cooldown active — %.0fs remaining before next write is allowed",
                name,
                GIVTCP_MIN_WRITE_INTERVAL_S - elapsed,
            )
            return True
        return False

    async def _givtcp_call_service(
        self, domain: str, service: str, data: dict, name: str, value
    ) -> bool:
        """Call a write service, returning False and logging if it raises."""
        entity_id = data["entity_id"]
        try:
            await self._call_service(domain, service, data)
        except HomeAssistantError as err:
            _LOG.warning("%s: %s.%s on %s failed: %s", name, domain, service, entity_id, err)
        except Exception:
            _LOG.exception(
                "%s: unexpected error calling %s.%s on %s", name, domain, service, entity_id
            )
        else:
            self._increment_write_count()
            return True
        self._last_write_time.pop((entity_id, value), None)
        return False

    async def _givtcp_set_switch(
        self,
        entity_id: str | None,
        state: bool,
        name: str,
        step: int = 0,
    ) -> bool:
        """Set a GivTCP switch entity with read-before-write and retry."""
        if not entity_id:
            return False
        # Read-before-write: skip if already at the desired state
        current = self._get_state(entity_id)
        if current is not None:
            current_on = current.state == "on"
            if current_on == state:
                _LOG.debug("%s: already %s — skipping write", name, "on" if state else "off")
                return True
        if self._write_cooldown_active(entity_id, name, state):
            return True

        self._last_write_time[(entity_id, state)] = time.monotonic()
        service = "turn_on" if state else "turn_off"
        accepted = False
        for attempt in range(1, GIVTCP_MAX_WRITE_RETRIES + 1):
            if not await self._givtcp_call_service(
                "switch", service, {"entity_id": entity_id}, name, state
            ):
                return False
            await asyncio.sleep(GIVTCP_WRITE_RETRY_SLEEP_S)
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
            if accepted:
                break
            if attempt < GIVTCP_MAX_WRITE_RETRIES:
                _LOG.warning(
                    "%s: attempt %d/%d — wrote %s but read back %s, retrying",
                    name,
                    attempt,
                    GIVTCP_MAX_WRITE_RETRIES,
                    "on" if state else "off",
                    actual.state if actual else "unknown",
                )
        if not accepted:
            _LOG.warning(
                "%s: wrote %s but could not confirm after %d attempts",
                name,
                "on" if state else "off",
                GIVTCP_MAX_WRITE_RETRIES,
            )
        return True

    async def _givtcp_set_select(
        self,
        entity_id: str | None,
        value: str,
        name: str,
        step: int = 0,
    ) -> bool:
        """Set a GivTCP select entity with read-before-write and retry."""
        if not entity_id:
            return False
        # Read-before-write: skip if already correct
        current = self._get_state(entity_id)
        if current is not None and current.state == value:
            _LOG.debug("%s: already %r — skipping write", name, value)
            return True
        if self._write_cooldown_active(entity_id, name, value):
            return True

        self._last_write_time[(entity_id, value)] = time.monotonic()
        accepted = False
        for attempt in range(1, GIVTCP_MAX_WRITE_RETRIES + 1):
            if not await self._givtcp_call_service(
                "select", "select_option", {"entity_id": entity_id, "option": value}, name, value
            ):
                return False
            await asyncio.sleep(GIVTCP_WRITE_RETRY_SLEEP_S)
            actual = self._get_state(entity_id)
            if actual is None:
                _LOG.warning(
                    "%s: entity %s vanished from HA state machine after write", name, entity_id
                )
                log_givtcp_write(_LOG, step, entity_id, value, "unavailable", False)
                return False
            accepted = actual.state == value
            log_givtcp_write(_LOG, step, entity_id, value, actual.state, accepted)
            if accepted:
                break
            if attempt < GIVTCP_MAX_WRITE_RETRIES:
                _LOG.warning(
                    "%s: attempt %d/%d — wrote %r but read back %r, retrying",
                    name,
                    attempt,
                    GIVTCP_MAX_WRITE_RETRIES,
                    value,
                    actual.state,
                )
        if not accepted:
            _LOG.warning(
                "%s: wrote %r but could not confirm after %d attempts",
                name,
                value,
                GIVTCP_MAX_WRITE_RETRIES,
            )
        return True

    async def _givtcp_set_number(
        self,
        entity_id: str | None,
        value: int,
        name: str,
        step: int = 0,
    ) -> bool:
        """Set a GivTCP number entity with read-before-write and retry."""
        if not entity_id:
            return False
        # Read-before-write: skip if already at the target value
        if _state_as_int(self._get_state(entity_id)) == value:
            _LOG.debug("%s: already %d — skipping write", name, value)
            return True
        if self._write_cooldown_active(entity_id, name, value):
            return True

        self._last_write_time[(entity_id, value)] = time.monotonic()
        accepted = False
        for attempt in range(1, GIVTCP_MAX_WRITE_RETRIES + 1):
            if not await self._givtcp_call_service(
                "number", "set_value", {"entity_id": entity_id, "value": value}, name, value
            ):
                return False
            await asyncio.sleep(GIVTCP_WRITE_RETRY_SLEEP_S)
            actual = self._get_state(entity_id)
            accepted = _state_as_int(actual) == value
            log_givtcp_write(
                _LOG, step, entity_id, value, actual.state if actual else "unknown", accepted
            )
            if accepted:
                break
            if attempt < GIVTCP_MAX_WRITE_RETRIES:
                _LOG.warning(
                    "%s: attempt %d/%d — wrote %d but read back %s, retrying",
                    name,
                    attempt,
                    GIVTCP_MAX_WRITE_RETRIES,
                    value,
                    actual.state if actual else "unknown",
                )
        if not accepted:
            _LOG.warning(
                "%s: wrote %d but could not confirm after %d attempts",
                name,
                value,
                GIVTCP_MAX_WRITE_RETRIES,
            )
        return True

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
        now = dt_util.as_local(datetime.now(timezone.utc))
        if self._acc.roll_forward(now):
            await self._acc.async_save()
        self._last_reset_time = self._acc.state.last_reset_iso
        self.entry.async_on_unload(self.async_flush)
        self.entry.async_on_unload(
            self.hass.bus.async_listen(EVENT_HOMEASSISTANT_FINAL_WRITE, self._async_final_write)
        )

    async def async_flush(self) -> None:
        """Write the accumulators and battery statistics to storage now."""
        self._acc.save_battery_stats(self._battery_stats)
        await self._acc.async_save()

    async def _async_final_write(self, _event: Event) -> None:
        await self.async_flush()

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
            # Write the minimum SoC as the charge target so the battery can discharge
            # freely overnight. If we leave the old target (e.g. 80%) in GivTCP the
            # inverter will hold the battery at that level and import from grid instead
            # of discharging.
            tariff = build_tariff(cfg)
            if tariff.rate_periods:
                min_soc = int(cfg.get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC))
                cheap = min(tariff.rate_periods, key=lambda p: p.rate)
                if bool(cfg.get(CONF_DRY_RUN, DEFAULT_DRY_RUN)):
                    _LOG.info(
                        "DRY RUN: skip_charge=True — would write min target %d%% (%s)",
                        min_soc,
                        decision.reason,
                    )
                else:
                    _LOG.info(
                        "skip_charge=True — writing min target %d%% to allow free discharge (%s)",
                        min_soc,
                        decision.reason,
                    )
                    self._create_task(
                        self._async_apply_charge_target(cfg, min_soc, cheap)
                    )
            else:
                _LOG.info(
                    "skip_charge=True (%s) — no rate periods, leaving GivTCP unchanged",
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
        The charge target is not enabled when writing the target number failed,
        because the inverter would then limit charging to a stale target.
        """
        clamped = _clamp_charge_target(target_soc)
        if clamped != target_soc:
            _LOG.warning(
                "Charge target %s%% is outside the range GivTCP accepts (%d-%d%%), using %d%%",
                target_soc,
                GIVTCP_MIN_CHARGE_TARGET_PCT,
                GIVTCP_MAX_CHARGE_TARGET_PCT,
                clamped,
            )
        target_soc = clamped
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
        target_written = await self._givtcp_set_number(
            cfg.get(CONF_TARGET_SOC_ENTITY),
            target_soc,
            "target_soc",
            step=4,
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
        # getattr fallback handles subclasses that don't call our __init__ (e.g. FakeCoordinator).
        prev_smoothed = getattr(self, "_smoothed_solar_w", 0.0)
        if "solar_power" not in unavailable:
            self._smoothed_solar_w = 0.5 * prev_smoothed + 0.5 * raw.solar_power_w
        raw.smoothed_solar_power_w = getattr(self, "_smoothed_solar_w", 0.0)
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
            if raw.immersion_temp is None:
                unavailable.append("immersion_temp")
        raw.unavailable_inputs = tuple(unavailable)

        forecast_eid = cfg.get(CONF_FORECAST_ENTITY)
        if forecast_eid:
            v = self._read_optional_float(forecast_eid)
            raw.forecast_kwh_tomorrow = v if v is not None and v >= 0 else None

        forecast_p10_eid = cfg.get(CONF_FORECAST_ENTITY_P10)
        if forecast_p10_eid:
            v = self._read_optional_float(forecast_p10_eid)
            raw.forecast_kwh_p10 = v if v is not None and v >= 0 else None

        forecast_d2_eid = cfg.get(CONF_FORECAST_ENTITY_D2)
        if forecast_d2_eid:
            v = self._read_optional_float(forecast_d2_eid)
            raw.forecast_kwh_d2 = v if v is not None and v >= 0 else None

        carbon_eid = cfg.get(CONF_CARBON_INTENSITY_ENTITY)
        if carbon_eid:
            raw.carbon_intensity_gco2 = self._read_optional_float(carbon_eid)

        inverter_temp_eid = cfg.get(CONF_INVERTER_TEMP_ENTITY)
        if inverter_temp_eid:
            raw.inverter_temp = self._read_optional_float(inverter_temp_eid)

        if self._ev_charger is not None:
            raw.ev_power_w = self._ev_charger.power_w
            raw.ev_plugged_in = self._ev_charger.is_plugged_in

        raw.battery_lifetime_cycles = self._read_battery_lifetime_cycles()

        # GivTCP daily energy counters — present on GivTCP v2.1+ and v3.
        # Entity IDs are derived from the inverter serial stored in config.
        # _read_optional_float returns None for missing/unavailable entities;
        # the engine falls back to power-integration when any counter is None.
        serial = cfg.get(CONF_INVERTER_SERIAL)
        if serial:
            pfx = f"sensor.givtcp_{serial}"
            raw.solar_energy_today_kwh = self._read_optional_float(f"{pfx}_pv_energy_today_kwh")
            raw.import_energy_today_kwh = self._read_optional_float(
                f"{pfx}_import_energy_today_kwh"
            )
            raw.export_energy_today_kwh = self._read_optional_float(
                f"{pfx}_export_energy_today_kwh"
            )
            # GivTCP names these battery_charge_energy_today_kwh and
            # battery_discharge_energy_today_kwh. The unprefixed names are kept
            # as a fallback for older GivTCP versions.
            raw.charge_energy_today_kwh = self._read_first_optional_float(
                f"{pfx}_battery_charge_energy_today_kwh", f"{pfx}_charge_energy_today_kwh"
            )
            raw.discharge_energy_today_kwh = self._read_first_optional_float(
                f"{pfx}_battery_discharge_energy_today_kwh",
                f"{pfx}_discharge_energy_today_kwh",
            )
            raw.load_energy_today_kwh = self._read_optional_float(f"{pfx}_load_energy_today_kwh")

        return raw

    def _track_input_outage(self, raw: RawSensorValues, now: datetime) -> None:
        """Record how long the required inputs have been continuously unavailable."""
        if not raw.unavailable_inputs:
            self._inputs_unavailable_since = None
            raw.unavailable_for_s = 0.0
            return
        if self._inputs_unavailable_since is None:
            self._inputs_unavailable_since = now
        raw.unavailable_for_s = max(0.0, (now - self._inputs_unavailable_since).total_seconds())
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

        entity_id = self._ev_charger.charge_mode_entity
        if self._write_cooldown_active(entity_id, self._ev_charger.display_name, target_mode):
            return
        self._last_write_time[(entity_id, target_mode)] = time.monotonic()

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

    def _maybe_release_immersion_run_to_target(
        self, immersion_temp: float | None
    ) -> None:
        """Release manual run-to-target override once water reaches target temperature."""
        if not self._immersion_manual_run_to_target:
            return
        if immersion_temp is not None and immersion_temp >= self.immersion_target_temp:
            _LOG.info(
                "Immersion reached target %.1f°C — releasing manual override",
                immersion_temp,
            )
            self._immersion_manual_run_to_target = False
            self.override_immersion = None

    async def _write_floor_target(self, cfg: dict, target_entity: str, soc: int) -> bool:
        """Write SoC target and enable charge target switch for cheap rate floor top-up.

        Uses the same read-before-write, cooldown, write counting and read-back
        helpers as the overnight charge target so the inverter registers are not
        written more often than necessary. Returns False, without enabling the
        charge target, when the target could not be written.
        """
        soc = _clamp_charge_target(soc)
        if not await self._givtcp_set_number(target_entity, soc, "Cheap rate floor target"):
            return False
        return await self._givtcp_set_switch(
            cfg.get(CONF_ENABLE_CHARGE_TARGET), True, "Cheap rate floor charge target enable"
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

        if not await self._write_floor_target(cfg, target_entity, effective_floor):
            return f"Error writing floor — {status}"

        self._floor_top_up_applied = True
        return status

    def _check_config_repair_issues(self, cfg: dict) -> None:
        """Raise or clear repair issues for misconfigured values that won't self-heal."""
        min_soc = int(cfg.get(CONF_BATTERY_MIN_SOC, DEFAULT_BATTERY_MIN_SOC))
        if min_soc > MIN_SOC_HIGH_THRESHOLD:
            async_create_min_soc_issue(self.hass, min_soc)
        else:
            async_delete_min_soc_issue(self.hass)

    async def _async_update_data(self) -> CoordinatorData:
        """
        Called every UPDATE_INTERVAL_SECONDS by the HA coordinator framework.

        Reads HA state → calls engine → applies HA side-effects.
        """
        self._update_cycle += 1
        if self._update_cycle % 10 == 0:
            self._acc.save_battery_stats(self._battery_stats)
            self._acc.schedule_save()
        cfg = self._effective_cfg()
        self._acc.update_bill_start_day(self._configured_bill_start_day(cfg))
        self.export_rate = float(cfg.get(CONF_EXPORT_RATE, 0.0))

        # 0. Validate config — raise repair issues for values that won't self-heal.
        self._check_config_repair_issues(cfg)

        # 1. Check GivTCP is publishing (entity-unavailable quality scale item)
        #    Both sensors must be stale before raising — a single brief interruption
        #    should not mark the entire integration unavailable.
        _solar_eid = cfg.get(CONF_SOLAR_POWER)
        _batt_eid = cfg.get(CONF_BATTERY_SOC)
        _solar_st = self._get_state(_solar_eid) if _solar_eid else None
        _batt_st = self._get_state(_batt_eid) if _batt_eid else None
        _stale = ("unavailable", "unknown")
        _solar_missing = _solar_st is None
        _batt_missing = _batt_st is None
        if (_solar_st is None or _solar_st.state in _stale) and (
            _batt_st is None or _batt_st.state in _stale
        ):
            if not self._givtcp_was_unavailable:
                _LOG.warning(
                    "GivTCP has stopped publishing data — solar and battery sensors "
                    "are unavailable. Check GivTCP is running and MQTT is connected."
                )
                self._givtcp_was_unavailable = True
            if _solar_missing and _batt_missing:
                async_create_givtcp_missing_issue(self.hass)
            raise UpdateFailed(
                translation_domain="givenergy_inverter_manager",
                translation_key="givtcp_unavailable",
            )

        if self._givtcp_was_unavailable:
            _LOG.info("GivTCP is publishing data again — resuming normal operation.")
            self._givtcp_was_unavailable = False
        async_delete_givtcp_missing_issue(self.hass)

        # 2. Refresh EV charger discovery
        self._maybe_rediscover_ev()
        self._maybe_rediscover_battery_cycles()

        # 3. Read all sensor values from HA
        raw = self._collect_raw(cfg)

        # 4. Update EV charger state now we have battery_power_w
        if self._ev_charger is not None:
            update_charger_state(self._get_state, self._ev_charger, raw.battery_power_w)
            raw.ev_power_w = self._ev_charger.power_w
            raw.ev_plugged_in = self._ev_charger.is_plugged_in

        # 5a. Release manual run-to-target override once water reaches target temperature.
        self._maybe_release_immersion_run_to_target(raw.immersion_temp)

        # 5. Run the pure logic engine
        now = dt_util.as_local(datetime.now(timezone.utc))

        self._track_input_outage(raw, now)

        # 5a. Update per-slot baseline load for this 30-min window.
        if self._last_update is not None:
            elapsed_h = (now - self._last_update).total_seconds() / 3600
            slot = now.hour * 2 + now.minute // 30
            immersion_w = raw.immersion_wattage_w if raw.immersion_on else 0.0
            baseline_w = max(0.0, raw.house_load_w - immersion_w - raw.ev_power_w)
            self._acc.record_slot_load(now, slot, (baseline_w / 1000) * elapsed_h, elapsed_h)

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
            acc_year=self._acc.year,
            acc_yesterday=self._acc.yesterday,
            solar_forecast_kwh_today=self._acc.today_forecast_kwh,
            yesterday_forecast_accuracy_pct=self._acc.yesterday_forecast_accuracy_pct,
            forecast_accuracy_7day_avg_pct=self._acc.forecast_accuracy_7day_avg_pct,
            load_profile=self._acc.slot_load_profile((now + timedelta(days=1)).weekday()),
            forecast_correction=self._acc.forecast_correction_factor,
        )

        data.week_start_time = self._acc.state.week_start_iso
        data.month_start_time = self._acc.state.month_start_iso
        data.year_start_time = self._acc.state.year_start_iso
        data.register_write_count = getattr(self, "_register_write_count", 0)
        data.trailing_12m_export_kwh = self._acc.trailing_12m_export_kwh
        data.trailing_12m_solar_kwh = self._acc.trailing_12m_solar_kwh
        data.trailing_12m_import_kwh = self._acc.trailing_12m_import_kwh
        data.trailing_12m_import_cost = self._acc.trailing_12m_import_cost
        data.trailing_12m_export_earnings = self._acc.trailing_12m_export_earnings

        # 5b. Annotate divert reason when manual run-to-target is still active.
        if self._immersion_manual_run_to_target and data.should_divert_immersion:
            data.divert_reason = (
                f"Manual — running to {self.immersion_target_temp:.0f}°C"
                + (
                    f" ({raw.immersion_temp:.1f}°C now)"
                    if raw.immersion_temp is not None
                    else ""
                )
            )

        self._acc.on_raw_forecast(raw.forecast_kwh_tomorrow)
        self._acc.note_clipping(data.is_clipping)

        # 6. Record forecast for accuracy tracking (sets solar_forecast_today sensor)
        if data.charge_decision is not None and data.charge_decision.forecast_kwh > 0:
            self._acc.on_charge_decision(data.charge_decision.forecast_kwh)

        # 7. Cheap rate floor — top up if battery drops below minimum during cheap hours
        data.cheap_rate_floor_status = await self._maybe_apply_cheap_rate_floor(now, raw, cfg)

        # 8. Verbose logging (debug-level, opt-in via config)
        log_cycle(_LOG, self._update_cycle, raw, data, now)

        # 9. Update coordinator state for next cycle
        self._last_soc = None if "battery_soc" in raw.unavailable_inputs else raw.battery_soc
        self._last_update = now

        # 10. Apply HA side-effects requested by the engine
        self._apply_ev_action(ev_target_mode)

        return data
