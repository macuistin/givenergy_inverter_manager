"""The charge window end is sized to the plan and written at the pre-window trigger."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from conftest import (
    CHARGE_END,
    CHARGE_START,
    PREFIX,
    TARGET_SOC,
    Scenario,
)
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.givenergy_inverter_manager.const import DOMAIN

CHARGE_RATE = f"number.{PREFIX}_battery_charge_rate"

# One minute before the cheapest period (Nightboost, 02:00 to 04:00) starts. The e2e entry has a
# 9.5 kWh battery and the winter plan charges to the configured 80% cap.
PRE_WINDOW = Scenario(
    name="pre_window",
    frozen_utc="2026-12-15 01:58:30+00:00",
    solar_w=0.0,
    battery_soc=10.0,
    battery_w=0.0,
    grid_w=-600.0,
    load_w=600.0,
)
TRIGGER = datetime(2026, 12, 15, 1, 59, 1, tzinfo=timezone.utc)


@pytest.fixture
def scenario():
    return PRE_WINDOW


def _mock_writes(hass) -> dict[str, list]:
    return {
        f"{domain}.{service}": async_mock_service(hass, domain, service)
        for domain, service in (
            ("number", "set_value"),
            ("switch", "turn_on"),
            ("switch", "turn_off"),
            ("select", "select_option"),
        )
    }


async def _fire_pre_window_trigger(hass, entry, charge_rate: str | None) -> dict[str, list]:
    """Refresh with the given charge rate, then let the 01:59 listener write the schedule."""
    if charge_rate is not None:
        hass.states.async_set(CHARGE_RATE, charge_rate, {"unit_of_measurement": "W"})
    # The inverter reads 4%, so the read-before-write check never skips the target write.
    hass.states.async_set(TARGET_SOC, 4, {"min": 4, "max": 100, "step": 1})
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    calls = _mock_writes(hass)
    coordinator._writer.last_write_time.clear()
    async_fire_time_changed(hass, TRIGGER)
    await hass.async_block_till_done()
    return calls


def _written(calls: dict[str, list], entity_id: str) -> set[str]:
    """The distinct options sent to a select. The mocked service never changes the state, so the
    writer retries the same value until it gives up."""
    return {c.data["option"] for c in calls["select.select_option"] if c.data["entity_id"] == entity_id}


async def test_a_slow_charge_rate_moves_the_window_end_into_the_night_band(hass, loaded_entry):
    calls = await _fire_pre_window_trigger(hass, loaded_entry, charge_rate="2000")

    # 70 points of 9.5 kWh is 6.65 kWh. At 2 kW that is 199.5 minutes, 229.4 with the margin,
    # rounded up to 230: 02:00 plus 3 h 50 min.
    assert _written(calls, CHARGE_END) == {"05:50:00"}
    targets = {c.data["value"] for c in calls["number.set_value"] if c.data["entity_id"] == TARGET_SOC}
    assert targets == {80}
    window = loaded_entry.runtime_data.data.charge_window
    assert window.extended is True
    assert window.text == "02:00 to 05:50"


async def test_the_window_sensor_shows_the_planned_end_and_energy(hass, loaded_entry):
    hass.states.async_set(CHARGE_RATE, "2000", {"unit_of_measurement": "W"})
    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{loaded_entry.entry_id}_overnight_charge_window"
    )
    state = hass.states.get(entity_id)

    assert state.state == "02:00 to 05:50"
    assert state.attributes["window_extended"] is True
    assert state.attributes["window_end"] == "05:50"
    assert state.attributes["expected_kwh"] == pytest.approx(6.65)
    assert state.attributes["expected_finish"] == "05:20"


async def test_a_fast_charge_rate_keeps_the_cheapest_period(hass, loaded_entry):
    calls = await _fire_pre_window_trigger(hass, loaded_entry, charge_rate="9000")

    assert _written(calls, CHARGE_END) == {"04:00:00"}
    assert loaded_entry.runtime_data.data.charge_window.extended is False


async def test_without_a_charge_rate_entity_the_window_is_unchanged(hass, loaded_entry):
    calls = await _fire_pre_window_trigger(hass, loaded_entry, charge_rate=None)

    assert _written(calls, CHARGE_END) == {"04:00:00"}
    assert _written(calls, CHARGE_START) == {"02:00:00"}


def _window_state(hass, entry):
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_overnight_charge_window"
    )
    return hass.states.get(entity_id)


async def test_the_window_sensor_holds_a_small_move_but_the_write_uses_the_planned_end(
    hass, loaded_entry
):
    coordinator = loaded_entry.runtime_data
    hass.states.async_set(CHARGE_RATE, "2000", {"unit_of_measurement": "W"})
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert _window_state(hass, loaded_entry).state == "02:00 to 05:50"

    # A slightly faster charge shortens the plan by 5 minutes, to 05:45.
    hass.states.async_set(CHARGE_RATE, "2050", {"unit_of_measurement": "W"})
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.data.charge_window.text == "02:00 to 05:45"
    assert _window_state(hass, loaded_entry).state == "02:00 to 05:50"

    calls = await _fire_pre_window_trigger(hass, loaded_entry, charge_rate="2050")

    assert _written(calls, CHARGE_END) == {"05:45:00"}
    # The write released the held window. The sensor catches up on the next cycle. The trigger
    # also fires the coordinator's own poll timer, and which of the two runs first depends on
    # the real loop clock, so run that cycle here instead of leaving it to the order.
    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _window_state(hass, loaded_entry).state == "02:00 to 05:45"


async def test_the_window_sensor_shows_a_large_move_at_once(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    hass.states.async_set(CHARGE_RATE, "2000", {"unit_of_measurement": "W"})
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    hass.states.async_set(CHARGE_RATE, "9000", {"unit_of_measurement": "W"})
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert _window_state(hass, loaded_entry).state == "02:00 to 04:00"
