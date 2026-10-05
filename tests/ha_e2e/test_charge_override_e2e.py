"""The charge target override: switch, slider and coordinator agree at all times."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from conftest import CHEAP_NIGHT, TARGET_SOC
from homeassistant.components.number import DATA_COMPONENT as NUMBER_COMPONENT
from homeassistant.components.switch import DATA_COMPONENT as SWITCH_COMPONENT
from homeassistant.core import State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    async_mock_service,
    mock_restore_cache_with_extra_data,
)

from custom_components.givenergy_inverter_manager.const import DOMAIN

NUMBER_UID = "charge_target_override"
SWITCH_UID = "charge_target_override_enabled"


@pytest.fixture
def scenario():
    return CHEAP_NIGHT


def _entity_id(hass, entry, domain: str, key: str) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id is not None, key
    return entity_id


def _entity(hass, entry, domain: str, key: str):
    component = hass.data[NUMBER_COMPONENT if domain == "number" else SWITCH_COMPONENT]
    return component.get_entity(_entity_id(hass, entry, domain, key))


async def _set_slider(hass, entry, value: int) -> None:
    await _entity(hass, entry, "number", NUMBER_UID).async_set_native_value(value)
    await hass.async_block_till_done()


async def _set_switch(hass, entry, on: bool) -> None:
    switch = _entity(hass, entry, "switch", SWITCH_UID)
    await (switch.async_turn_on() if on else switch.async_turn_off())
    await hass.async_block_till_done()


async def _written_target(hass, entry) -> int:
    """Run the pre-window write and return the target sent to GivTCP."""
    writes = async_mock_service(hass, "number", "set_value")
    async_mock_service(hass, "switch", "turn_on")
    async_mock_service(hass, "switch", "turn_off")
    async_mock_service(hass, "select", "select_option")
    # The inverter reads 4%, so the read-before-write check never skips the write.
    hass.states.async_set(TARGET_SOC, 4, {"min": 4, "max": 100, "step": 1})
    coordinator = entry.runtime_data
    await coordinator.async_refresh()  # a refresh request is debounced, so run the cycle now
    coordinator._last_write_time.clear()
    coordinator._write_charge_target_to_inverter(datetime.now(timezone.utc))
    await hass.async_block_till_done()
    targets = [c.data["value"] for c in writes if c.data["entity_id"] == TARGET_SOC]
    assert targets, "no charge target was written"
    return targets[-1]


def _state(hass, entry, domain: str, key: str) -> str:
    return hass.states.get(_entity_id(hass, entry, domain, key)).state


def _slider_state(hass, entry) -> float:
    return float(_state(hass, entry, "number", NUMBER_UID))


async def test_switch_on_with_the_slider_untouched_applies_the_slider_default(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    assert coordinator.override_charge_target is None

    await _set_switch(hass, loaded_entry, on=True)

    assert coordinator.override_charge_target == 80
    assert _slider_state(hass, loaded_entry) == 80
    assert await _written_target(hass, loaded_entry) == 80
    assert coordinator.data.charge_decision.reason == "Manual override: charge to 80%"


async def test_slider_moved_while_the_switch_is_off_changes_nothing(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    baseline = await _written_target(hass, loaded_entry)
    moved = 95 if baseline != 95 else 90

    await _set_slider(hass, loaded_entry, moved)

    assert _state(hass, loaded_entry, "switch", SWITCH_UID) == "off"
    assert _slider_state(hass, loaded_entry) == moved
    assert coordinator.override_charge_target is None
    assert await _written_target(hass, loaded_entry) == baseline
    assert not coordinator.data.charge_decision.reason.startswith("Manual override")


async def test_switch_on_after_moving_the_slider_uses_the_slider_value(hass, loaded_entry):
    await _set_slider(hass, loaded_entry, 65)
    await _set_switch(hass, loaded_entry, on=True)

    assert loaded_entry.runtime_data.override_charge_target == 65
    assert await _written_target(hass, loaded_entry) == 65


async def test_moving_the_slider_while_on_applies_straight_away(hass, loaded_entry):
    await _set_switch(hass, loaded_entry, on=True)
    await _set_slider(hass, loaded_entry, 55)

    assert loaded_entry.runtime_data.override_charge_target == 55
    assert await _written_target(hass, loaded_entry) == 55


async def test_switch_off_after_on_returns_to_automatic(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    baseline = await _written_target(hass, loaded_entry)
    moved = 95 if baseline != 95 else 90
    await _set_slider(hass, loaded_entry, moved)
    await _set_switch(hass, loaded_entry, on=True)
    assert await _written_target(hass, loaded_entry) == moved

    await _set_switch(hass, loaded_entry, on=False)

    assert coordinator.override_charge_target is None
    assert _state(hass, loaded_entry, "switch", SWITCH_UID) == "off"
    assert _slider_state(hass, loaded_entry) == moved
    assert await _written_target(hass, loaded_entry) == baseline
    assert not coordinator.data.charge_decision.reason.startswith("Manual override")


def _restore(hass, entry_unused=None, *, switch: str, number: float | None) -> None:
    """Seed the restore cache. Entity ids follow the names in entity_snapshot.json."""
    from homeassistant.components.number import NumberExtraStoredData

    states = [(State("switch.givenergy_inverter_manager_enable_charge_target_override", switch), {})]
    if number is not None:
        extra = NumberExtraStoredData(100, 10, 5, "%", number).as_dict()
        states.append(
            (
                State(
                    "number.givenergy_inverter_manager_overnight_charge_target_override",
                    str(number),
                ),
                extra,
            )
        )
    mock_restore_cache_with_extra_data(hass, states)


@pytest.fixture
def restored_on_65(hass):
    _restore(hass, switch="on", number=65.0)


@pytest.fixture
def restored_off_65(hass):
    _restore(hass, switch="off", number=65.0)


async def test_restart_with_the_switch_on_keeps_the_override(
    hass, restored_on_65, loaded_entry
):
    coordinator = loaded_entry.runtime_data

    assert coordinator.override_charge_target == 65
    assert _state(hass, loaded_entry, "switch", SWITCH_UID) == "on"
    assert _slider_state(hass, loaded_entry) == 65
    assert await _written_target(hass, loaded_entry) == 65
    assert coordinator.data.charge_decision.reason == "Manual override: charge to 65%"


async def test_restart_with_the_switch_off_stays_automatic(hass, restored_off_65, loaded_entry):
    coordinator = loaded_entry.runtime_data

    assert coordinator.override_charge_target is None
    assert coordinator.override_charge_value == 65
    assert _state(hass, loaded_entry, "switch", SWITCH_UID) == "off"
    assert _slider_state(hass, loaded_entry) == 65
    await coordinator.async_refresh()
    assert not coordinator.data.charge_decision.reason.startswith("Manual override")


async def test_restart_with_nothing_to_restore_is_off_at_the_default(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data

    assert coordinator.override_charge_target is None
    assert coordinator.override_charge_value == 80
    assert _slider_state(hass, loaded_entry) == 80
