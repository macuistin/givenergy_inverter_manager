"""Helpers for the tests of the tuning controls (dry run, verbose logging and the five numbers)."""

from __future__ import annotations

from homeassistant.components.number import DATA_COMPONENT as NUMBER_COMPONENT
from homeassistant.components.switch import DATA_COMPONENT as SWITCH_COMPONENT
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import DOMAIN

SWITCH_KEYS = ("dry_run", "verbose_logging", "charge_replan")
NUMBER_KEYS = (
    "surplus_divert_soc_pct",
    "surplus_divert_min_power_w",
    "cheap_rate_floor_soc",
    "skip_charge_soc_threshold_pct",
    "forecast_conservatism",
)
CONTROL_KEYS = SWITCH_KEYS + NUMBER_KEYS


def domain_of(key: str) -> str:
    return "switch" if key in SWITCH_KEYS else "number"


def entity_id_of(hass, entry, key: str) -> str | None:
    """The registered entity id of a control, or None when it is not registered."""
    registry = er.async_get(hass)
    return registry.async_get_entity_id(domain_of(key), DOMAIN, f"{entry.entry_id}_{key}")


def control(hass, entry, key: str):
    """The live entity object of a control, as the repo's other end-to-end tests fetch one."""
    entity_id = entity_id_of(hass, entry, key)
    assert entity_id is not None, key
    component = SWITCH_COMPONENT if key in SWITCH_KEYS else NUMBER_COMPONENT
    return hass.data[component].get_entity(entity_id)


# The defaults of section 5 of the design brief. A key nobody has saved shows these.
BRIEF_DEFAULTS = {
    "dry_run": "off",
    "verbose_logging": "off",
    "charge_replan": "off",
    "surplus_divert_soc_pct": 80.0,
    "surplus_divert_min_power_w": 500.0,
    "cheap_rate_floor_soc": 40.0,
    "skip_charge_soc_threshold_pct": 75.0,
    "forecast_conservatism": 0.35,
}


def state_of(hass, entry, key: str):
    entity_id = entity_id_of(hass, entry, key)
    assert entity_id is not None, key
    return hass.states.get(entity_id)


def value_of(hass, entry, key: str):
    state = state_of(hass, entry, key)
    return state.state if key in SWITCH_KEYS else float(state.state)


async def set_control(hass, entry, key: str, value) -> None:
    entity = control(hass, entry, key)
    if key in SWITCH_KEYS:
        await (entity.async_turn_on() if value else entity.async_turn_off())
    else:
        await entity.async_set_native_value(value)
    await hass.async_block_till_done()
