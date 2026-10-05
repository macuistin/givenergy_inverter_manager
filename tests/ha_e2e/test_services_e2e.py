"""Service actions with one and two config entries in a real Home Assistant instance."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.givenergy_inverter_manager.const import CONF_INVERTER_SERIAL, DOMAIN

ALL_SERVICES = (
    "get_dashboard_yaml",
    "suggest_appliance_run",
    "get_roi_summary",
    "compare_tariff",
    "year_on_year_summary",
    "export_energy_data",
)


@pytest.fixture(autouse=True)
def _notifications(hass):
    return async_mock_service(hass, "persistent_notification", "create")


RESPONSE_SERVICES = {"get_roi_summary", "compare_tariff", "year_on_year_summary", "export_energy_data"}


def _second_entry() -> MockConfigEntry:
    data = full_config_data()
    data[CONF_INVERTER_SERIAL] = "cd9876h543"
    return MockConfigEntry(
        domain=DOMAIN, title="Second inverter", data=data, unique_id="cd9876h543", version=1
    )


async def _load(hass, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_services_exist_before_any_entry_is_loaded(hass):
    """Registration happens in async_setup, so the actions exist with no entry."""
    assert await async_setup_component(hass, DOMAIN, {})
    for service in ALL_SERVICES:
        assert hass.services.has_service(DOMAIN, service), service


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("get_dashboard_yaml", {}),
        ("suggest_appliance_run", {"appliance_name": "Dishwasher", "appliance_power_w": 2000}),
        ("get_roi_summary", {}),
        ("compare_tariff", {"rate": 0.3}),
        ("year_on_year_summary", {}),
        ("export_energy_data", {}),
    ],
)
async def test_actions_raise_when_no_entry_is_loaded(hass, service, data):
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, service, data, blocking=True, return_response=service in RESPONSE_SERVICES
        )
    assert err.value.translation_key == "no_config_entry"


async def test_two_entries_keep_services_until_the_last_unloads(
    hass, hass_in_scenario, service_calls, config_entry
):
    second = _second_entry()
    await _load(hass, config_entry)
    await _load(hass, second)
    for service in ALL_SERVICES:
        assert hass.services.has_service(DOMAIN, service), service

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    for service in ALL_SERVICES:
        assert hass.services.has_service(DOMAIN, service), service
    roi = await hass.services.async_call(
        DOMAIN, "get_roi_summary", blocking=True, return_response=True
    )
    assert "today" in roi

    assert await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done()
    for service in ALL_SERVICES:
        assert not hass.services.has_service(DOMAIN, service), service

    await _load(hass, config_entry)
    assert hass.services.has_service(DOMAIN, "get_roi_summary")
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_export_energy_data_returns_the_rows_written(hass, loaded_entry):
    response = await hass.services.async_call(
        DOMAIN, "export_energy_data", blocking=True, return_response=True
    )

    assert response["rows_written"] == len(response["rows"]) >= 5
    assert [row.split(",")[0] for row in response["rows"][:5]] == [
        "today",
        "yesterday",
        "this_week",
        "this_month",
        "this_year",
    ]
    written = Path(response["file"]).read_text(encoding="utf-8").splitlines()
    assert written == [response["header"], *response["rows"]]


async def test_export_energy_data_still_works_without_a_response(hass, loaded_entry):
    assert await hass.services.async_call(DOMAIN, "export_energy_data", blocking=True) is None
    assert Path(hass.config.config_dir, "givenergy_energy_export.csv").exists()


async def test_compare_tariff_lists_every_loaded_entry_and_skips_unloaded_ones(
    hass, hass_in_scenario, service_calls, config_entry
):
    second = _second_entry()
    await _load(hass, config_entry)
    await _load(hass, second)

    both = await hass.services.async_call(
        DOMAIN, "compare_tariff", {"rate": 0.3}, blocking=True, return_response=True
    )
    assert [e["entry_id"] for e in both["entries"]] == [config_entry.entry_id, second.entry_id]
    assert both["entry_id"] == config_entry.entry_id

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    one = await hass.services.async_call(
        DOMAIN, "compare_tariff", {"rate": 0.3}, blocking=True, return_response=True
    )
    assert [e["entry_id"] for e in one["entries"]] == [second.entry_id]
    assert one["entry_id"] == second.entry_id
    await hass.config_entries.async_unload(second.entry_id)
