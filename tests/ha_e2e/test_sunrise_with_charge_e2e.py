"""The two SoC at sunrise sensors, through the real Home Assistant runtime.

A June evening, 19:00 local: the battery at 66%, no solar, a charge planned for the cheap period.
Estimated SoC at Sunrise Without a Charge sits on the minimum SoC, because the house would run the
battery flat before 08:00 with no charge. Estimated SoC at Sunrise With the Planned Charge adds
the charge window and says where the night ends.
"""

from __future__ import annotations

import re

import pytest
from conftest import PREFIX, Scenario
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import DOMAIN

CHARGE_RATE = f"number.{PREFIX}_battery_charge_rate"

# 19:00 in Dublin in June is 18:00 UTC.
JUNE_EVENING = Scenario(
    name="june_evening",
    frozen_utc="2026-06-15 18:00:00+00:00",
    solar_w=0.0,
    battery_soc=66.0,
    battery_w=0.0,
    grid_w=-550.0,
    load_w=550.0,
)


@pytest.fixture
def scenario():
    return JUNE_EVENING


def _sensor(hass, entry, key: str):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, f"no sensor registered for {key}"
    return registry.async_get(entity_id), hass.states.get(entity_id)


async def _refresh(hass, entry) -> None:
    """Refresh with a 3 kW charge rate and a charge to 90% planned, so the figure is not the forecast's."""
    hass.states.async_set(CHARGE_RATE, "3000", {"unit_of_measurement": "W"})
    entry.runtime_data.override_charge_value = 90
    entry.runtime_data.override_charge_enabled = True
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_without_a_charge_the_figure_sits_on_the_minimum(hass, loaded_entry):
    await _refresh(hass, loaded_entry)

    _, state = _sensor(hass, loaded_entry, "estimated_soc_at_sunrise")

    assert float(state.state) == loaded_entry.runtime_data.data.battery_min_soc
    assert state.attributes["unit_of_measurement"] == "%"
    assert state.attributes["state_class"] == "measurement"


async def test_with_the_planned_charge_the_figure_says_where_the_night_ends(hass, loaded_entry):
    await _refresh(hass, loaded_entry)
    data = loaded_entry.runtime_data.data

    _, without = _sensor(hass, loaded_entry, "estimated_soc_at_sunrise")
    _, with_charge = _sensor(hass, loaded_entry, "estimated_soc_at_sunrise_with_charge")

    assert float(with_charge.state) == pytest.approx(round(data.sunrise_with_charge.soc, 1))
    assert float(with_charge.state) - float(without.state) > 40.0
    assert with_charge.attributes["unit_of_measurement"] == "%"
    assert with_charge.attributes["state_class"] == "measurement"


async def test_the_attributes_make_the_figure_obvious(hass, loaded_entry):
    await _refresh(hass, loaded_entry)
    data = loaded_entry.runtime_data.data

    _, state = _sensor(hass, loaded_entry, "estimated_soc_at_sunrise_with_charge")
    attributes = state.attributes

    # 7 hours of the house's load take the battery well below its 66% before the window opens.
    assert 10.0 <= attributes["soc_at_charge_start"] < 66.0
    assert attributes["charge_added_pct"] > 0.0
    assert re.fullmatch(r"02:00 to \d\d:\d\d", attributes["charge_window"])
    assert attributes["basis"] == data.sunrise_with_charge.basis
    assert isinstance(attributes["basis"], str) and attributes["basis"]


async def test_night_survival_is_still_judged_without_the_charge(hass, loaded_entry):
    await _refresh(hass, loaded_entry)

    _, status = _sensor(hass, loaded_entry, "night_survival_reason")

    assert status.state.startswith("Battery may run low")
    assert loaded_entry.runtime_data.data.will_survive_night is False


async def test_a_skipped_night_gives_the_same_figure_twice(hass, loaded_entry):
    loaded_entry.runtime_data.override_skip_charge = True
    await _refresh(hass, loaded_entry)

    _, without = _sensor(hass, loaded_entry, "estimated_soc_at_sunrise")
    _, with_charge = _sensor(hass, loaded_entry, "estimated_soc_at_sunrise_with_charge")

    assert with_charge.state == without.state
    assert with_charge.attributes["charge_window"] is None
    assert with_charge.attributes["soc_at_charge_start"] is None
    assert with_charge.attributes["charge_added_pct"] == 0.0
    assert "No charge planned" in with_charge.attributes["basis"]


async def test_both_sensors_are_enabled_and_keep_their_unique_ids(hass, loaded_entry):
    for key in ("estimated_soc_at_sunrise", "estimated_soc_at_sunrise_with_charge"):
        entry, state = _sensor(hass, loaded_entry, key)
        assert entry.disabled_by is None
        assert entry.unique_id == f"{loaded_entry.entry_id}_{key}"
        assert state is not None
