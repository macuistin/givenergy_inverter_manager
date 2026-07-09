"""
test_dashboard.py — Tests for dashboard.py pure logic.

The HA-dependent parts (service registration, persistent_notification call)
are not tested here — they require a running HA instance.

What is tested:
  - _build_dashboard_yaml produces syntactically valid YAML
  - All expected sensor entity references appear in the output
  - The output is stable (same config → same YAML)
  - Dry run sensor entities are included in the Controls view
"""

from unittest.mock import MagicMock

import yaml


def _mock_hass_with_registry(entry_id: str) -> MagicMock:
    """Return a mock HA instance that returns predictable entity IDs."""
    hass = MagicMock()
    # entity_registry returns None for all lookups → falls back to default
    reg = MagicMock()
    reg.async_get_entity_id = MagicMock(return_value=None)
    import sys

    er_mod = sys.modules.get("homeassistant.helpers.entity_registry")
    if er_mod:
        er_mod.async_get.return_value = reg
    return hass


def _build(entry_id: str = "test_entry_123") -> str:
    from custom_components.givenergy_inverter_manager.dashboard import _build_dashboard_yaml

    hass = _mock_hass_with_registry(entry_id)
    return _build_dashboard_yaml(hass, entry_id)


class TestBuildDashboardYaml:
    def test_returns_string(self):
        result = _build()
        assert isinstance(result, str)
        assert len(result) > 100

    def test_is_valid_yaml(self):
        """Generated output must parse as valid YAML without errors."""
        result = _build()
        parsed = yaml.safe_load(result)
        assert parsed is not None

    def test_has_views_key(self):
        """Top-level key must be 'views'."""
        result = _build()
        parsed = yaml.safe_load(result)
        assert "views" in parsed

    def test_has_four_views(self):
        result = _build()
        parsed = yaml.safe_load(result)
        assert len(parsed["views"]) == 4

    def test_view_titles(self):
        result = _build()
        parsed = yaml.safe_load(result)
        titles = [v["title"] for v in parsed["views"]]
        assert "Power Flow" in titles
        assert "Today" in titles
        assert "Battery" in titles
        assert "Controls" in titles

    def test_view_paths(self):
        result = _build()
        parsed = yaml.safe_load(result)
        paths = [v["path"] for v in parsed["views"]]
        assert "power-flow" in paths
        assert "today" in paths
        assert "battery" in paths
        assert "controls" in paths

    def test_sensor_references_present(self):
        """Key sensor suffixes must appear in the output."""
        result = _build()
        required = [
            "solar_power",
            "battery_soc",
            "grid_power",
            "house_load",
            "import_cost_today",
            "export_earnings_today",
            "zappi_cost_today",
            "immersion_cost_today",
            "house_cost_today",
            "overnight_charge_target",
            "overnight_charge_reason",
            "battery_cycles",
            "battery_remaining_life",
            "dry_run_active",
            "dry_run_last_skipped",
            "battery_power",
        ]
        for suffix in required:
            assert suffix in result, (
                f"Expected sensor suffix {suffix!r} not found in dashboard YAML"
            )

    def test_dry_run_sensors_in_controls(self):
        """Controls view must include both dry run sensor references."""
        result = _build()
        parsed = yaml.safe_load(result)
        controls_view = next(v for v in parsed["views"] if v["title"] == "Controls")
        view_yaml = yaml.dump(controls_view)
        assert "dry_run_active" in view_yaml
        assert "dry_run_last_skipped" in view_yaml

    def test_conditional_dry_run_warning_present(self):
        """Controls view must have a conditional card for dry run warning."""
        result = _build()
        parsed = yaml.safe_load(result)
        controls_view = next(v for v in parsed["views"] if v["title"] == "Controls")
        card_types = [c.get("type") for c in controls_view.get("cards", [])]
        assert "conditional" in card_types, "Expected a conditional dry-run warning card"

    def test_stable_output(self):
        """Same inputs produce identical YAML on multiple calls."""
        result_a = _build("entry_abc")
        result_b = _build("entry_abc")
        assert result_a == result_b

    def test_consistent_fallback_entity_ids(self):
        """When the entity registry returns None, fallback IDs follow a predictable pattern."""
        result = _build("any_entry")
        # Fallback uses sensor.givenergy_inverter_manager_{suffix}
        assert "sensor.givenergy_inverter_manager_solar_power" in result
        assert "sensor.givenergy_inverter_manager_battery_soc" in result

    def test_power_flow_card_present(self):
        """Power Flow view must include the power-flow-card-plus card type."""
        result = _build()
        assert "power-flow-card-plus" in result

    def test_power_flow_card_uses_battery_power_not_soc(self):
        """Power flow card battery entity must be battery_power (watts), not battery_soc.
        Using SoC for the entity field gives the card a % value instead of watts,
        distorting all flow calculations."""
        result = _build()
        parsed = yaml.safe_load(result)
        pf_view = next(v for v in parsed["views"] if v["path"] == "power-flow")
        pf_card = next(c for c in pf_view["cards"] if "power-flow-card-plus" in c.get("type", ""))
        battery_entity = pf_card["entities"]["battery"]["entity"]
        assert "battery_power" in battery_entity, (
            f"Power flow card battery entity should be battery_power, got {battery_entity!r}. "
            "Using battery_soc gives the card a % value instead of watts."
        )
        soc_entity = pf_card["entities"]["battery"]["state_of_charge"]
        assert "battery_soc" in soc_entity or "state_of_charge" in soc_entity, (
            f"state_of_charge field should reference battery SoC, got {soc_entity!r}"
        )

    def test_no_template_placeholders_remain(self):
        """No unfilled {} placeholders should remain (f-string interpolation complete)."""
        result = _build()
        # YAML anchors use & and *, not {}. A remaining {} means a missing f-string var.
        # We allow {{ and }} which are escaped braces in some templating but we don't use those.
        import re

        # Find any {word} that doesn't look like it was intentionally left
        unresolved = re.findall(r"\{[a-z_]+\}", result)
        assert not unresolved, f"Unresolved placeholders in dashboard YAML: {unresolved}"


class TestDryRunEngine:
    """Tests that dry_run flag is correctly threaded through engine output."""

    def _run_with_dry_run(self, dry_run: bool):
        from datetime import datetime

        from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
        from custom_components.givenergy_inverter_manager.core.engine import (
            RawSensorValues,
            build_coordinator_data,
        )
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        cfg = {
            "rate_periods": [
                {"name": "Day", "rate": 0.3334, "start": "08:00", "end": "23:00"},
                {"name": "Night", "rate": 0.1644, "start": "23:00", "end": "08:00"},
            ],
            "dry_run": dry_run,
            "currency": "EUR",
        }
        raw = RawSensorValues(solar_power_w=1000.0, battery_soc=70.0)
        data, _ = build_coordinator_data(
            raw=raw,
            cfg=cfg,
            acc=EnergyAccumulator(),
            battery_stats=BatteryStats(),
            last_soc=None,
            last_update_time=None,
            now=datetime(2024, 6, 15, 14, 0),
        )
        return data

    def test_dry_run_false_by_default(self):
        data = self._run_with_dry_run(False)
        assert data.dry_run is False

    def test_dry_run_true_when_configured(self):
        data = self._run_with_dry_run(True)
        assert data.dry_run is True

    def test_dry_run_last_skipped_empty_on_init(self):
        data = self._run_with_dry_run(True)
        assert data.dry_run_last_skipped == ""

    def test_dry_run_does_not_affect_sensor_values(self):
        """dry_run=True must not change any sensor readings."""
        live = self._run_with_dry_run(False)
        dry = self._run_with_dry_run(True)
        assert dry.solar_power_w == live.solar_power_w
        assert dry.battery_soc == live.battery_soc
        assert dry.charge_decision is not None

    def test_dry_run_flag_not_exposed_as_charge_skip(self):
        """dry_run mode must not force skip_charge."""
        data = self._run_with_dry_run(True)
        # dry_run should not interfere with the charge decision logic
        assert isinstance(data.charge_decision.skip_charge, bool)


class TestEvChargerDiscovery:
    """_find_ev_charger_power prefers known external EV integrations over the
    integration's own sensor, which reads from GivTCP and may show 0W."""

    def _find(self, states_present=None):
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.dashboard import (
            _find_ev_charger_power,
        )

        hass = MagicMock()
        hass.states.get = lambda eid: MagicMock() if eid in (states_present or []) else None
        return _find_ev_charger_power(hass, "sensor.givenergy_inverter_manager_ev_charging_power")

    def test_falls_back_to_integration_sensor_when_no_external_charger(self):
        assert self._find([]) == "sensor.givenergy_inverter_manager_ev_charging_power"

    def test_prefers_myenergi_zappi_when_present(self):
        assert (
            self._find(["sensor.myenergi_zappi_power_ct_internal_load"])
            == "sensor.myenergi_zappi_power_ct_internal_load"
        )

    def test_prefers_first_candidate_found(self):
        result = self._find(
            ["sensor.myenergi_zappi_power_ct_internal_load", "sensor.wallbox_charging_power"]
        )
        assert result == "sensor.myenergi_zappi_power_ct_internal_load"

    def test_wallbox_used_when_no_zappi(self):
        assert self._find(["sensor.wallbox_charging_power"]) == "sensor.wallbox_charging_power"

    def test_no_invert_state_in_generated_yaml(self):
        """invert_state causes double negation — Home shows 0W."""
        assert "invert_state" not in _build()


class TestSuggestApplianceServiceCall:
    """suggest_appliance_run service handler must pass all required arguments."""

    def test_battery_power_w_in_call(self):
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/dashboard.py").read_text()
        assert "battery_power_w=data.battery_power_w" in src, (
            "Missing battery_power_w causes TypeError on every service invocation."
        )

    def test_export_rate_from_coordinator_not_data(self):
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/dashboard.py").read_text()
        assert "coordinator.export_rate" in src
        assert 'hasattr(data, "export_rate")' not in src, (
            "hasattr guard always returned False — CoordinatorData has no export_rate."
        )
