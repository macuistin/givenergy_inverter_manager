"""The cheap rate binary sensors follow the tariff in a real Home Assistant."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import DOMAIN


def _state(hass, entry, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id, f"no binary sensor for {key}"
    return hass.states.get(entity_id).state


async def test_both_sensors_are_on_in_the_cheapest_period_and_off_by_day(
    hass, loaded_entry, scenario
):
    """The scenarios are a June midday on the day rate and a winter 02:30 in the Nightboost."""
    expected = STATE_ON if scenario.name == "winter_cheap_night" else STATE_OFF
    assert _state(hass, loaded_entry, "cheapest_rate_active") == expected
    assert _state(hass, loaded_entry, "cheap_rate_active") == expected
