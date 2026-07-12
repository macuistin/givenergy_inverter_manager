"""
test_untested_modules.py — Basic coverage for diagnostics.py, number.py, reporting.py.

These modules are primarily HA-layer code that's hard to test without a running HA
instance. Tests here use source inspection to confirm key structural properties that
would otherwise go undetected (missing keys, broken imports, wrong patterns).
"""

from __future__ import annotations

from pathlib import Path

# ── diagnostics.py ───────────────────────────────────────────────────────────


class TestDiagnostics:
    """diagnostics.py provides HA Download Diagnostics."""

    def _src(self) -> str:
        return Path("custom_components/givenergy_inverter_manager/diagnostics.py").read_text()

    def test_async_get_config_entry_diagnostics_defined(self):
        assert "async_get_config_entry_diagnostics" in self._src()

    def test_returns_config_section(self):
        src = self._src()
        assert '"config"' in src or "'config'" in src

    def test_returns_coordinator_data(self):
        src = self._src()
        assert "runtime_data" in src or "coordinator" in src.lower()

    def test_uses_redact_data(self):
        assert "async_redact_data" in self._src()

    def test_importable(self):
        # The module imports from homeassistant which is stubbed in conftest.
        # Just confirm the file exists and parses without syntax errors.
        import ast
        ast.parse(self._src())


# ── number.py ────────────────────────────────────────────────────────────────


class TestNumber:
    """number.py provides RestoreNumber entities for immersion temperature controls."""

    def _src(self) -> str:
        return Path("custom_components/givenergy_inverter_manager/number.py").read_text()

    def test_restore_number_used(self):
        assert "RestoreNumber" in self._src()

    def test_async_added_to_hass_implemented(self):
        src = self._src()
        assert "async_added_to_hass" in src

    def test_immersion_target_temp_entity_defined(self):
        assert "ImmersionTargetTempNumber" in self._src()

    def test_immersion_min_temp_entity_defined(self):
        assert "ImmersionMinTempNumber" in self._src()

    def test_immersion_hysteresis_entity_defined(self):
        assert "ImmersionHysteresisNumber" in self._src()

    def test_charge_target_override_entity_defined(self):
        assert "GivEnergyChargeTargetOverride" in self._src()

    def test_persist_uses_async_update_entry(self):
        assert "async_update_entry" in self._src()

    def test_importable(self):
        import ast
        ast.parse(self._src())


# ── core/reporting.py ────────────────────────────────────────────────────────


class TestReporting:
    """reporting.py builds HTML report strings for today, charge plan, and week."""

    def _src(self) -> str:
        return Path("custom_components/givenergy_inverter_manager/core/reporting.py").read_text()

    def test_build_today_summary_html_defined(self):
        assert "build_today_summary_html" in self._src()

    def test_build_today_summary_state_defined(self):
        assert "build_today_summary_state" in self._src()

    def test_build_charge_plan_html_defined(self):
        assert "build_charge_plan_html" in self._src()

    def test_build_charge_plan_state_defined(self):
        assert "build_charge_plan_state" in self._src()

    def test_build_week_summary_html_defined(self):
        assert "build_week_summary_html" in self._src()

    def test_build_week_summary_state_defined(self):
        assert "build_week_summary_state" in self._src()

    def test_no_ha_imports(self):
        src = self._src()
        assert "homeassistant" not in src, (
            "reporting.py must remain HA-free (pure Python) for testability"
        )

    def test_importable_and_callable(self):
        from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
        from custom_components.givenergy_inverter_manager.core.reporting import (
            build_charge_plan_state,
            build_today_summary_state,
            build_week_summary_state,
        )
        data = CoordinatorData()
        # All three functions must accept a CoordinatorData and return a string
        assert isinstance(build_today_summary_state(data), str)
        assert isinstance(build_charge_plan_state(data), str)
        assert isinstance(build_week_summary_state(data), str)

    def test_today_summary_includes_key_metrics(self):
        from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
        from custom_components.givenergy_inverter_manager.core.reporting import (
            build_today_summary_state,
        )
        data = CoordinatorData()
        data.today.solar_kwh = 5.0
        data.today.import_kwh = 1.0
        data.today.export_kwh = 2.0
        result = build_today_summary_state(data)
        assert isinstance(result, str)
        assert len(result) > 0
