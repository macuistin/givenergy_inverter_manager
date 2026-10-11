"""SP3, part 3: async_update_and_abort with an update listener, and the 2026.12 deprecation.

The throwaway flows and fixtures are in sp3_support.py. See docs/design/spikes/SP3.md.
"""

# ruff: noqa: F811
# The fixtures come from sp3_support and are used by name, which ruff reads as a redefinition.

from __future__ import annotations

import logging

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_config_flow
from sp3_support import (  # noqa: F401
    DOMAIN,
    PAGES,
    Counters,
    ReloadFlow,
    SetupFlow,
    StaleSnapshotOptionsWizard,
    _fresh_deprecation_log,
    counters,
    loaded_entry,
    wizard,
    wizard_without_listener,
)

# ---------------------------------------------------------------------------------------------
# 3. async_update_and_abort with an update listener
# ---------------------------------------------------------------------------------------------

DEPRECATION = "has an update listener and should use it for scheduling a reload"


async def _reconfigure(hass: HomeAssistant, entry: MockConfigEntry, host: str) -> dict:
    flow = await entry.start_reconfigure_flow(hass)
    assert flow["step_id"] == "reconfigure"
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"host": host})
    await hass.async_block_till_done()
    return flow


async def test_update_and_abort_with_a_listener_reloads_once_and_logs_nothing(hass, wizard, caplog):
    entry = await loaded_entry(hass)
    caplog.set_level(logging.DEBUG)
    flow = await _reconfigure(hass, entry, "new")
    assert flow["type"] is FlowResultType.ABORT
    assert flow["reason"] == "reconfigure_successful"
    assert entry.data["host"] == "new"
    assert (wizard.unloads, wizard.setups) == (1, 2)  # one reload (setup ran once before)
    assert DEPRECATION not in caplog.text
    assert "2026.12" not in caplog.text


async def test_update_and_abort_without_a_listener_does_not_reload(hass, wizard_without_listener):
    entry = await loaded_entry(hass)
    await _reconfigure(hass, entry, "new")
    assert entry.data["host"] == "new"
    assert (wizard_without_listener.unloads, wizard_without_listener.setups) == (0, 1)


async def test_update_and_abort_with_unchanged_data_does_not_notify_the_listener(hass, wizard):
    entry = await loaded_entry(hass)
    await _reconfigure(hass, entry, "old")
    assert (wizard.unloads, wizard.setups) == (0, 1)


async def test_update_reload_and_abort_with_a_listener_logs_the_2026_12_deprecation(
    hass, wizard, caplog
):
    """What the brief says not to do: the helper plus a listener. Measures the log and reloads."""

    entry = await loaded_entry(hass)
    caplog.set_level(logging.DEBUG)
    with mock_config_flow(DOMAIN, ReloadFlow):
        flow = await _reconfigure(hass, entry, "new")
    assert flow["reason"] == "reconfigure_successful"

    records = [r for r in caplog.records if DEPRECATION in r.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert records[0].levelno == logging.WARNING
    assert f"Detected that custom integration '{DOMAIN}' {DEPRECATION}." in message
    assert "This will stop working in Home Assistant 2026.12.0" in message
    # The listener reloads and so does the helper: two reloads for one change.
    assert wizard.unloads == 2
    assert wizard.setups == 3


async def test_the_deprecation_is_logged_once_per_run_for_an_integration(hass, wizard, caplog):
    entry = await loaded_entry(hass)
    with mock_config_flow(DOMAIN, ReloadFlow):
        await _reconfigure(hass, entry, "a")
        await _reconfigure(hass, entry, "b")
    assert sum(DEPRECATION in r.getMessage() for r in caplog.records) == 1


def test_the_throwaway_handler_is_gone_after_the_fixture():
    """The handler is registered per test and never leaks into the real HANDLERS table."""
    assert DOMAIN not in config_entries.HANDLERS
