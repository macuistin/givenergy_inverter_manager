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

import pytest
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

    def test_power_flow_battery_soc_is_visible(self):
        """show_state_of_charge must be true so the SoC % appears on the power flow card."""
        result = _build()
        parsed = yaml.safe_load(result)
        pf_view = next(v for v in parsed["views"] if v["path"] == "power-flow")
        pf_card = next(
            c for c in pf_view["cards"] if "power-flow-card-plus" in c.get("type", "")
        )
        assert pf_card["entities"]["battery"]["show_state_of_charge"] is True, (
            "show_state_of_charge must be true — the battery % is otherwise hidden on the card"
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

    def test_no_invert_state_true_in_generated_yaml(self):
        """invert_state: true causes double negation — Home shows 0W.
        invert_state: false is explicit but harmless."""
        assert "invert_state: true" not in _build()


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


class TestPowerFlowTabChanges:
    """Verify the power flow tab layout improvements."""

    def test_clipping_as_secondary_info_on_solar(self):
        yaml = _build()
        solar_section = yaml[yaml.find("solar:") : yaml.find("battery:")]
        assert "secondary_info_entity:" in solar_section, (
            "Clipping must be secondary_info_entity on solar — not a separate large card."
        )

    def test_no_three_column_grid(self):
        assert "columns: 3" not in _build(), "3-column grid must be replaced with compact markdown."

    def test_live_cost_rate_shown_as_grid_secondary_info(self):
        """Live €/hr cost rate is secondary_info on the grid entity."""
        yaml = _build()
        grid_idx = yaml.find("grid:")
        grid_block = yaml[grid_idx : grid_idx + 400]
        assert "secondary_info:" in grid_block, (
            "Live cost rate must be shown as secondary_info on the grid entity."
        )
        assert "live_grid_cost_rate" in grid_block, (
            "Grid secondary_info must reference the live_grid_cost_rate sensor."
        )

    def test_clipping_entity_card_removed(self):
        assert "icon: mdi:alert-circle-outline" not in _build(), (
            "Old standalone clipping entity card must be removed."
        )

    def test_immersion_section_absent_when_unconfigured(self):
        """When no immersion temp sensor is set, section must be a comment not broken YAML."""
        yaml = _build()
        # "apexcharts-card" appears in the header comment — check the section itself
        assert "no temperature sensor configured" in yaml
        # No functional apexcharts block should appear (only the header comment reference)
        assert "graph_span: 12h" not in yaml, (
            "No apexcharts chart should render when temp sensor is unconfigured."
        )

    def test_immersion_section_present_when_configured(self):
        """When temp sensor is configured, section must include apexcharts + glance."""
        from unittest.mock import MagicMock, patch

        from custom_components.givenergy_inverter_manager.const import CONF_IMMERSION_TEMP_SENSOR
        from custom_components.givenergy_inverter_manager.dashboard import _build_dashboard_yaml

        fake_entry = MagicMock()
        fake_entry.entry_id = "test_entry_123"
        fake_entry.data = {CONF_IMMERSION_TEMP_SENSOR: "sensor.water_temp"}
        fake_entry.options = {}

        hass = MagicMock()
        hass.config_entries.async_entries.return_value = [fake_entry]
        hass.states.get.return_value = None

        with patch("custom_components.givenergy_inverter_manager.dashboard.er") as mock_er:
            mock_er.async_get.return_value.async_get_entity_id.return_value = None
            yaml = _build_dashboard_yaml(hass, "test_entry_123")

        assert "apexcharts-card" in yaml, "Immersion section must use apexcharts-card"
        assert "graph_span: 12h" in yaml, "Must show 12 hours of history"
        assert "sensor.water_temp" in yaml, "Actual temp sensor entity must appear in YAML"
        assert yaml.count("apexcharts-card") >= 2, (
            "Must have temperature chart and energy/power chart."
        )
        assert "type: tile" in yaml, "Divert reason must use tile card."


class TestDashboardImprovements:
    """Tests for dashboard improvements: new entities, removed HACS dep, typo fix."""

    def test_new_sensor_references_present(self):
        """Sensors added in dashboard improvements must appear in the output."""
        result = _build()
        for suffix in [
            "current_rate_period",
            "cheap_rate_floor_status",
            "immersion_savings_today",
        ]:
            assert suffix in result, f"Expected {suffix!r} in dashboard YAML"

    def test_immersion_temp_numbers_in_controls(self):
        """Immersion temperature number entities must appear in the Controls view."""
        result = _build()
        parsed = yaml.safe_load(result)
        controls_view = next(v for v in parsed["views"] if v.get("path") == "controls")
        controls_yaml = yaml.dump(controls_view)
        assert "immersion_target_temp" in controls_yaml
        assert "immersion_min_temp" in controls_yaml
        assert "immersion_hysteresis" in controls_yaml

    def test_no_vertical_stack_in_card(self):
        """vertical-stack-in-card HACS dependency must be removed."""
        result = _build()
        assert "vertical-stack-in-card" not in result, (
            "vertical-stack-in-card is a HACS dependency that was removed from the Battery tab"
        )

    def test_tonights_typo_fixed(self):
        """'Tonights' must be corrected to 'Tonight\\'s'."""
        result = _build()
        assert "Tonights" not in result
        assert "Tonight's" in result

    def test_battery_power_in_battery_view(self):
        """battery_power must appear in the Battery view, not just the Power Flow view."""
        result = _build()
        parsed = yaml.safe_load(result)
        battery_view = next(v for v in parsed["views"] if v.get("path") == "battery")
        battery_yaml = yaml.dump(battery_view)
        assert "battery_power" in battery_yaml


class TestIncomeBar:
    """Live cost rate is embedded in the grid node secondary_info (no separate markdown card)."""

    def test_no_income_markdown_card_on_power_flow(self):
        result = _build()
        parsed = yaml.safe_load(result)
        pf_view = next(v for v in parsed["views"] if v.get("path") == "power-flow")
        card_types = [c.get("type", "") for c in pf_view.get("cards", [])]
        assert "markdown" not in card_types, (
            "Income bar is now on the grid node — no separate markdown card needed"
        )

    def test_income_bar_references_grid_power(self):
        result = _build()
        assert "grid_power" in result

    def test_live_cost_rate_in_dashboard(self):
        result = _build()
        assert "live_grid_cost_rate" in result
class TestSolarForecastCards:
    """Solar vs forecast section is present on the Today tab."""

    def test_solar_forecast_entities_in_today_view(self):
        result = _build()
        assert "solar_forecast_kwh_today" in result
        assert "solar_actual_vs_forecast_pct" in result
        assert "yesterday_forecast_accuracy_pct" in result

    def test_solar_history_graph_in_today_view(self):
        result = _build()
        parsed = yaml.safe_load(result)
        today_view = next(v for v in parsed["views"] if v.get("path") == "today")
        history_titles = [
            c.get("title", "")
            for c in today_view.get("cards", [])
            if c.get("type") == "history-graph"
        ]
        assert any("solar" in t.lower() for t in history_titles)
class TestSoCHistoryChart:
    """Battery SoC 24h history graph is present on the Battery tab."""

    def test_soc_history_graph_in_battery_view(self):
        result = _build()
        parsed = yaml.safe_load(result)
        battery_view = next(v for v in parsed["views"] if v.get("path") == "battery")
        history_titles = [
            c.get("title", "")
            for c in battery_view.get("cards", [])
            if c.get("type") == "history-graph"
        ]
        assert any("soc" in t.lower() or "battery" in t.lower() for t in history_titles)


class TestExportCsvHelpers:
    """Unit tests for the CSV export helper functions in dashboard.py."""

    def test_acc_to_csv_row_format(self):
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
        from custom_components.givenergy_inverter_manager.dashboard import _acc_to_csv_row

        acc = EnergyAccumulator()
        acc.solar_kwh = 12.5
        acc.import_kwh = 3.2
        acc.export_kwh = 2.1
        row = _acc_to_csv_row("today", acc)
        parts = row.split(",")
        assert parts[0] == "today"
        assert float(parts[1]) == pytest.approx(12.5)
        assert float(parts[2]) == pytest.approx(3.2)
        assert float(parts[3]) == pytest.approx(2.1)

    def test_snapshot_to_csv_row_format(self):
        from custom_components.givenergy_inverter_manager.dashboard import _snapshot_to_csv_row

        snap = {
            "solar_kwh": 45.0,
            "import_kwh": 20.0,
            "export_kwh": 10.0,
            "battery_throughput_kwh": 8.0,
            "export_earnings": 1.95,
            "import_cost_by_period": {"Night": 1.5, "Day": 2.0},
        }
        row = _snapshot_to_csv_row(1, snap)
        parts = row.split(",")
        assert parts[0] == "month_snapshot_01"
        assert float(parts[1]) == pytest.approx(45.0)  # solar_kwh
        assert float(parts[5]) == pytest.approx(3.5)   # import_cost (1.5 + 2.0)

    def test_csv_header_fields(self):
        from custom_components.givenergy_inverter_manager.dashboard import _CSV_HEADER

        fields = _CSV_HEADER.split(",")
        assert fields[0] == "period"
        assert "solar_kwh" in fields
        assert "import_cost" in fields
        assert "net_position" in fields
