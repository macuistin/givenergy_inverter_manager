"""A fake GivTCP, a stub Zappi and a stub immersion switch for end-to-end tests.

The integration reads GivTCP entities from the Home Assistant state machine and writes them
with ``number.set_value``, ``switch.turn_on``, ``switch.turn_off`` and ``select.select_option``.
This module stands in for everything on the other side of those calls:

* it publishes the entity states GivTCP publishes (names as ``lib/givtcp/discovery.py``
  expects);
* it registers the four write services and **records every call, in order**, instead of
  sending it anywhere;
* it moves the target entity's state to the written value (a "follow" device), so the
  writer's read-back sees what a real GivTCP would show. ``follow = False`` leaves the state
  alone, and ``fail_on`` makes a call raise, to test the retry and failure paths;
* it can add a stub Zappi (a charge mode select) and an immersion switch with a water
  temperature sensor.

There is no MQTT broker. The brief wanted a disposable instance with Mosquitto; the integration
never talks MQTT itself, it only sees the entities that GivTCP's MQTT discovery would create,
so publishing those entities straight into Home Assistant tests the same code with nothing to
install and no network. ``docs/design/mock_givtcp.md`` says how the same entities and command
topics map onto a real broker for a disposable instance.

Home Assistant is imported only under ``TYPE_CHECKING``, so ``python tools/mock_givtcp.py``
prints the entity map without Home Assistant installed.

Used from ``tests/ha_e2e/test_write_sequence_e2e.py``. Never point it at a real instance: it
replaces the write services of the instance it is installed on.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

DEFAULT_SERIAL = "ab1234g567"
DEFAULT_IMMERSION_SWITCH = "switch.immersion_heater"
DEFAULT_IMMERSION_TEMP = "sensor.hot_water_cylinder_temperature"
ZAPPI_PREFIX = "myenergi_zappi"
# The GivEnergy charger GivTCP publishes as the device GivEVC. The datapoint names and the state
# strings are GivTCP's own. The prefix is a guess, since the documentation gives none.
EVC_PREFIX = "givtcp_evc_ev1234a567"
ZAPPI_PLUGGED_IN = "EV Connected"
ZAPPI_UNPLUGGED = "EV Disconnected"

# Unused charge slots in GivTCP read 00:00:00. The integration writes HH:MM:SS.
UNUSED_SLOT = "00:00:00"

# (service domain, service) pairs the integration writes through.
WRITE_SERVICES = (
    ("number", "set_value"),
    ("switch", "turn_on"),
    ("switch", "turn_off"),
    ("select", "select_option"),
)

# GivTCP daily energy counters and the value each starts at (kWh).
DAILY_COUNTERS = {
    "pv_energy_today_kwh": 12.4,
    "import_energy_today_kwh": 3.1,
    "ac_charge_energy_today_kwh": 1.4,
    "export_energy_today_kwh": 4.6,
    "battery_charge_energy_today_kwh": 5.2,
    "battery_discharge_energy_today_kwh": 2.2,
    "load_energy_today_kwh": 9.8,
}


@dataclass(frozen=True)
class Write:
    """One accepted-looking command, as the integration sent it."""

    domain: str
    service: str
    entity_id: str
    value: str | float | None  # number value, select option, or None for a switch

    @property
    def action(self) -> str:
        """What a test compares: ``"switch.turn_on"``, ``"number.set_value"`` and so on."""
        return f"{self.domain}.{self.service}"

    def as_tuple(self) -> tuple[str, str, Any]:
        return (self.action, self.entity_id, self.value)


@dataclass
class Readings:
    """Live readings in GivTCP's own sign convention (see CLAUDE.md).

    ``grid_w`` is positive when exporting, ``battery_w`` is positive when discharging.
    """

    solar_w: float = 0.0
    battery_soc: float = 50.0
    battery_w: float = 0.0
    grid_w: float = 0.0
    load_w: float = 500.0
    inverter_temp_c: float = 41.5
    capacity_kwh: float = 9.5
    target_soc: int = (
        50  # the idle charge target; a write of the same value is skipped by the writer
    )


@dataclass
class MockGivTCP:
    """The device side of every write the integration makes."""

    hass: HomeAssistant
    serial: str = DEFAULT_SERIAL
    follow: bool = True
    writes: list[Write] = field(default_factory=list)
    other_calls: list[Write] = field(default_factory=list)
    _failing: dict[str, Exception] = field(default_factory=dict)
    _owned: set[str] = field(default_factory=set)

    # ── Names ────────────────────────────────────────────────────────────────

    @property
    def prefix(self) -> str:
        return f"givtcp_{self.serial}"

    def entity(self, domain: str, suffix: str) -> str:
        """``sensor.givtcp_<serial>_<suffix>``, the names GivTCP's MQTT discovery creates."""
        return f"{domain}.{self.prefix}_{suffix}"

    @property
    def entities(self) -> dict[str, str]:
        """The config keys the integration stores, mapped to the entity ids published here."""
        return {
            "solar_power": self.entity("sensor", "pv_power"),
            "battery_soc": self.entity("sensor", "soc"),
            "battery_power": self.entity("sensor", "battery_power"),
            "grid_power": self.entity("sensor", "grid_power"),
            "house_load": self.entity("sensor", "load_power"),
            "inverter_temp": self.entity("sensor", "invertor_temperature"),
            "serial_sensor": self.entity("sensor", "invertor_serial_number"),
            "battery_capacity_kwh": self.entity("sensor", "battery_capacity_kwh"),
            "target_soc": self.entity("number", "target_soc"),
            "enable_charge_target": self.entity("switch", "enable_charge_target"),
            "enable_charge_schedule": self.entity("switch", "enable_charge_schedule"),
            "charge_start_time": self.entity("select", "charge_start_time_slot_1"),
            "charge_end_time": self.entity("select", "charge_end_time_slot_1"),
        }

    # ── States ───────────────────────────────────────────────────────────────

    def publish(self, readings: Readings | None = None, **overrides: Any) -> None:
        """Publish the inverter's read-only states and its controls at their idle values.

        The controls start where a freshly idle inverter has them: schedule and target switches
        off, ``Readings.target_soc`` as the target, both window times unused. Call this before
        the integration is set up, and again to move the readings. Pass ``reset_controls=False``
        to move the readings without touching the controls.
        """
        reset_controls = overrides.pop("reset_controls", True)
        r = readings or Readings(**overrides)
        e = self.entities
        states = self.hass.states.async_set
        power = {"unit_of_measurement": "W", "device_class": "power"}
        states(e["solar_power"], r.solar_w, power)
        states(
            e["battery_soc"], r.battery_soc, {"unit_of_measurement": "%", "device_class": "battery"}
        )
        states(e["battery_power"], r.battery_w, power)
        states(e["grid_power"], r.grid_w, power)
        states(e["house_load"], r.load_w, power)
        states(
            e["inverter_temp"],
            r.inverter_temp_c,
            {"unit_of_measurement": "°C", "device_class": "temperature"},
        )
        states(e["serial_sensor"], self.serial)
        states(e["battery_capacity_kwh"], r.capacity_kwh, {"unit_of_measurement": "kWh"})
        energy = {"unit_of_measurement": "kWh", "device_class": "energy"}
        for suffix, value in DAILY_COUNTERS.items():
            states(self.entity("sensor", suffix), value, energy)
        if reset_controls:
            self.reset_controls(r.target_soc)
        self._owned.update(e.values())

    def reset_controls(self, target_soc: int = 50) -> None:
        e = self.entities
        states = self.hass.states.async_set
        states(e["target_soc"], target_soc, {"min": 4, "max": 100, "step": 1})
        states(e["enable_charge_target"], "off")
        states(e["enable_charge_schedule"], "off")
        states(e["charge_start_time"], UNUSED_SLOT)
        states(e["charge_end_time"], UNUSED_SLOT)

    def add_immersion(
        self,
        switch: str = DEFAULT_IMMERSION_SWITCH,
        temp_sensor: str = DEFAULT_IMMERSION_TEMP,
        *,
        on: bool = False,
        temperature_c: float = 48.2,
    ) -> None:
        """A plain switch and a water temperature sensor, as the integration is configured with."""
        self.hass.states.async_set(switch, "on" if on else "off")
        self.set_water_temperature(temperature_c, temp_sensor)
        self._owned.add(switch)

    def set_water_temperature(self, celsius: float, sensor: str = DEFAULT_IMMERSION_TEMP) -> None:
        self.hass.states.async_set(
            sensor, celsius, {"unit_of_measurement": "°C", "device_class": "temperature"}
        )

    def add_zappi(
        self, *, plugged_in: bool = True, mode: str = "Fast", power_w: float = 0.0
    ) -> str:
        """The entities the myenergi integration creates. Returns the charge mode select."""
        p = ZAPPI_PREFIX
        states = self.hass.states.async_set
        states(f"sensor.{p}_plug_status", ZAPPI_PLUGGED_IN if plugged_in else ZAPPI_UNPLUGGED)
        states(f"sensor.{p}_status", "Boosting" if power_w else "Paused")
        states(f"sensor.{p}_internal_load_ct1", power_w)
        states(f"sensor.{p}_charge_added_session", 0)
        states(f"sensor.{p}_serial_number", "21637627")
        select = f"select.{p}_charge_mode"
        states(select, mode)
        self._owned.add(select)
        return select

    def add_givevc(
        self, *, plugged_in: bool = True, charging: bool = False, mode: str = "Grid"
    ) -> str:
        """The entities GivTCP publishes for a GivEnergy charger. Returns the charging mode select.

        Only the charging mode select is owned, so a write to it is recorded in `writes`. Charge
        Control and Plug and Go are published but not owned: any write to them lands in
        `other_calls`, which the charger tests assert stays empty.
        """
        p = EVC_PREFIX
        states = self.hass.states.async_set
        connection = "Connected" if plugged_in else "Not Connected"
        state = "Charging" if charging else ("Connected" if plugged_in else "Idle")
        states(f"sensor.{p}_serial_number", "EV1234A567")
        states(f"sensor.{p}_connection_status", connection)
        states(f"sensor.{p}_charging_state", state)
        states(f"sensor.{p}_active_power", 1380 if charging else 0)
        states(f"sensor.{p}_charge_session_energy", 2.4)
        states(f"switch.{p}_plug_and_go", "on")
        states(f"select.{p}_charge_control", "Start", {"options": ["Start", "Stop"]})
        select = f"select.{p}_charging_mode"
        states(select, mode, {"options": ["Grid", "Solar", "Hybrid"]})
        self._owned.add(select)
        return select

    # ── Services ─────────────────────────────────────────────────────────────

    def install(self) -> None:
        """Register the four write services. Call again after the integration has set up.

        Setting up the switch and number platforms registers Home Assistant's own services of
        the same names, so the mock goes in last.
        """
        for domain, service in WRITE_SERVICES:
            self.hass.services.async_register(domain, service, self._handler(domain, service))

    def fail_on(self, entity_id: str, error: Exception | None = None) -> None:
        """Make every write to *entity_id* raise (a rejected register write)."""
        from homeassistant.exceptions import HomeAssistantError  # noqa: PLC0415

        self._failing[entity_id] = error or HomeAssistantError("write rejected")

    def stop_failing(self, entity_id: str) -> None:
        self._failing.pop(entity_id, None)

    def _handler(self, domain: str, service: str) -> Callable[[ServiceCall], Any]:
        async def handle(call: ServiceCall) -> None:
            for entity_id in _entity_ids(call.data["entity_id"]):
                self._record(domain, service, entity_id, call.data)

        return handle

    def _record(self, domain: str, service: str, entity_id: str, data: Any) -> None:
        value: str | float | None = None
        if service == "set_value":
            value = data["value"]
        elif service == "select_option":
            value = data["option"]
        write = Write(domain, service, entity_id, value)
        if entity_id not in self._owned:
            self.other_calls.append(write)
            return
        if entity_id in self._failing:
            raise self._failing[entity_id]
        self.writes.append(write)
        if self.follow:
            self.hass.states.async_set(entity_id, _state_after(service, value))

    # ── What the tests read ──────────────────────────────────────────────────

    def sequence(self) -> list[tuple[str, str, Any]]:
        """Every recorded write as ``(action, entity_id, value)``, in the order it was sent."""
        return [w.as_tuple() for w in self.writes]

    def writes_to(self, entity_id: str) -> list[Write]:
        return [w for w in self.writes if w.entity_id == entity_id]

    def clear(self) -> None:
        self.writes.clear()
        self.other_calls.clear()


def _state_after(service: str, value: Any) -> str:
    if service == "turn_on":
        return "on"
    if service == "turn_off":
        return "off"
    return str(value)


def _entity_ids(value: Any) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def describe(serial: str = DEFAULT_SERIAL) -> dict[str, Any]:
    """The entity map without Home Assistant, for ``python tools/mock_givtcp.py``."""
    mock = MockGivTCP(None, serial=serial)  # type: ignore[arg-type]
    return {
        "serial": serial,
        "entities": mock.entities,
        "write_services": [f"{d}.{s}" for d, s in WRITE_SERVICES],
        "idle_controls": {
            "target_soc": Readings.target_soc,
            "enable_charge_target": "off",
            "enable_charge_schedule": "off",
            "charge_start_time": UNUSED_SLOT,
            "charge_end_time": UNUSED_SLOT,
        },
    }


if __name__ == "__main__":
    json.dump(describe(*(sys.argv[1:2])), sys.stdout, indent=2)
    sys.stdout.write("\n")
