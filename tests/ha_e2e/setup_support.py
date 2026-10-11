"""Helpers for the setup wizard tests: the usual inputs, a second inverter, and a runner that
walks the ticked pages. Not collected as tests (the name has no `test_` prefix)."""

from __future__ import annotations

from conftest import (
    BATTERY_POWER,
    FORECAST,
    GRID,
    LOAD,
    SOC,
    SOLAR,
)
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from wizard_support import submit

from custom_components.givenergy_inverter_manager.const import (
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_SOLAR_POWER,
    DOMAIN,
)

FIVE = {
    CONF_SOLAR_POWER: SOLAR,
    CONF_BATTERY_SOC: SOC,
    CONF_BATTERY_POWER: BATTERY_POWER,
    CONF_GRID_POWER: GRID,
    CONF_HOUSE_LOAD: LOAD,
}
TARIFF = {"base_rate": 0.3, "export_rate": 0.1}
ROWS = {
    "rate_period_1": {"rate": 0.12},
    "rate_period_2": {"rate": 0.2},
}
SECOND_SERIAL = "cd5678h901"


def manager(hass):
    return hass.config_entries.flow


async def start(hass):
    return await manager(hass).async_init(DOMAIN, context={"source": SOURCE_USER})


def only_inverter_states(hass, keep_forecast: bool = False) -> None:
    """Leave only the five power sensors, so nothing is discovered."""
    keep = set(FIVE.values()) | ({FORECAST} if keep_forecast else set())
    for entity_id in list(hass.states.async_entity_ids()):
        if entity_id not in keep:
            hass.states.async_remove(entity_id)


def remove_forecast(hass) -> None:
    hass.states.async_remove(FORECAST)


def add_second_inverter(hass, complete: bool = True) -> None:
    prefix = f"givtcp_{SECOND_SERIAL}"
    hass.states.async_set(f"sensor.{prefix}_invertor_serial_number", SECOND_SERIAL)
    hass.states.async_set(f"sensor.{prefix}_pv_power", 100)
    hass.states.async_set(f"sensor.{prefix}_soc", 50)
    hass.states.async_set(f"sensor.{prefix}_battery_power", 0)
    hass.states.async_set(f"sensor.{prefix}_grid_power", 0)
    if complete:
        hass.states.async_set(f"sensor.{prefix}_load_power", 300)
        hass.states.async_set(f"sensor.{prefix}_battery_capacity_kwh", 13.5)


async def finish(hass, result):
    """Submit the confirm form and unload the entry that was created."""
    assert result["step_id"] == "confirm"
    result = await manager(hass).async_configure(result["flow_id"], user_input={})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    return result["result"]


async def unload(hass, entry) -> None:
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def run_pages(hass, result, ticked, **inputs):
    """Submit the system form with *ticked*, then every page with its defaults and *inputs*.

    Returns the screens shown in order and the confirm result.
    """
    shown = [result["step_id"]]
    result = await submit(manager(hass), result, pages=ticked, **inputs.get("system", {}))
    while result["type"] is FlowResultType.FORM and result["step_id"] != "confirm":
        shown.append(result["step_id"])
        values = dict(inputs.get(result["step_id"], {}))
        result = await submit(manager(hass), result, **values)
    shown.append(result["step_id"])
    return shown, result


