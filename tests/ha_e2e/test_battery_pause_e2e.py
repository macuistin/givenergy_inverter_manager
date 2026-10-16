"""GivTCP's battery pause, through the real Home Assistant runtime.

A June evening, 19:00 local, battery at 90%, no solar. GivTCP pauses discharge from 23:00 to
08:00, so nine of the thirteen hours to sunrise run the house from the grid. The Estimated SoC at
Sunrise sensors and the survival reason read the pause from three GivTCP select entities. The
entities may be missing at set-up and added later, or removed again, with no reload.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import PREFIX, Scenario
from homeassistant.config_entries import RELOAD_AFTER_UPDATE_DELAY
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.core.sunrise_hold import HeldSunrise

MODE = f"select.{PREFIX}_battery_pause_mode"
START = f"select.{PREFIX}_battery_pause_start_time_slot"
END = f"select.{PREFIX}_battery_pause_end_time_slot"
START_PICKER = f"time.{PREFIX}_battery_pause_start_time_slot"
END_PICKER = f"time.{PREFIX}_battery_pause_end_time_slot"
CHARGE_RATE = f"number.{PREFIX}_battery_charge_rate"
NOTE = "The battery is paused from 23:00 to 08:00."

# 19:00 in Dublin in June is 18:00 UTC.
JUNE_EVENING = Scenario(
    name="june_evening_90",
    frozen_utc="2026-06-15 18:00:00+00:00",
    solar_w=0.0,
    battery_soc=90.0,
    battery_w=0.0,
    grid_w=-550.0,
    load_w=550.0,
)

PAUSE_STATES = {
    MODE: ("PauseDischarge", {"options": ["Disabled", "PauseCharge", "PauseDischarge", "PauseBoth"]}),
    START: ("23:00:00", {}),
    END: ("08:00:00", {}),
    START_PICKER: ("23:00:00", {}),
    END_PICKER: ("08:00:00", {}),
}


@pytest.fixture
def scenario():
    return JUNE_EVENING


def _publish_the_pause(hass, mode: str = "PauseDischarge") -> None:
    for entity_id, (state, attributes) in PAUSE_STATES.items():
        hass.states.async_set(entity_id, mode if entity_id == MODE else state, attributes)


def _remove_the_pause(hass) -> None:
    for entity_id in PAUSE_STATES:
        hass.states.async_remove(entity_id)


def _sensor(hass, entry, key: str):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, f"no sensor registered for {key}"
    return hass.states.get(entity_id)


async def _refresh(hass, entry) -> None:
    """Refresh with a charge to 90% planned at 3 kW.

    The published figures move at the battery's own pace, so the held figure is forgotten first:
    each step then reads what the model says now. The pacing has its own tests.
    """
    hass.states.async_set(CHARGE_RATE, "3000", {"unit_of_measurement": "W"})
    entry.runtime_data.override_charge_value = 90
    entry.runtime_data.override_charge_enabled = True
    entry.runtime_data._held_sunrise = HeldSunrise()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def _figure(hass, entry) -> float:
    return float(_sensor(hass, entry, "estimated_soc_at_sunrise").state)


async def test_an_install_without_a_pause_is_read_as_it_always_was(hass, loaded_entry):
    await _refresh(hass, loaded_entry)
    data = loaded_entry.runtime_data.data

    assert data.battery_pause is None
    assert "paused" not in _sensor(hass, loaded_entry, "night_survival_reason").state
    basis = _sensor(hass, loaded_entry, "estimated_soc_at_sunrise_with_charge").attributes["basis"]
    assert "paused" not in basis


async def test_a_pause_is_read_and_the_figure_does_not_run_down_on_it(hass, loaded_entry):
    await _refresh(hass, loaded_entry)
    without = _figure(hass, loaded_entry)

    _publish_the_pause(hass)
    await _refresh(hass, loaded_entry)
    data = loaded_entry.runtime_data.data

    # 90% less the 10% minimum is 80 points of usable battery. The house uses (80 - (without
    # - 10)) of them between 19:00 and 08:00, and nine of those thirteen hours are paused.
    used_without_pause = 80.0 - (without - 10.0)
    assert _figure(hass, loaded_entry) == pytest.approx(
        without + used_without_pause * 9 / 13, abs=0.2
    )
    assert data.battery_pause is not None
    assert data.battery_pause.text == "23:00 to 08:00"


async def test_the_words_say_the_battery_is_paused_once(hass, loaded_entry):
    _publish_the_pause(hass)
    await _refresh(hass, loaded_entry)

    reason = _sensor(hass, loaded_entry, "night_survival_reason").state
    basis = _sensor(hass, loaded_entry, "estimated_soc_at_sunrise_with_charge").attributes["basis"]

    assert reason.endswith(NOTE)
    assert reason.count("paused") == 1
    assert basis.endswith(NOTE)
    assert basis.count("paused") == 1


async def test_a_pause_that_is_removed_and_added_again_is_followed(hass, loaded_entry):
    await _refresh(hass, loaded_entry)
    without = _figure(hass, loaded_entry)

    _publish_the_pause(hass)
    await _refresh(hass, loaded_entry)
    with_pause = _figure(hass, loaded_entry)
    assert with_pause > without + 20.0

    _remove_the_pause(hass)
    await _refresh(hass, loaded_entry)
    assert _figure(hass, loaded_entry) == pytest.approx(without)
    assert loaded_entry.runtime_data.data.battery_pause is None
    assert "paused" not in _sensor(hass, loaded_entry, "night_survival_reason").state

    _publish_the_pause(hass)
    await _refresh(hass, loaded_entry)
    assert _figure(hass, loaded_entry) == pytest.approx(with_pause)
    assert loaded_entry.runtime_data.data.battery_pause is not None


async def test_a_pause_that_goes_unavailable_is_no_pause(hass, loaded_entry):
    await _refresh(hass, loaded_entry)
    without = _figure(hass, loaded_entry)
    _publish_the_pause(hass)
    for entity_id in PAUSE_STATES:
        hass.states.async_set(entity_id, "unavailable")
    await _refresh(hass, loaded_entry)

    assert _figure(hass, loaded_entry) == pytest.approx(without)
    assert loaded_entry.runtime_data.data.battery_pause is None


@pytest.mark.parametrize("mode", ["Disabled", "PauseCharge"])
async def test_a_pause_that_does_not_stop_discharge_changes_nothing(hass, loaded_entry, mode):
    await _refresh(hass, loaded_entry)
    without = _figure(hass, loaded_entry)

    _publish_the_pause(hass, mode)
    await _refresh(hass, loaded_entry)

    assert _figure(hass, loaded_entry) == pytest.approx(without)
    assert loaded_entry.runtime_data.data.battery_pause is None


async def test_the_pause_is_only_read_and_nothing_is_written_to_it(hass, loaded_entry, service_calls):
    _publish_the_pause(hass)
    await _refresh(hass, loaded_entry)

    sent = [call.data for calls in service_calls.values() for call in calls]
    assert not [data for data in sent if "pause" in str(data).lower()]


async def _enable_overnight_confidence(hass, entry) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_night_survival_confidence"
    )
    assert entity_id
    registry.async_update_entity(entity_id, disabled_by=None)
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=RELOAD_AFTER_UPDATE_DELAY + 1)
    )
    await hass.async_block_till_done()
    return entity_id


async def test_the_overnight_text_names_the_pause_once(hass, loaded_entry):
    entity_id = await _enable_overnight_confidence(hass, loaded_entry)
    _publish_the_pause(hass)
    await _refresh(hass, loaded_entry)

    attributes = hass.states.get(entity_id).attributes

    assert attributes["summary"].endswith("battery paused 23:00 to 08:00")
    assert attributes["summary"].count("paused") == 1
    assert attributes["explanation"].endswith(NOTE)
    assert attributes["explanation"].count("paused") == 1
    assert len(hass.states.get(entity_id).state) <= 255
