"""The recommended charge target holds steady, and the write to the inverter never does."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import FORECAST, FORECAST_P10, MIDDAY, TARGET_SOC
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.givenergy_inverter_manager.const import (
    CHARGE_TARGET_HOLD_MIN_MINUTES,
    CHARGE_TARGET_HOLD_STEP_PCT,
    DOMAIN,
)

FIRST_FORECAST_KWH = 13.0
JITTERED_FORECAST_KWH = 13.2
LOWER_FORECAST_KWH = 14.5


@pytest.fixture
def scenario():
    return MIDDAY


def _entity_id(hass, entry, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None, key
    return entity_id


def _published(hass, entry, key: str) -> str:
    return hass.states.get(_entity_id(hass, entry, key)).state


async def _refresh_with_forecast(hass, coordinator, kwh: float) -> None:
    hass.states.async_set(FORECAST, kwh, {"unit_of_measurement": "kWh"})
    hass.states.async_set(FORECAST_P10, kwh * 0.7, {"unit_of_measurement": "kWh"})
    await coordinator.async_refresh()
    await hass.async_block_till_done()


async def _written_target(hass, coordinator) -> int:
    """Run the pre-window write and return the target sent to GivTCP."""
    writes = async_mock_service(hass, "number", "set_value")
    async_mock_service(hass, "switch", "turn_on")
    async_mock_service(hass, "switch", "turn_off")
    async_mock_service(hass, "select", "select_option")
    # The inverter reads 4%, so the read-before-write check never skips the write.
    hass.states.async_set(TARGET_SOC, 4, {"min": 4, "max": 100, "step": 1})
    coordinator._writer.last_write_time.clear()
    coordinator._write_charge_target_to_inverter(datetime.now(timezone.utc))
    await hass.async_block_till_done()
    targets = [c.data["value"] for c in writes if c.data["entity_id"] == TARGET_SOC]
    assert targets, "no charge target was written"
    return targets[-1]


def _let_the_published_value_stand(freezer) -> None:
    """Move the clock past the time a published target stands before it may step."""
    freezer.tick(timedelta(minutes=CHARGE_TARGET_HOLD_MIN_MINUTES))


async def _settled_at_first_forecast(hass, entry, freezer):
    coordinator = entry.runtime_data
    _let_the_published_value_stand(freezer)
    await _refresh_with_forecast(hass, coordinator, FIRST_FORECAST_KWH)
    return coordinator


async def test_a_small_forecast_change_leaves_the_published_target_and_reason_alone(
    hass, loaded_entry, freezer
):
    coordinator = await _settled_at_first_forecast(hass, loaded_entry, freezer)
    target = _published(hass, loaded_entry, "overnight_charge_target")
    reason = _published(hass, loaded_entry, "overnight_charge_reason")

    await _refresh_with_forecast(hass, coordinator, JITTERED_FORECAST_KWH)

    fresh = coordinator.data.charge_decision
    assert fresh.target_soc != int(target)
    assert abs(fresh.target_soc - int(target)) < CHARGE_TARGET_HOLD_STEP_PCT
    assert _published(hass, loaded_entry, "overnight_charge_target") == target
    assert _published(hass, loaded_entry, "overnight_charge_reason") == reason


async def test_a_clear_change_is_published_once_the_value_has_stood(hass, loaded_entry, freezer):
    coordinator = await _settled_at_first_forecast(hass, loaded_entry, freezer)
    target = int(_published(hass, loaded_entry, "overnight_charge_target"))
    _let_the_published_value_stand(freezer)

    await _refresh_with_forecast(hass, coordinator, LOWER_FORECAST_KWH)

    fresh = coordinator.data.charge_decision.target_soc
    assert abs(fresh - target) >= CHARGE_TARGET_HOLD_STEP_PCT
    assert int(_published(hass, loaded_entry, "overnight_charge_target")) == fresh


async def test_the_write_uses_the_fresh_target_not_the_held_one(hass, loaded_entry, freezer):
    coordinator = await _settled_at_first_forecast(hass, loaded_entry, freezer)
    held_target = int(_published(hass, loaded_entry, "overnight_charge_target"))
    await _refresh_with_forecast(hass, coordinator, JITTERED_FORECAST_KWH)
    fresh_target = coordinator.data.charge_decision.target_soc
    assert fresh_target != held_target

    assert await _written_target(hass, coordinator) == fresh_target


async def test_the_published_target_matches_the_write_from_the_next_cycle(
    hass, loaded_entry, freezer
):
    coordinator = await _settled_at_first_forecast(hass, loaded_entry, freezer)
    await _refresh_with_forecast(hass, coordinator, JITTERED_FORECAST_KWH)
    written = await _written_target(hass, coordinator)

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert int(_published(hass, loaded_entry, "overnight_charge_target")) == written
