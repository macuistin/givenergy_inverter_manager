"""SP3, part 2: the options flow. Routing, one write at confirm, merged into the current options.

The throwaway flows and fixtures are in sp3_support.py. See docs/design/spikes/SP3.md.
"""

# ruff: noqa: F811
# The fixtures come from sp3_support and are used by name, which ruff reads as a redefinition.

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
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
# 2. Options flow variant
# ---------------------------------------------------------------------------------------------


async def test_options_flow_routes_and_writes_once_at_confirm(hass, wizard):
    entry = await loaded_entry(hass)
    real = hass.config_entries.async_update_entry
    with patch.object(hass.config_entries, "async_update_entry", wraps=real) as update:
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        assert (flow["step_id"], flow["last_step"]) == ("init", False)

        flow = await hass.config_entries.options.async_configure(
            flow["flow_id"], {"pages": ["hot_water", "battery"]}
        )
        assert flow["step_id"] == "hot_water"
        flow = await hass.config_entries.options.async_configure(
            flow["flow_id"], {"immersion_switch": "switch.heater"}
        )
        assert flow["step_id"] == "battery"
        flow = await hass.config_entries.options.async_configure(
            flow["flow_id"], {"battery_capacity_kwh": 12.0}
        )
        assert (flow["step_id"], flow["last_step"]) == ("confirm", True)
        assert flow["description_placeholders"]["changes"] == (
            "battery_capacity_kwh, immersion_switch"
        )
        # Three screens answered and the confirm form shown: still no write.
        assert update.call_count == 0
        assert dict(entry.options) == {"dry_run": True, "slider": 80, "base_rate": 0.3}

        flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
        await hass.async_block_till_done()
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert update.call_count == 1
    assert dict(entry.options) == {
        "dry_run": True,
        "slider": 80,
        "base_rate": 0.3,
        "immersion_switch": "switch.heater",
        "battery_capacity_kwh": 12.0,
    }


async def test_options_confirm_merges_the_current_options_not_a_copy_from_flow_start(hass, wizard):
    """A live key moved while the wizard is open survives. Reads at confirm, never in __init__."""
    entry = await loaded_entry(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"pages": ["battery"]}
    )
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"battery_capacity_kwh": 12.0}
    )

    # Meanwhile: dashboard control moved, dry run toggled.
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "slider": 95, "dry_run": False}
    )
    await hass.async_block_till_done()
    wizard.setups = wizard.unloads = 0

    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["slider"] == 95
    assert entry.options["dry_run"] is False
    assert entry.options["battery_capacity_kwh"] == 12.0


async def test_control_a_flow_that_copies_options_at_creation_overwrites_a_live_change(
    hass, wizard
):
    """Documents the v0.17.1 hazard (`self._options = dict(config_entry.options)` in __init__)."""
    entry = await loaded_entry(hass)
    with patch.object(
        SetupFlow,
        "async_get_options_flow",
        staticmethod(lambda e: StaleSnapshotOptionsWizard(dict(e.options))),
    ):
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        flow = await hass.config_entries.options.async_configure(
            flow["flow_id"], {"pages": ["battery"]}
        )
        flow = await hass.config_entries.options.async_configure(
            flow["flow_id"], {"battery_capacity_kwh": 12.0}
        )
        hass.config_entries.async_update_entry(entry, options={**entry.options, "slider": 95})
        flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["slider"] == 80  # the live change was lost


async def test_options_flow_nothing_ticked_aborts_without_a_write(hass, wizard):
    entry = await loaded_entry(hass)
    real = hass.config_entries.async_update_entry
    with patch.object(hass.config_entries, "async_update_entry", wraps=real) as update:
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"pages": []})
    assert flow["type"] is FlowResultType.ABORT
    assert update.call_count == 0


async def test_options_confirm_without_changes_does_not_notify_the_listener(hass, wizard):
    """An unchanged write returns False in async_update_entry, so no listener and no reload."""
    entry = await loaded_entry(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"pages": ["tariff"]})
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"base_rate": 0.3, "rate_count": "0"}
    )
    wizard.setups = wizard.unloads = 0
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()
    # rate_count is new, so the options did change here: one reload, not two.
    assert (wizard.unloads, wizard.setups) == (1, 1)

    # Same answers again: the merged options equal the stored ones.
    wizard.setups = wizard.unloads = 0
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"pages": ["tariff"]})
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"base_rate": 0.3, "rate_count": "0"}
    )
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert (wizard.unloads, wizard.setups) == (0, 0)


async def test_options_flow_with_reload_class_refuses_an_entry_with_update_listeners(hass, wizard):
    """OptionsFlowWithReload is not an option for an integration that keeps its listener."""

    class AutoReloadOptions(config_entries.OptionsFlowWithReload):
        async def async_step_init(self, user_input: dict | None = None) -> Any:
            if user_input is not None:
                return self.async_create_entry(title="", data={"x": 1})
            return self.async_show_form(step_id="init", data_schema=vol.Schema({}))

    entry = await loaded_entry(hass)
    assert entry.update_listeners
    with patch.object(
        SetupFlow, "async_get_options_flow", staticmethod(lambda e: AutoReloadOptions())
    ):
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        with pytest.raises(ValueError, match="update listeners should not be used"):
            await hass.config_entries.options.async_configure(flow["flow_id"], {})
