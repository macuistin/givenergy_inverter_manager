"""
test_diagnostics.py — Tests for diagnostics.py.

async_redact_data is stubbed in conftest.py (pass-through), so diagnostics.py
can be imported and tested without a real HA instance.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock


def _make_entry(data=None, options=None, data_is_none=False):
    entry = MagicMock()
    entry.data = data or {"inverter_serial": "SN123", "base_rate": 0.3334}
    entry.options = options or {"battery_min_soc_pct": 10}
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.update_cycle = 42
    coordinator.solar_fractions = {6: 1.0, 12: 0.5}
    coordinator.ev_charger_brand = "zappi"
    if data_is_none:
        coordinator.data = None
    else:
        coordinator.data = MagicMock()
        coordinator.data.battery_soc = 72.5
        coordinator.data.solar_power_w = 1800.0
        coordinator.data.grid_power_w = -200.0
        coordinator.data.current_rate = 0.0965
        coordinator.data.current_rate_name = "Nightboost"
        coordinator.data.dry_run = False
        coordinator.data.charge_decision = MagicMock()
        coordinator.data.charge_decision.target_soc = 85
    entry.runtime_data = coordinator
    return entry


class TestDiagnostics:
    def test_returns_config_section(self):
        from custom_components.givenergy_inverter_manager.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        entry = _make_entry()
        result = asyncio.run(async_get_config_entry_diagnostics(MagicMock(), entry))

        assert "config" in result
        assert result["config"]["inverter_serial"] == "SN123"

    def test_options_merged_into_config(self):
        from custom_components.givenergy_inverter_manager.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        entry = _make_entry()
        result = asyncio.run(async_get_config_entry_diagnostics(MagicMock(), entry))

        assert result["config"].get("battery_min_soc_pct") == 10

    def test_coordinator_section_present(self):
        from custom_components.givenergy_inverter_manager.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        entry = _make_entry()
        result = asyncio.run(async_get_config_entry_diagnostics(MagicMock(), entry))

        coord = result["coordinator"]
        assert coord["last_update_success"] is True
        assert coord["update_cycle"] == 42
        assert coord["has_ev_charger"] is True
        assert coord["ev_charger_brand"] == "zappi"

    def test_current_data_section_present(self):
        from custom_components.givenergy_inverter_manager.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        entry = _make_entry()
        result = asyncio.run(async_get_config_entry_diagnostics(MagicMock(), entry))

        current = result["current_data"]
        assert current["battery_soc"] == 72.5
        assert current["charge_target"] == 85

    def test_no_current_data_when_coordinator_data_is_none(self):
        from custom_components.givenergy_inverter_manager.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        entry = _make_entry(data_is_none=True)
        result = asyncio.run(async_get_config_entry_diagnostics(MagicMock(), entry))

        assert "current_data" not in result
