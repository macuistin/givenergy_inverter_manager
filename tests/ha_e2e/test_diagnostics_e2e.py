"""Download diagnostics through the real diagnostics HTTP view."""

from __future__ import annotations

import json

from conftest import MIDDAY, PREFIX, SERIAL, set_givtcp_states
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.givenergy_inverter_manager.const import CONF_SOLAR_POWER


async def test_downloaded_diagnostics_hide_the_serial(
    hass, hass_client, service_calls, config_entry, tmp_path
):
    """The serial and every entity ID built from it are redacted in the download.

    The clock is not frozen here: aiohttp's access logger fails under a frozen time.
    """
    hass.config.config_dir = str(tmp_path)
    set_givtcp_states(hass, MIDDAY)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    text = json.dumps(diagnostics).lower()
    assert SERIAL.lower() not in text
    assert PREFIX not in text
    assert diagnostics["config"]["inverter_serial"] == "**REDACTED**"
    assert "**REDACTED**" in diagnostics["config"][CONF_SOLAR_POWER]
    assert diagnostics["config"]["base_rate"] == 0.3334
    assert diagnostics["coordinator"]["last_update_success"] is True
    assert "current_data" in diagnostics

    await hass.config_entries.async_unload(config_entry.entry_id)
