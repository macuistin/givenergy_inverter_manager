"""
conftest.py - fixtures for the real Home Assistant end-to-end suite.

Nothing in here stubs homeassistant. The `hass` fixture comes from
pytest-homeassistant-custom-component and runs a real HomeAssistant instance
with an in-memory storage layer, so config entries, the entity registry, the
entity platform and the config/options flow managers all behave as in
production. Only the outside world is faked: GivTCP entity states are set with
hass.states.async_set and service calls that would write to the inverter are
captured with async_mock_service.

This suite needs its own virtualenv (see docs/testing.md). When the plugin is
not installed (for example in the venv used by the stubbed suite) every test
module in this directory is skipped at collection time.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_PLUGIN_MISSING = importlib.util.find_spec("pytest_homeassistant_custom_component") is None

if _PLUGIN_MISSING:
    # Do not import the real test modules (they need the plugin at import time).
    # Everything except test_00_plugin_available.py is ignored, and that one
    # reports a single skip that says what to install.
    collect_ignore_glob = ["test_[!0]*.py"]
else:
    import pytest
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
        async_mock_service,
    )

    from custom_components.givenergy_inverter_manager.const import (
        CONF_BASE_RATE,
        CONF_BASE_RATE_NAME,
        CONF_BATTERY_CAPACITY,
        CONF_BATTERY_MIN_SOC,
        CONF_BATTERY_POWER,
        CONF_BATTERY_SOC,
        CONF_BILL_START_DAY,
        CONF_CAR_EFFICIENCY_KWH_PER_100KM,
        CONF_CARBON_INTENSITY_ENTITY,
        CONF_CHARGE_END_TIME_ENTITY,
        CONF_CHARGE_START_TIME_ENTITY,
        CONF_CHEAP_RATE_FLOOR_SOC,
        CONF_CURRENCY,
        CONF_DISCOUNT_RATE,
        CONF_ENABLE_CHARGE_SCHEDULE,
        CONF_ENABLE_CHARGE_TARGET,
        CONF_EXPORT_RATE,
        CONF_FORECAST_CONSERVATISM,
        CONF_FORECAST_ENTITY,
        CONF_FORECAST_ENTITY_D2,
        CONF_FORECAST_ENTITY_P10,
        CONF_FORECAST_PROVIDER,
        CONF_GRID_POWER,
        CONF_HOUSE_LOAD,
        CONF_IMMERSION_MIN_TEMP,
        CONF_IMMERSION_SWITCH,
        CONF_IMMERSION_TARGET_TEMP,
        CONF_IMMERSION_TEMP_SENSOR,
        CONF_IMMERSION_WATTAGE,
        CONF_INVERTER_MAX_OUTPUT,
        CONF_INVERTER_SERIAL,
        CONF_INVERTER_TEMP_ENTITY,
        CONF_OVERNIGHT_CHARGE_TARGET,
        CONF_PSO_LEVY,
        CONF_RATE_PERIODS,
        CONF_SKIP_CHARGE_SOC_THRESHOLD,
        CONF_SOLAR_POWER,
        CONF_STANDING_CHARGE,
        CONF_SURPLUS_DIVERT_MIN_W,
        CONF_SURPLUS_DIVERT_SOC,
        CONF_TARGET_SOC_ENTITY,
        CONF_VAT_RATE,
        DEFAULT_RATE_PERIODS,
        DOMAIN,
        FORECAST_PROVIDER_SOLCAST,
    )

SERIAL = "ab1234g567"
PREFIX = f"givtcp_{SERIAL}"

# Entity IDs follow GivTCP's naming (see const.py and discovery/givtcp.py).
SOLAR = f"sensor.{PREFIX}_pv_power"
SOC = f"sensor.{PREFIX}_soc"
BATTERY_POWER = f"sensor.{PREFIX}_battery_power"
GRID = f"sensor.{PREFIX}_grid_power"
LOAD = f"sensor.{PREFIX}_load_power"
INV_TEMP = f"sensor.{PREFIX}_invertor_temperature"
SERIAL_SENSOR = f"sensor.{PREFIX}_invertor_serial_number"
CAPACITY = f"sensor.{PREFIX}_battery_capacity_kwh"
TARGET_SOC = f"number.{PREFIX}_target_soc"
ENABLE_TARGET = f"switch.{PREFIX}_enable_charge_target"
ENABLE_SCHEDULE = f"switch.{PREFIX}_enable_charge_schedule"
CHARGE_START = f"select.{PREFIX}_charge_start_time_slot_1"
CHARGE_END = f"select.{PREFIX}_charge_end_time_slot_1"

IMMERSION_SWITCH = "switch.immersion_heater"
IMMERSION_TEMP = "sensor.hot_water_cylinder_temperature"
FORECAST = "sensor.energy_production_tomorrow"
FORECAST_P10 = "sensor.solcast_pv_forecast_forecast_tomorrow_10"
FORECAST_D2 = "sensor.solcast_pv_forecast_forecast_day_3"
CARBON = "sensor.grid_carbon_intensity"

# The entities the myenergi integration creates for a Zappi. Their presence is what makes
# the integration discover an EV charger, so a test that wants one publishes these.
ZAPPI_STATES = {
    "sensor.myenergi_zappi_plug_status": "EV Disconnected",
    "sensor.myenergi_zappi_status": "Paused",
    "sensor.myenergi_zappi_internal_load_ct1": "0",
    "sensor.myenergi_zappi_charge_added_session": "0",
    "sensor.myenergi_zappi_serial_number": "21637627",
    "select.myenergi_zappi_charge_mode": "Eco+",
}


async def discover_the_charger(hass, entry) -> None:
    """Run the coordinator's next update as a rediscovery cycle, so it finds a charger."""
    entry.runtime_data._update_cycle = 0
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


@dataclass(frozen=True)
class Scenario:
    """A point in time plus the GivTCP readings that match it."""

    name: str
    frozen_utc: str
    solar_w: float
    battery_soc: float
    battery_w: float  # GivTCP convention: positive = discharging, negative = charging
    grid_w: float  # GivTCP convention: positive = export
    load_w: float
    states: dict[str, Any] = field(default_factory=dict)


# Mid-afternoon in June: solar surplus, battery charging, exporting.
MIDDAY = Scenario(
    name="midday_surplus",
    frozen_utc="2026-06-15 12:00:00+00:00",
    solar_w=3200.0,
    battery_soc=62.0,
    battery_w=-1300.0,
    grid_w=400.0,
    load_w=1500.0,
)
# Winter night inside the cheap-rate window: importing, no solar.
CHEAP_NIGHT = Scenario(
    name="winter_cheap_night",
    frozen_utc="2026-12-15 02:30:00+00:00",
    solar_w=0.0,
    battery_soc=31.0,
    battery_w=0.0,
    grid_w=-600.0,
    load_w=600.0,
)


def full_config_data() -> dict[str, Any]:
    """A complete, valid config entry payload (every optional feature on)."""
    return {
        CONF_INVERTER_SERIAL: SERIAL,
        CONF_SOLAR_POWER: SOLAR,
        CONF_BATTERY_SOC: SOC,
        CONF_BATTERY_POWER: BATTERY_POWER,
        CONF_GRID_POWER: GRID,
        CONF_HOUSE_LOAD: LOAD,
        CONF_INVERTER_TEMP_ENTITY: INV_TEMP,
        CONF_TARGET_SOC_ENTITY: TARGET_SOC,
        CONF_ENABLE_CHARGE_TARGET: ENABLE_TARGET,
        CONF_ENABLE_CHARGE_SCHEDULE: ENABLE_SCHEDULE,
        CONF_CHARGE_START_TIME_ENTITY: CHARGE_START,
        CONF_CHARGE_END_TIME_ENTITY: CHARGE_END,
        CONF_BATTERY_CAPACITY: 9.5,
        CONF_INVERTER_MAX_OUTPUT: 5.0,
        # Tariff
        CONF_BASE_RATE: 0.3334,
        CONF_BASE_RATE_NAME: "Day",
        CONF_RATE_PERIODS: [dict(p) for p in DEFAULT_RATE_PERIODS],
        CONF_EXPORT_RATE: 0.195,
        CONF_STANDING_CHARGE: 0.8259,
        CONF_PSO_LEVY: 1.46,
        CONF_VAT_RATE: 9.0,
        CONF_DISCOUNT_RATE: 5.5,
        CONF_BILL_START_DAY: 16,
        CONF_CURRENCY: "EUR",
        # Forecast and carbon
        CONF_FORECAST_PROVIDER: FORECAST_PROVIDER_SOLCAST,
        CONF_FORECAST_ENTITY: FORECAST,
        CONF_FORECAST_ENTITY_P10: FORECAST_P10,
        CONF_FORECAST_ENTITY_D2: FORECAST_D2,
        CONF_CARBON_INTENSITY_ENTITY: CARBON,
        CONF_FORECAST_CONSERVATISM: 0.35,
        # Immersion
        CONF_IMMERSION_SWITCH: IMMERSION_SWITCH,
        CONF_IMMERSION_WATTAGE: 3000,
        CONF_IMMERSION_TEMP_SENSOR: IMMERSION_TEMP,
        CONF_IMMERSION_TARGET_TEMP: 55,
        CONF_IMMERSION_MIN_TEMP: 50,
        # EV
        CONF_CAR_EFFICIENCY_KWH_PER_100KM: 15.0,
        # Battery
        CONF_BATTERY_MIN_SOC: 10,
        CONF_CHEAP_RATE_FLOOR_SOC: 40,
        CONF_OVERNIGHT_CHARGE_TARGET: 80,
        CONF_SKIP_CHARGE_SOC_THRESHOLD: 75,
        CONF_SURPLUS_DIVERT_SOC: 80,
        CONF_SURPLUS_DIVERT_MIN_W: 500,
    }


def set_givtcp_states(hass, scenario: Scenario) -> None:
    """Publish GivTCP-style input states into the state machine."""
    s = hass.states.async_set
    # GivTCP publishes grid_power with positive = export (coordinator negates it).
    s(SOLAR, scenario.solar_w, {"unit_of_measurement": "W", "device_class": "power"})
    s(SOC, scenario.battery_soc, {"unit_of_measurement": "%", "device_class": "battery"})
    s(BATTERY_POWER, scenario.battery_w, {"unit_of_measurement": "W", "device_class": "power"})
    s(GRID, scenario.grid_w, {"unit_of_measurement": "W", "device_class": "power"})
    s(LOAD, scenario.load_w, {"unit_of_measurement": "W", "device_class": "power"})
    s(INV_TEMP, 41.5, {"unit_of_measurement": "°C", "device_class": "temperature"})
    s(SERIAL_SENSOR, SERIAL)
    s(CAPACITY, 9.5, {"unit_of_measurement": "kWh"})
    # Daily counters the coordinator prefers over its own integration.
    for suffix, value in (
        ("pv_energy_today_kwh", 12.4),
        ("import_energy_today_kwh", 3.1),
        ("export_energy_today_kwh", 4.6),
        ("battery_charge_energy_today_kwh", 5.2),
        ("battery_discharge_energy_today_kwh", 2.2),
        ("load_energy_today_kwh", 9.8),
    ):
        s(
            f"sensor.{PREFIX}_{suffix}",
            value,
            {"unit_of_measurement": "kWh", "device_class": "energy"},
        )
    # Charge control entities (written to, but only through mocked services).
    s(TARGET_SOC, 80, {"min": 4, "max": 100, "step": 1})
    s(ENABLE_TARGET, "off")
    s(ENABLE_SCHEDULE, "on")
    s(CHARGE_START, "02:00")
    s(CHARGE_END, "04:00")
    # Optional extras.
    s(IMMERSION_SWITCH, "off")
    s(IMMERSION_TEMP, 48.2, {"unit_of_measurement": "°C", "device_class": "temperature"})
    s(FORECAST, 14.2, {"unit_of_measurement": "kWh", "device_class": "energy"})
    s(FORECAST_P10, 9.8, {"unit_of_measurement": "kWh", "device_class": "energy"})
    s(FORECAST_D2, 11.0, {"unit_of_measurement": "kWh", "device_class": "energy"})
    s(CARBON, 187, {"unit_of_measurement": "g/kWh"})


if not _PLUGIN_MISSING:

    @pytest.fixture(autouse=True)
    def _enable_custom_integrations(enable_custom_integrations):
        """Let the loader find custom_components/givenergy_inverter_manager."""
        return None

    @pytest.fixture(autouse=True)
    def _no_write_retry_delay(monkeypatch):
        """Skip the real 2 s sleeps in the GivTCP write retry loops."""
        monkeypatch.setattr(
            "custom_components.givenergy_inverter_manager.givtcp_writer.GIVTCP_WRITE_RETRY_SLEEP_S",
            0,
        )

    @pytest.fixture(params=[MIDDAY, CHEAP_NIGHT], ids=lambda s: s.name)
    def scenario(request) -> Scenario:
        return request.param

    @pytest.fixture
    async def hass_in_scenario(hass, freezer, scenario, tmp_path) -> Any:
        """hass with a Dublin time zone, a frozen clock and GivTCP inputs published."""
        await hass.config.async_set_time_zone("Europe/Dublin")
        hass.config.latitude = 53.3
        hass.config.longitude = -6.3
        # The integration writes a placeholder dashboard file into the config dir.
        # Keep that out of the plugin's shared testing_config directory.
        hass.config.config_dir = str(tmp_path)
        freezer.move_to(scenario.frozen_utc)
        set_givtcp_states(hass, scenario)
        return hass

    @pytest.fixture
    def service_calls(hass) -> dict[str, list]:
        """Capture every write the integration would send to GivTCP.

        Keys are "domain.service". Nothing reaches a real inverter and the
        mocked services do not change entity state.
        """
        calls: dict[str, list] = {}
        for domain, service in (
            ("number", "set_value"),
            ("switch", "turn_on"),
            ("switch", "turn_off"),
            ("select", "select_option"),
        ):
            calls[f"{domain}.{service}"] = async_mock_service(hass, domain, service)
        return calls

    @pytest.fixture
    def config_entry():
        return MockConfigEntry(
            domain=DOMAIN,
            title="GivEnergy Inverter Manager",
            data=full_config_data(),
            unique_id=SERIAL,
            version=1,
        )

    @pytest.fixture
    async def loaded_entry(hass_in_scenario, service_calls, config_entry) -> AsyncGenerator[Any]:
        """A config entry set up through hass.config_entries.async_setup."""
        hass = hass_in_scenario
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        yield config_entry
        # Unload so the coordinator timers do not outlive the test.
        if config_entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(config_entry.entry_id)
            await hass.async_block_till_done()

    @pytest.fixture
    async def loaded_entry_with_charger(
        hass_in_scenario, service_calls, config_entry
    ) -> AsyncGenerator[Any]:
        """Like loaded_entry, on an install whose Zappi is already there to be discovered."""
        hass = hass_in_scenario
        for entity_id, state in ZAPPI_STATES.items():
            hass.states.async_set(entity_id, state)
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        await discover_the_charger(hass, config_entry)
        yield config_entry
        if config_entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(config_entry.entry_id)
            await hass.async_block_till_done()

    @pytest.fixture
    def sensor_entries() -> Callable:
        """Return registry entries of one platform for a config entry."""
        from homeassistant.helpers import entity_registry as er

        def _get(hass, entry, domain: str = "sensor") -> list:
            registry = er.async_get(hass)
            return [
                e
                for e in er.async_entries_for_config_entry(registry, entry.entry_id)
                if e.domain == domain
            ]

        return _get
