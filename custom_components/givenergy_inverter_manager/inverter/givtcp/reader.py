"""
reader.py: read a GivTCP inverter into InverterValues and say whether its feed is live.

This is the only place the grid and battery signs are negated. GivTCP publishes grid power as
positive for export and battery power as positive for discharging. InverterValues uses the
integration's convention: grid positive is import, battery positive is charging.

Entity ids for the daily counters, the charge rate, the status and the data age are built
from the inverter serial in the config.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from ...const import (
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_INVERTER_SERIAL,
    CONF_INVERTER_TEMP_ENTITY,
    CONF_SOLAR_POWER,
    GIVTCP_FROZEN_AFTER_S,
)
from ...core.feed_freshness import frozen_age_s, newest_report
from ...core.inverter_values import FeedState, FeedStatus, InverterValues
from ...logging import get_logger
from .discovery import GIVTCP_PREFIX, inverter_temperature_entity_ids

_LOG = get_logger(__name__)

GetState = Callable[[str], Any]

# The entities read every cycle that GivTCP keeps publishing. The feed is frozen only when none
# of them has reported lately, so one that GivTCP publishes less often cannot trip it alone.
_FEED_KEYS = (
    CONF_SOLAR_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_POWER,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
)
_UNREADABLE = ("unavailable", "unknown", "")
PAUSED_STATUS = "paused"


def _is_stale(state) -> bool:
    """True when an entity is missing or reports unavailable or unknown."""
    return state is None or state.state in ("unavailable", "unknown")


class GivTCPReader:
    """Reads GivTCP entity states through one callable, so tests need no Home Assistant."""

    def __init__(self, get_state: GetState) -> None:
        self._get_state = get_state
        self.battery_cycle_entities: list[str] = []

    # ── Typed state reads ─────────────────────────────────────────────────────

    def _state(self, entity_id: str | None):
        return self._get_state(entity_id) if entity_id else None

    def _float(self, entity_id: str | None, default: float = 0.0) -> float:
        """Read a numeric entity state safely, returning default if unavailable."""
        if not entity_id:
            return default
        state = self._get_state(entity_id)
        if state is None:
            _LOG.debug("Entity %s not found in HA state machine", entity_id)
            return default
        if state.state in _UNREADABLE:
            _LOG.debug("Entity %s is %s", entity_id, state.state or "empty")
            return default
        try:
            return float(state.state)
        except (ValueError, TypeError):
            _LOG.warning("Entity %s has non-numeric state %r", entity_id, state.state)
            return default

    def _optional_float(self, entity_id: str | None) -> float | None:
        """Read a float state, returning None if entity missing, unavailable, or unknown."""
        state = self._state(entity_id)
        if state is None or state.state in _UNREADABLE:
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _first_optional_float(self, *entity_ids: str) -> float | None:
        """Return the first entity id that has a numeric state, else None."""
        for entity_id in entity_ids:
            value = self._optional_float(entity_id)
            if value is not None:
                return value
        return None

    def _tracked(self, entity_id: str | None, name: str, unavailable: list[str]) -> float:
        """Read a float state, recording name in unavailable and returning 0.0 if it is missing."""
        value = self._optional_float(entity_id)
        if value is None:
            unavailable.append(name)
            return 0.0
        return value

    # ── The read ──────────────────────────────────────────────────────────────

    def read(self, cfg: Mapping[str, Any]) -> InverterValues:
        """One read of the inverter, in the integration's sign convention."""
        unavailable: list[str] = []
        solar = self._tracked(cfg.get(CONF_SOLAR_POWER), "solar_power", unavailable)
        soc = self._tracked(cfg.get(CONF_BATTERY_SOC), "battery_soc", unavailable)
        # GivTCP reports battery power as positive=discharging, negative=charging.
        # Negate to match internal convention (positive=charging, negative=discharging).
        # Subtracting from 0.0 avoids a -0.0 reading when the sensor is idle or missing.
        battery_power = 0.0 - self._tracked(
            cfg.get(CONF_BATTERY_POWER), "battery_power", unavailable
        )
        # GivTCP v3 uses positive=export, negative=import.
        # Negate to match internal convention (positive=import, negative=export).
        grid_power = -self._float(cfg.get(CONF_GRID_POWER))
        house_load = self._tracked(cfg.get(CONF_HOUSE_LOAD), "house_load", unavailable)
        return InverterValues(
            solar_power_w=solar,
            battery_soc=soc,
            battery_power_w=battery_power,
            grid_power_w=grid_power,
            house_load_w=house_load,
            inverter_temp=self._inverter_temperature(cfg),
            battery_lifetime_cycles=self._battery_lifetime_cycles(),
            battery_charge_rate_w=self._charge_rate_w(cfg),
            data_age_s=self._data_age_s(cfg),
            unavailable_inputs=tuple(unavailable),
            **self._daily_counters(cfg),
        )

    def _inverter_temperature(self, cfg: Mapping[str, Any]) -> float | None:
        """The inverter temperature: the chosen entity, else GivTCP's, found from the serial.

        An install set up before GivTCP published the temperature has no entity stored.
        """
        entity_ids = [cfg.get(CONF_INVERTER_TEMP_ENTITY) or ""]
        serial = cfg.get(CONF_INVERTER_SERIAL)
        if serial:
            entity_ids += inverter_temperature_entity_ids(serial)
        return self._first_optional_float(*entity_ids)

    def _battery_lifetime_cycles(self) -> float | None:
        """Highest BMS cycle counter across the battery packs, None if none is readable.

        Each pack counts its own cycles, so the packs are not summed.
        """
        values = [self._optional_float(eid) for eid in self.battery_cycle_entities]
        readable = [v for v in values if v is not None and v > 0]
        return max(readable) if readable else None

    def _daily_counters(self, cfg: Mapping[str, Any]) -> dict[str, float | None]:
        """GivTCP daily energy counters, present on GivTCP v2.1+ and v3.

        Entity IDs are derived from the inverter serial stored in config. A missing or
        unavailable entity reads as None, and the engine then falls back to power integration.
        """
        serial = cfg.get(CONF_INVERTER_SERIAL)
        if not serial:
            return {}
        pfx = f"sensor.{GIVTCP_PREFIX}{serial}"
        return {
            "solar_energy_today_kwh": self._optional_float(f"{pfx}_pv_energy_today_kwh"),
            "import_energy_today_kwh": self._optional_float(f"{pfx}_import_energy_today_kwh"),
            "export_energy_today_kwh": self._optional_float(f"{pfx}_export_energy_today_kwh"),
            # GivTCP names these battery_charge_energy_today_kwh and
            # battery_discharge_energy_today_kwh. The unprefixed names are kept
            # as a fallback for older GivTCP versions.
            "charge_energy_today_kwh": self._first_optional_float(
                f"{pfx}_battery_charge_energy_today_kwh", f"{pfx}_charge_energy_today_kwh"
            ),
            "discharge_energy_today_kwh": self._first_optional_float(
                f"{pfx}_battery_discharge_energy_today_kwh", f"{pfx}_discharge_energy_today_kwh"
            ),
            "load_energy_today_kwh": self._optional_float(f"{pfx}_load_energy_today_kwh"),
            # The part of today's import that charged the battery.
            "ac_charge_energy_today_kwh": self._optional_float(
                f"{pfx}_ac_charge_energy_today_kwh"
            ),
        }

    def _charge_rate_w(self, cfg: Mapping[str, Any]) -> float | None:
        """The battery charge rate setting GivTCP exposes, derived from the inverter serial.

        None when the serial is unknown or the entity is missing, unavailable or not above
        zero. The charge window is then left as the cheapest period.
        """
        serial = cfg.get(CONF_INVERTER_SERIAL)
        if not serial:
            return None
        rate = self._optional_float(f"number.{GIVTCP_PREFIX}{serial}_battery_charge_rate")
        return rate if rate is not None and rate > 0 else None

    def _data_age_s(self, cfg: Mapping[str, Any]) -> float | None:
        """GivTCP's Data_Age sensor: seconds since it last read the inverter, -1 for never.

        None where GivTCP does not publish it (older releases), so staleness cannot be seen.
        """
        serial = cfg.get(CONF_INVERTER_SERIAL)
        if not serial:
            return None
        return self._optional_float(f"sensor.{GIVTCP_PREFIX}{serial}_data_age")

    # ── Is GivTCP giving live numbers ─────────────────────────────────────────

    def feed_status(self, cfg: Mapping[str, Any], now: datetime) -> FeedStatus:
        """Silent, frozen, paused, stale or publishing, checked in that order.

        Silent needs the solar and battery entities both missing or unavailable, so a single
        brief interruption does not mark the whole integration unavailable. Frozen is judged
        on when an entity was last reported, never on its value, so a steady reading while
        GivTCP publishes stays fresh. Paused and stale use GivTCP 3.6's status and Data_Age
        sensors where they exist.
        """
        solar = self._state(cfg.get(CONF_SOLAR_POWER))
        battery = self._state(cfg.get(CONF_BATTERY_SOC))
        if _is_stale(solar) and _is_stale(battery):
            missing = solar is None and battery is None
            return FeedStatus(FeedState.MISSING if missing else FeedState.SILENT)
        states = (self._state(cfg.get(key)) for key in _FEED_KEYS)
        newest = newest_report(state.last_reported for state in states if state is not None)
        if frozen_age_s(newest, now) is not None:
            return FeedStatus(FeedState.FROZEN, newest)
        if self._is_paused(cfg):
            return FeedStatus(FeedState.PAUSED, newest)
        age = self._data_age_s(cfg)
        if age is not None and (age < 0 or age > GIVTCP_FROZEN_AFTER_S):
            return FeedStatus(FeedState.STALE, newest)
        return FeedStatus(FeedState.PUBLISHING, newest)

    def _is_paused(self, cfg: Mapping[str, Any]) -> bool:
        serial = cfg.get(CONF_INVERTER_SERIAL)
        state = self._state(f"sensor.{GIVTCP_PREFIX}{serial}_status") if serial else None
        return state is not None and str(state.state).lower() == PAUSED_STATUS
