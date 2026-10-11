"""Which options saves reload the integration, played through a real options flow.

A slider move, a threshold change and a dry-run toggle apply live: the entry object stays
loaded, its coordinator is the same one, and setup runs once. Changing the immersion switch
changes the device set, so it reloads. The slider, threshold and dry-run changes below go
through the controls, which own those settings. The options form no longer carries them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from conftest import TARGET_SOC, Scenario
from controls_support import control
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)
from test_options_flow_e2e import _serialise

import custom_components.givenergy_inverter_manager as integration
from custom_components.givenergy_inverter_manager.const import (
    CONF_DRY_RUN,
    CONF_FORECAST_CONSERVATISM,
    CONF_IMMERSION_SWITCH,
    CONF_OVERNIGHT_CHARGE_TARGET,
    CONF_RATE_PERIODS,
    CONF_SKIP_CHARGE_SOC_THRESHOLD,
    CONF_TARIFF_REVIEWED_ON,
    DOMAIN,
)

# One minute before the cheapest period (Nightboost, 02:00 to 04:00) starts, on a night the
# plan charges: the trigger that writes the charge target is about to fire.
PRE_WINDOW = Scenario(
    name="pre_window",
    frozen_utc="2026-12-15 01:58:30+00:00",
    solar_w=0.0,
    battery_soc=10.0,
    battery_w=0.0,
    grid_w=-600.0,
    load_w=600.0,
)


@pytest.fixture
def scenario():
    return PRE_WINDOW


@pytest.fixture
def lifecycle(monkeypatch):
    """Count how often the integration is set up and unloaded."""
    calls = {"setup": 0, "unload": 0}
    real_setup, real_unload = integration.async_setup_entry, integration.async_unload_entry

    async def counted_setup(hass, entry):
        calls["setup"] += 1
        return await real_setup(hass, entry)

    async def counted_unload(hass, entry):
        calls["unload"] += 1
        return await real_unload(hass, entry)

    monkeypatch.setattr(integration, "async_setup_entry", counted_setup)
    monkeypatch.setattr(integration, "async_unload_entry", counted_unload)
    return calls


def _form_values(fields: list[dict]) -> dict:
    """What the frontend submits untouched: every default and every suggested value."""
    values: dict = {}
    for field in fields:
        if field.get("type") == "expandable":
            values[field["name"]] = _form_values(field["schema"])
        elif "default" in field:
            values[field["name"]] = field["default"]
        elif "suggested_value" in field.get("description", {}):
            values[field["name"]] = field["description"]["suggested_value"]
    return values


def frontend_payload(result, **section_overrides: dict) -> dict:
    """The submission for the open options form, with the given section values changed."""
    payload = _form_values(_serialise(result))
    for name, values in section_overrides.items():
        payload[name] = {**payload.get(name, {}), **values}
    return payload


async def _save_options(hass, entry, **sections: dict) -> None:
    """Open the options form, change the given sections as the frontend would and submit."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=frontend_payload(result, **sections)
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY, result


def _assert_applied_live(entry, coordinator, lifecycle) -> None:
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is coordinator
    assert lifecycle == {"setup": 1, "unload": 0}


async def test_a_slider_move_does_not_reload(hass, lifecycle, loaded_entry):
    coordinator = loaded_entry.runtime_data

    await control(hass, loaded_entry, CONF_FORECAST_CONSERVATISM).async_set_native_value(0.6)
    await hass.async_block_till_done()

    _assert_applied_live(loaded_entry, coordinator, lifecycle)
    assert loaded_entry.options[CONF_FORECAST_CONSERVATISM] == pytest.approx(0.6)


async def test_a_threshold_change_does_not_reload(hass, lifecycle, loaded_entry):
    coordinator = loaded_entry.runtime_data

    await _save_options(
        hass, loaded_entry, threshold_settings={CONF_OVERNIGHT_CHARGE_TARGET: 90}
    )

    _assert_applied_live(loaded_entry, coordinator, lifecycle)
    assert loaded_entry.options[CONF_OVERNIGHT_CHARGE_TARGET] == 90


async def test_a_threshold_control_does_not_reload(hass, lifecycle, loaded_entry):
    coordinator = loaded_entry.runtime_data

    await control(hass, loaded_entry, CONF_SKIP_CHARGE_SOC_THRESHOLD).async_set_native_value(90)
    await hass.async_block_till_done()

    _assert_applied_live(loaded_entry, coordinator, lifecycle)
    assert loaded_entry.options[CONF_SKIP_CHARGE_SOC_THRESHOLD] == 90


async def test_a_dry_run_toggle_does_not_reload_and_takes_effect(hass, lifecycle, loaded_entry):
    coordinator = loaded_entry.runtime_data
    assert coordinator.is_dry_run is False

    await control(hass, loaded_entry, CONF_DRY_RUN).async_turn_on()
    await hass.async_block_till_done()

    _assert_applied_live(loaded_entry, coordinator, lifecycle)
    assert coordinator.is_dry_run is True
    assert coordinator.data.dry_run is True

    await control(hass, loaded_entry, CONF_DRY_RUN).async_turn_off()
    await hass.async_block_till_done()

    _assert_applied_live(loaded_entry, coordinator, lifecycle)
    # The refresh a second save asks for waits out the coordinator's request cooldown, so
    # only the setting the actuators read is checked here.
    assert coordinator.is_dry_run is False


async def test_saving_the_form_unchanged_does_not_reload(hass, lifecycle, loaded_entry):
    coordinator = loaded_entry.runtime_data

    await _save_options(hass, loaded_entry)

    _assert_applied_live(loaded_entry, coordinator, lifecycle)


async def test_changing_the_immersion_switch_reloads(hass, lifecycle, loaded_entry):
    coordinator = loaded_entry.runtime_data
    hass.states.async_set("switch.second_heater", "off")

    await _save_options(
        hass, loaded_entry, immersion_settings={CONF_IMMERSION_SWITCH: "switch.second_heater"}
    )

    assert loaded_entry.state is ConfigEntryState.LOADED
    assert loaded_entry.runtime_data is not coordinator
    assert lifecycle == {"setup": 2, "unload": 1}
    assert loaded_entry.options[CONF_IMMERSION_SWITCH] == "switch.second_heater"


async def test_clearing_the_immersion_switch_reloads_and_removes_its_entities(
    hass, lifecycle, loaded_entry
):
    registry = er.async_get(hass)
    unique_id = f"{loaded_entry.entry_id}_auto_immersion"
    assert registry.async_get_entity_id("switch", DOMAIN, unique_id) is not None
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    payload = frontend_payload(result)
    # The frontend omits an emptied optional selector.
    payload["immersion_settings"].pop(CONF_IMMERSION_SWITCH, None)

    await hass.config_entries.options.async_configure(result["flow_id"], user_input=payload)
    await hass.async_block_till_done()

    assert lifecycle == {"setup": 2, "unload": 1}
    assert registry.async_get_entity_id("switch", DOMAIN, unique_id) is None


async def _fire_trigger_at(hass, entry, at: datetime) -> list:
    """Let the time listeners for *at* run, and return the charge target writes they made."""
    hass.states.async_set(TARGET_SOC, 4, {"min": 4, "max": 100, "step": 1})  # never skip a write
    await entry.runtime_data.async_refresh()
    writes = async_mock_service(hass, "number", "set_value")
    entry.runtime_data._writer.last_write_time.clear()
    async_fire_time_changed(hass, at)
    await hass.async_block_till_done()
    return [c for c in writes if c.data["entity_id"] == TARGET_SOC]


OLD_TRIGGER = datetime(2026, 12, 15, 1, 59, 1, tzinfo=timezone.utc)  # Nightboost starts at 02:00
NEW_TRIGGER = datetime(2026, 12, 15, 23, 29, 1, tzinfo=timezone.utc)  # Night starts at 23:30
SHIFTED_TARIFF = [{"name": "Night", "rate": 0.15, "start": "23:30", "end": "07:30"}]


async def test_the_charge_target_is_written_at_the_saved_tariffs_trigger(hass, loaded_entry):
    """Control for the test below: the unchanged tariff writes at its own trigger."""
    assert await _fire_trigger_at(hass, loaded_entry, OLD_TRIGGER) != []
    assert await _fire_trigger_at(hass, loaded_entry, NEW_TRIGGER) == []


async def test_a_live_tariff_change_moves_the_charge_target_write(hass, lifecycle, loaded_entry):
    """The target is written a minute before the cheapest rate starts.

    That trigger is built from the tariff when the entry loads and again at midnight. A saved
    tariff that moves the cheapest rate must move the write at once, with no reload.
    """
    coordinator = loaded_entry.runtime_data

    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, CONF_RATE_PERIODS: SHIFTED_TARIFF}
    )
    await hass.async_block_till_done()

    _assert_applied_live(loaded_entry, coordinator, lifecycle)
    assert await _fire_trigger_at(hass, loaded_entry, OLD_TRIGGER) == []
    assert await _fire_trigger_at(hass, loaded_entry, NEW_TRIGGER) != []


async def test_a_live_change_releases_the_held_charge_recommendation(hass, loaded_entry):
    """A reload used to clear the held recommendation, so the new setting showed at once."""
    coordinator = loaded_entry.runtime_data

    with patch.object(
        coordinator._held_charge, "release", wraps=coordinator._held_charge.release
    ) as release:
        await control(hass, loaded_entry, CONF_SKIP_CHARGE_SOC_THRESHOLD).async_set_native_value(
            90
        )
        await hass.async_block_till_done()

    release.assert_called_once_with()


async def test_recording_the_tariff_review_date_changes_nothing_else(hass, lifecycle, loaded_entry):
    coordinator = loaded_entry.runtime_data

    with patch.object(
        coordinator._held_charge, "release", wraps=coordinator._held_charge.release
    ) as release:
        hass.config_entries.async_update_entry(
            loaded_entry, options={**loaded_entry.options, CONF_TARIFF_REVIEWED_ON: "2026-12-01"}
        )
        await hass.async_block_till_done()

    _assert_applied_live(loaded_entry, coordinator, lifecycle)
    release.assert_not_called()
