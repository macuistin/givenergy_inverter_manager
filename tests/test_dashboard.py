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

import re

import pytest
import yaml

from tests.dashboard_support import (
    ENTRY_ID,
    FULL_CONFIG,
    MINIMAL_CONFIG,
    FakeRegistry,
    default_entity_ids,
    fake_hass,
)

_IDS = default_entity_ids()


def eid(key: str) -> str:
    """Entity ID Home Assistant gives the entity with this unique ID suffix."""
    return _IDS[key]


def _build(config=None, registry=None, **kw) -> str:
    """Dashboard YAML. Defaults to every feature configured and every sensor enabled."""
    from custom_components.givenergy_inverter_manager.dashboard_builder import (
        build_dashboard_yaml,
    )

    with fake_hass(
        FULL_CONFIG if config is None else config,
        registry or FakeRegistry(enable_all=True),
        **({"ev_brand": "myenergi"} | kw),
    ) as hass:
        return build_dashboard_yaml(hass, ENTRY_ID)


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

    def test_has_five_tabs_and_six_sub_views(self):
        result = _build()
        parsed = yaml.safe_load(result)
        tabs = [v for v in parsed["views"] if not v.get("subview")]
        subs = [v for v in parsed["views"] if v.get("subview")]
        assert len(tabs) == 5
        assert len(subs) == 6

    def test_view_titles(self):
        result = _build()
        parsed = yaml.safe_load(result)
        titles = [v["title"] for v in parsed["views"] if not v.get("subview")]
        assert titles == ["Power Flow", "Today", "Bill", "Battery", "Controls"]

    def test_view_paths(self):
        result = _build()
        parsed = yaml.safe_load(result)
        paths = [v["path"] for v in parsed["views"] if not v.get("subview")]
        assert paths == ["power-flow", "today", "bill", "battery", "controls"]
        sub_paths = [v["path"] for v in parsed["views"] if v.get("subview")]
        assert sub_paths == ["immersion", "ev-charger", "cost", "solar", "tariff", "battery-detail"]

    def test_sensor_references_present(self):
        """Key entities must appear in the output."""
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
        for key in required:
            assert eid(key) in result, f"Expected {eid(key)!r} not found in dashboard YAML"

    def test_dry_run_sensors_in_controls(self):
        """Controls view must include both dry run sensor references."""
        result = _build()
        parsed = yaml.safe_load(result)
        controls_view = next(v for v in parsed["views"] if v["title"] == "Controls")
        view_yaml = yaml.dump(controls_view)
        assert eid("dry_run_active") in view_yaml
        assert eid("dry_run_last_skipped") in view_yaml

    def test_conditional_dry_run_warning_present(self):
        """Controls view must have a conditional card for dry run warning."""
        result = _build()
        parsed = yaml.safe_load(result)
        controls_view = next(v for v in parsed["views"] if v["title"] == "Controls")
        card_types = [c.get("type") for c in controls_view.get("cards", [])]
        assert "conditional" in card_types, "Expected a conditional dry-run warning card"

    def test_stable_output(self):
        """Same inputs produce identical YAML on multiple calls."""
        assert _build() == _build()

    def test_entity_ids_come_from_the_registry(self):
        """Entity IDs in the output are the registered ones, not guesses from the key."""
        registry = FakeRegistry(enable_all=True)
        registry._by_uid[("sensor", f"{ENTRY_ID}_solar_power")] = "sensor.my_renamed_solar"
        registry._entries["sensor.my_renamed_solar"] = registry._entries.pop(eid("solar_power"))
        result = _build(registry=registry)
        assert "sensor.my_renamed_solar" in result
        assert eid("solar_power") not in result

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

        from custom_components.givenergy_inverter_manager.dashboard_builder import (
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

    def test_only_the_now_strip_is_a_three_column_grid(self):
        """The old 3-column status grid was replaced by compact markdown. The Now strip is new."""
        parsed = yaml.safe_load(_build())
        pf_view = next(v for v in parsed["views"] if v["path"] == "power-flow")
        grids = [c for c in pf_view["cards"] if c.get("type") == "grid" and c.get("columns") == 3]
        assert [g["title"] for g in grids] == ["Now"]

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

    def test_immersion_section_absent_without_temperature_sensor(self):
        """A switch but no temperature sensor gives the rows but no apexcharts charts."""
        from custom_components.givenergy_inverter_manager.const import CONF_IMMERSION_SWITCH

        text = _build(config={CONF_IMMERSION_SWITCH: "switch.immersion_heater"})
        parsed = yaml.safe_load(text)
        pf_view = next(v for v in parsed["views"] if v["path"] == "power-flow")
        assert all(c.get("type") != "vertical-stack" for c in pf_view["cards"])
        assert "graph_span: 12h" not in text
        assert eid("immersion_today") in text

    def test_immersion_section_present_when_configured(self):
        """When temp sensor is configured, section must include apexcharts + tile."""
        yaml_text = _build()

        assert "apexcharts-card" in yaml_text, "Immersion section must use apexcharts-card"
        assert "graph_span: 12h" in yaml_text, "Must show 12 hours of history"
        assert "sensor.hot_water_cylinder_temperature" in yaml_text
        assert yaml_text.count("apexcharts-card") >= 2, (
            "Must have temperature chart and energy/power chart."
        )
        assert "type: tile" in yaml_text, "Divert reason must use tile card."


class TestDashboardImprovements:
    """Tests for dashboard improvements: new entities, removed HACS dep, typo fix."""

    def test_new_sensor_references_present(self):
        """Sensors added in dashboard improvements must appear in the output."""
        result = _build()
        for key in [
            "current_rate_period",
            "cheap_rate_floor_status",
            "immersion_savings_today",
        ]:
            assert eid(key) in result, f"Expected {eid(key)!r} in dashboard YAML"

    def test_immersion_temp_numbers_in_controls(self):
        """Immersion temperature number entities must appear in the Controls view."""
        result = _build()
        parsed = yaml.safe_load(result)
        controls_view = next(v for v in parsed["views"] if v.get("path") == "controls")
        controls_yaml = yaml.dump(controls_view)
        assert eid("immersion_target_temp") in controls_yaml
        assert eid("immersion_min_temp") in controls_yaml
        assert eid("immersion_hysteresis") in controls_yaml

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
        for key in (
            "solar_forecast_kwh_today",
            "solar_actual_vs_forecast_pct",
            "yesterday_forecast_accuracy_pct",
        ):
            assert eid(key) in result

    def test_solar_graph_in_today_view_uses_statistics(self):
        graphs = [c for c in _cards(_build(), "solar") if c.get("type") == "statistics-graph"]
        assert any("solar" in c["title"].lower() for c in graphs)


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


class TestYamlSerialisation:
    """The dashboard is built as a dict and serialised once."""

    def _dict(self):
        from custom_components.givenergy_inverter_manager.dashboard_builder import build_dashboard

        with fake_hass(FULL_CONFIG, FakeRegistry(enable_all=True), ev_brand="myenergi") as hass:
            return build_dashboard(hass, ENTRY_ID)

    def test_yaml_round_trips_to_the_dict(self):
        assert yaml.safe_load(_build()) == self._dict()

    def test_no_anchors_or_aliases(self):
        """Shared sub-dicts (the apex config) must be written out, not aliased."""
        import re

        assert not re.search(r"[&*]id\d+", _build())

    def test_multiline_strings_are_literal_blocks(self):
        text = _build()
        assert "content: |-\n" in text
        assert "\\n" not in text

    def test_header_comment_precedes_views(self):
        text = _build()
        assert text.startswith("# GivEnergy Inverter Manager")
        assert text.index("views:") > text.index("power-flow-card-plus")


_OUR_ENTITY = re.compile(r"\b(?:sensor|switch|number)\.givenergy_inverter_manager_[a-z0-9_]+")


def _referenced(text: str) -> set[str]:
    return set(_OUR_ENTITY.findall(text))


def _titles(text: str) -> list[str]:
    parsed = yaml.safe_load(text)
    return [c.get("title", "") for v in parsed["views"] for c in v["cards"]]


class TestEntityAvailability:
    """A row or card appears only when the entity is registered and enabled."""

    @pytest.mark.parametrize(
        ("label", "config", "registry", "extra"),
        [
            ("minimal fresh install", MINIMAL_CONFIG, FakeRegistry(), {"ev_brand": None}),
            ("full fresh install", FULL_CONFIG, FakeRegistry(), {"ev_brand": "myenergi"}),
            ("full, all enabled", FULL_CONFIG, FakeRegistry(enable_all=True), {}),
            (
                "minimal, switch entities missing",
                MINIMAL_CONFIG,
                FakeRegistry(absent={"auto_immersion", "charge_target_override"}),
                {"ev_brand": None},
            ),
        ],
    )
    def test_every_referenced_entity_is_registered_and_enabled(
        self, label, config, registry, extra
    ):
        text = _build(config=config, registry=registry, **extra)
        usable = {
            entity_id
            for entity_id in default_entity_ids().values()
            if (entry := registry.async_get(entity_id)) is not None and entry.disabled_by is None
        }
        assert _referenced(text) <= usable, label
        assert _referenced(text), label

    def test_forecast_accuracy_is_left_out_on_a_fresh_install(self):
        """Forecast accuracy yesterday is disabled by default, so no row points at it."""
        text = _build(config=FULL_CONFIG, registry=FakeRegistry())
        assert eid("yesterday_forecast_accuracy_pct") not in text
        assert eid("solar_forecast_kwh_today") in text

    def test_forecast_accuracy_appears_once_enabled(self):
        text = _build(
            config=FULL_CONFIG,
            registry=FakeRegistry(enabled={"yesterday_forecast_accuracy_pct"}),
        )
        assert eid("yesterday_forecast_accuracy_pct") in text

    def test_disabled_sensors_are_listed_in_the_header(self):
        text = _build(config=FULL_CONFIG, registry=FakeRegistry())
        header = text[: text.index("views:")]
        assert "disabled" in header
        assert "Forecast accuracy yesterday" in header

    def test_no_header_note_when_nothing_was_left_out(self):
        text = _build(config=FULL_CONFIG, registry=FakeRegistry(enable_all=True))
        assert "disabled" not in text[: text.index("views:")]

    def test_unregistered_entity_is_left_out(self):
        text = _build(registry=FakeRegistry(enable_all=True, absent={"cheap_rate_floor_status"}))
        assert eid("cheap_rate_floor_status") not in text
        assert "Cheap Rate Floor" not in text

    def test_dashboard_is_never_empty(self):
        parsed = yaml.safe_load(_build(config=MINIMAL_CONFIG, registry=FakeRegistry()))
        assert [v["path"] for v in parsed["views"] if not v.get("subview")] == ["power-flow", "today", "bill", "battery", "controls"]


class TestFeatureGating:
    """EV, immersion, inverter temperature and forecast rows need the feature configured."""

    def _minimal(self, **kw) -> str:
        return _build(config=MINIMAL_CONFIG, registry=FakeRegistry(enable_all=True), **kw)

    def test_minimal_config_has_no_ev_rows(self):
        text = self._minimal(ev_brand=None)
        assert "EV Charger" not in _titles(text)
        for key in ("ev_power", "ev_charger_state", "zappi_today", "zappi_cost_today"):
            assert eid(key) not in text
        assert "Car Charger" not in text

    def test_minimal_config_has_no_immersion_rows(self):
        text = self._minimal(ev_brand=None)
        assert "Immersion Heater" not in _titles(text)
        for key in (
            "immersion_power",
            "immersion_today",
            "immersion_cost_today",
            "immersion_savings_today",
            "immersion_divert_reason",
            "auto_immersion",
            "immersion_target_temp",
        ):
            assert eid(key) not in text
        assert "apexcharts" not in text

    def test_minimal_config_has_no_inverter_temperature_rows(self):
        text = self._minimal(ev_brand=None)
        assert eid("inverter_temperature") not in text
        assert eid("inverter_temperature_status") not in text

    def test_minimal_config_has_no_forecast_card(self):
        text = self._minimal(ev_brand=None)
        assert "Solar vs Forecast" not in _titles(text)
        assert eid("solar_forecast_kwh_today") not in text

    def test_full_config_has_every_feature(self):
        text = _build(config=FULL_CONFIG, registry=FakeRegistry(enable_all=True))
        titles = _titles(text)
        for title in ("EV Charger", "Immersion Heater", "Solar vs Forecast"):
            assert title in titles
        for key in ("ev_power", "immersion_power", "inverter_temperature", "zappi_today"):
            assert eid(key) in text

    def test_each_feature_switches_on_independently(self):
        from custom_components.givenergy_inverter_manager.const import (
            CONF_INVERTER_TEMP_ENTITY,
        )

        text = _build(
            config={CONF_INVERTER_TEMP_ENTITY: "sensor.x"},
            registry=FakeRegistry(enable_all=True),
            ev_brand=None,
        )
        assert eid("inverter_temperature") in text
        assert eid("immersion_power") not in text
        assert eid("ev_power") not in text

    def test_external_ev_charger_state_counts_as_configured(self):
        """An EV charger the coordinator has not discovered yet is still shown if it exists."""
        text = _build(
            config=MINIMAL_CONFIG,
            registry=FakeRegistry(enable_all=True),
            ev_brand=None,
            states=("sensor.wallbox_charging_power",),
        )
        assert "sensor.wallbox_charging_power" in text
        assert "EV Charger" in _titles(text)

    def test_immersion_with_only_a_temperature_sensor(self):
        from custom_components.givenergy_inverter_manager.const import (
            CONF_IMMERSION_TEMP_SENSOR,
        )

        text = _build(
            config={CONF_IMMERSION_TEMP_SENSOR: "sensor.t"},
            registry=FakeRegistry(enable_all=True),
            ev_brand=None,
        )
        assert "Immersion Heater" in _titles(text)
        assert "sensor.t" in text


def _cards(text: str, path: str) -> list[dict]:
    parsed = yaml.safe_load(text)
    return next(v for v in parsed["views"] if v["path"] == path)["cards"]


class TestNowStrip:
    """The first card of the first view is a short strip of core cards."""

    def test_now_strip_is_the_first_card_of_the_first_view(self):
        first = _cards(_build(), "power-flow")[0]
        assert first["type"] == "grid"
        assert first["title"] == "Now"

    def test_now_strip_has_the_six_core_entities(self):
        strip = _cards(_build(), "power-flow")[0]
        assert [c["entity"] for c in strip["cards"]] == [
            eid("battery_soc"),
            eid("night_survival_confidence"),
            eid("current_rate"),
            eid("next_cheap_rate_start"),
            eid("hours_to_cheap_rate"),
            eid("import_cost_today"),
        ]

    def test_now_strip_uses_only_built_in_cards(self):
        strip = _cards(_build(), "power-flow")[0]
        assert {c["type"] for c in strip["cards"]} <= {"gauge", "tile"}

    def test_now_strip_drops_sensors_that_are_disabled_by_default(self):
        """Night survival confidence and the cheap rate sensors are off on a fresh install."""
        text = _build(registry=FakeRegistry())
        strip = _cards(text, "power-flow")[0]
        assert [c["entity"] for c in strip["cards"]] == [
            eid("battery_soc"),
            eid("current_rate"),
            eid("import_cost_today"),
        ]
        header = text[: text.index("views:")]
        for name in ("Night Survival Confidence", "Next Cheap Rate Start", "Hours to Cheap Rate"):
            assert name in header


class TestLongTextStates:
    """Sentences go in a markdown card, not in an entities row where they are cut off."""

    def _battery(self):
        return _cards(_build(), "battery-detail")

    def test_long_text_entities_are_not_entities_rows(self):
        for card in self._battery():
            if card.get("type") != "entities":
                continue
            rows = {r.get("entity") for r in card["entities"]}
            assert eid("overnight_charge_reason") not in rows
            assert eid("night_survival_reason") not in rows

    def test_markdown_card_renders_both_states(self):
        markdown = [c for c in self._battery() if c["type"] == "markdown"]
        assert len(markdown) == 1
        content = markdown[0]["content"]
        assert f"{{{{ states('{eid('overnight_charge_reason')}') }}}}" in content
        assert f"{{{{ states('{eid('night_survival_reason')}') }}}}" in content

    def test_markdown_card_is_valid_jinja(self):
        from jinja2 import Environment

        content = [c for c in self._battery() if c["type"] == "markdown"][0]["content"]
        assert Environment().from_string(content).render(states=lambda entity: "x")

    def test_markdown_card_opens_the_battery_detail_view(self):
        assert self._battery()[0]["type"] == "markdown"
        assert "Tonight's Charge Plan" in [c.get("title") for c in _cards(_build(), "battery")]


class TestStatisticsGraphs:
    """Sensors that reset at midnight draw a sawtooth in a history graph."""

    def test_no_history_graph_plots_a_midnight_reset_sensor(self):
        from tests.dashboard_support import midnight_reset_ids

        resets = midnight_reset_ids()
        parsed = yaml.safe_load(_build())
        for view in parsed["views"]:
            for card in view["cards"]:
                if card.get("type") != "history-graph":
                    continue
                plotted = {r["entity"] for r in card["entities"]}
                assert plotted.isdisjoint(resets), card["title"]

    def test_cost_and_solar_use_statistics_graphs(self):
        graphs = [
            c
            for path in ("cost", "solar")
            for c in _cards(_build(), path)
            if c["type"] == "statistics-graph"
        ]
        assert [g["period"] for g in graphs] == ["hour", "day"] or [
            g["period"] for g in graphs
        ] == ["day", "hour"]
        for g in graphs:
            assert g["stat_types"] == ["change"]
            assert g["chart_type"] == "bar"

    def test_battery_soc_history_graph_is_kept(self):
        """SoC and power do not reset, so a line graph is right for them."""
        graphs = [c for c in _cards(_build(), "battery") if c["type"] == "history-graph"]
        assert len(graphs) == 1


class TestBillView:
    """A view of the month so far and the tariff behind it, to compare with a real bill."""

    def test_bill_view_has_the_month_figures(self):
        text = yaml.dump(_cards(_build(), "bill"))
        for key in (
            "import_cost_this_month",
            "export_earnings_this_month",
            "accrued_bill",
            "projected_bill",
            "days_in_period",
            "days_remaining_in_period",
            "avg_import_rate_this_month",
            "cheap_import_fraction_this_month",
        ):
            assert eid(key) in text, key

    def test_bill_view_uses_only_built_in_cards(self):
        types = {c["type"] for c in _cards(_build(), "bill")}
        assert types <= {"entities", "markdown", "tile", "grid", "glance", "button"}

    def test_disabled_by_default_figures_are_left_out_and_listed(self):
        text = _build(registry=FakeRegistry())
        bill = yaml.dump(_cards(text, "bill"))
        for key in (
            "days_in_period",
            "avg_import_rate_this_month",
            "cheap_import_fraction_this_month",
        ):
            assert eid(key) not in bill
        header = text[: text.index("views:")]
        assert "Days Elapsed in Bill Period" in header
        assert "Average Import Rate This Month" in header

    def test_bill_prediction_moved_off_the_today_view(self):
        titles = [c.get("title") for c in _cards(_build(), "today")]
        assert "Bill Prediction" not in titles

    def _tariff_markdown(self, config=None) -> str:
        cards = _cards(_build(config=config), "tariff")
        return next(c for c in cards if c["type"] == "markdown")["content"]

    def test_tariff_table_lists_base_rate_and_periods(self):
        table = self._tariff_markdown()
        assert "| Day | all other times | €0.3334 |" in table
        assert "| Night | 23:00 to 08:00 | €0.1644 |" in table
        assert "| Nightboost | 02:00 to 04:00 | €0.0965 |" in table

    def test_tariff_table_shows_the_billed_rate(self):
        """Billed per kWh follows the docs: rate x (1 - discount) x (1 + VAT)."""
        table = self._tariff_markdown()
        assert "€0.3334 | €0.3434 |" in table
        assert "€0.0965 | €0.0994 |" in table

    def test_tariff_table_reads_the_config_entry(self):
        from custom_components.givenergy_inverter_manager.const import (
            CONF_BASE_RATE,
            CONF_BASE_RATE_NAME,
            CONF_BILL_START_DAY,
            CONF_CURRENCY,
            CONF_DISCOUNT_RATE,
            CONF_EXPORT_RATE,
            CONF_PSO_LEVY,
            CONF_RATE_PERIODS,
            CONF_STANDING_CHARGE,
            CONF_VAT_RATE,
        )

        table = self._tariff_markdown(
            {
                CONF_BASE_RATE: 0.30,
                CONF_BASE_RATE_NAME: "Standard",
                CONF_RATE_PERIODS: [
                    {"name": "Off-peak", "rate": 0.10, "start": "00:30", "end": "05:30"}
                ],
                CONF_EXPORT_RATE: 0.15,
                CONF_STANDING_CHARGE: 0.5,
                CONF_PSO_LEVY: 0,
                CONF_VAT_RATE: 20,
                CONF_DISCOUNT_RATE: 0,
                CONF_BILL_START_DAY: 12,
                CONF_CURRENCY: "GBP",
            }
        )
        assert "| Standard | all other times | £0.3000 | £0.3600 |" in table
        assert "| Off-peak | 00:30 to 05:30 | £0.1000 | £0.1200 |" in table
        assert "Night" not in table
        assert "less the 0% discount, plus 20% VAT" in table
        assert "| Export rate | £0.1500 per kWh |" in table
        assert "| Standing charge | £0.5000 per day |" in table
        assert "| PSO levy | £0.00 per bill period |" in table
        assert "| Bill starts on day | 12 |" in table

    def test_tariff_table_falls_back_to_the_defaults_the_engine_uses(self):
        table = self._tariff_markdown(config={})
        assert "| Night | 23:00 to 08:00 | €0.1644 |" in table


_PFC = "/hacsfiles/power-flow-card-plus/power-flow-card-plus.js?hacstag=1"
_APEX = "/hacsfiles/apexcharts-card/apexcharts-card.js?hacstag=2"


def _all_cards(text: str) -> list[dict]:
    parsed = yaml.safe_load(text)
    out: list[dict] = []

    def walk(cards):
        for card in cards:
            out.append(card)
            walk(card.get("cards", []))

    for view in parsed["views"]:
        walk(view["cards"])
    return out


class TestMissingHacsCards:
    """The custom cards are optional: without their resource the view uses built-in cards."""

    def _types(self, resources) -> set[str]:
        from custom_components.givenergy_inverter_manager.dashboard_builder import (
            build_dashboard_yaml,
        )

        with fake_hass(FULL_CONFIG, FakeRegistry(enable_all=True), ev_brand="myenergi") as hass:
            return {c["type"] for c in _all_cards(build_dashboard_yaml(hass, ENTRY_ID, resources))}

    def _text(self, resources) -> str:
        from custom_components.givenergy_inverter_manager.dashboard_builder import (
            build_dashboard_yaml,
        )

        with fake_hass(FULL_CONFIG, FakeRegistry(enable_all=True), ev_brand="myenergi") as hass:
            return build_dashboard_yaml(hass, ENTRY_ID, resources)

    def test_unknown_resources_keep_the_custom_cards(self):
        types = self._types(None)
        assert {"custom:power-flow-card-plus", "custom:apexcharts-card"} <= types

    def test_both_installed_keep_the_custom_cards(self):
        types = self._types([_PFC, _APEX])
        assert {"custom:power-flow-card-plus", "custom:apexcharts-card"} <= types

    def test_no_resources_means_no_custom_cards(self):
        types = self._types([])
        assert not {t for t in types if t.startswith("custom:")}

    def test_power_flow_falls_back_to_an_entities_card(self):
        text = self._text([_APEX])
        assert "custom:power-flow-card-plus" not in text
        card = next(c for c in _all_cards(text) if c.get("title") == "Live Power")
        assert card["type"] == "entities"
        rows = [r["entity"] for r in card["entities"]]
        for key in ("solar_power", "battery_power", "battery_soc", "grid_power", "house_load"):
            assert eid(key) in rows
        assert eid("ev_power") in rows
        assert eid("immersion_power") in rows

    def test_immersion_charts_fall_back_to_built_in_cards(self):
        text = self._text([_PFC])
        assert "custom:apexcharts-card" not in text
        stack = next(c for c in _all_cards(text) if c["type"] == "vertical-stack")
        assert [c["type"] for c in stack["cards"]] == ["history-graph", "tile", "statistics-graph"]
        graph = stack["cards"][0]
        assert [r["entity"] for r in graph["entities"]][0] == "sensor.hot_water_cylinder_temperature"

    def test_matching_ignores_case_and_path(self):
        types = self._types(["/local/Community/PowerFlowCard/POWER-FLOW-CARD-PLUS.js", _APEX])
        assert "custom:power-flow-card-plus" in types

    def test_header_names_the_missing_cards(self):
        header = self._text([])
        header = header[: header.index("views:")]
        assert "power-flow-card-plus" in header
        assert "apexcharts-card" in header
        assert "not installed" in header

    def test_header_has_no_note_when_cards_are_present(self):
        header = self._text([_PFC, _APEX])
        assert "not installed" not in header[: header.index("views:")]

    def test_no_apex_note_without_an_immersion_sensor(self):
        from custom_components.givenergy_inverter_manager.dashboard_builder import (
            build_dashboard_yaml,
        )

        with fake_hass(MINIMAL_CONFIG, FakeRegistry(enable_all=True)) as hass:
            text = build_dashboard_yaml(hass, ENTRY_ID, [_PFC])
        assert "not installed" not in text[: text.index("views:")]

    def test_fallback_dashboard_references_only_usable_entities(self):
        assert _referenced(self._text([])) <= set(default_entity_ids().values())


class TestReadingLovelaceResources:
    """async_lovelace_resource_urls reads hass.data['lovelace'] and fails open."""

    @staticmethod
    def _urls(data):
        import asyncio
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.dashboard_builder import (
            async_lovelace_resource_urls,
        )

        hass = MagicMock()
        hass.data = data
        return asyncio.run(async_lovelace_resource_urls(hass))

    @staticmethod
    def _collection(items, *, fail=False):
        from unittest.mock import AsyncMock, MagicMock

        resources = MagicMock()
        resources.async_get_info = AsyncMock(side_effect=OSError("boom") if fail else None)
        resources.async_items.return_value = items
        return resources

    def test_returns_urls_from_the_collection(self):
        from types import SimpleNamespace

        collection = self._collection([{"url": _PFC, "type": "module"}, {"type": "js"}])
        assert self._urls({"lovelace": SimpleNamespace(resources=collection)}) == [_PFC, ""]
        collection.async_get_info.assert_awaited_once()

    def test_not_loaded_returns_none(self):
        assert self._urls({}) is None

    def test_unreadable_collection_returns_none(self):
        from types import SimpleNamespace

        collection = self._collection([], fail=True)
        assert self._urls({"lovelace": SimpleNamespace(resources=collection)}) is None

    def test_dict_shaped_lovelace_data_is_read(self):
        collection = self._collection([{"url": _APEX}])
        assert self._urls({"lovelace": {"resources": collection}}) == [_APEX]


class TestSubViews:
    """Detail lives in sub-views, so the tabs stay short."""

    def _views(self, **kw):
        return yaml.safe_load(_build(**kw))["views"]

    def test_sub_views_have_no_tab_and_go_back_to_a_tab(self):
        views = self._views()
        tabs = {v["path"] for v in views if not v.get("subview")}
        for view in views:
            if view.get("subview"):
                assert view["back_path"] in tabs, view["path"]

    def test_every_link_opens_a_sub_view_that_exists(self):
        views = self._views()
        paths = {v["path"] for v in views}

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("tap_action", "icon_tap_action") and value.get("action") == "navigate":
                        yield value["navigation_path"]
                    else:
                        yield from walk(value)
            elif isinstance(node, list):
                for item in node:
                    yield from walk(item)

        targets = set(walk(views))
        assert targets, "no card links to a sub-view"
        assert targets <= paths

    def test_every_sub_view_is_reachable_from_its_back_view(self):
        views = self._views()
        for sub in (v for v in views if v.get("subview")):
            parent = next(v for v in views if v["path"] == sub["back_path"])
            assert f"navigation_path: {sub['path']}" in yaml.dump(parent), sub["path"]

    def test_tabs_stay_short(self):
        for view in self._views():
            if not view.get("subview"):
                assert len(view["cards"]) <= 6, view["path"]

    def test_energy_today_strip_is_not_repeated(self):
        titles = [
            c.get("title")
            for v in self._views()
            if not v.get("subview")
            for c in v["cards"]
            if c.get("title") == "Energy Today"
        ]
        assert len(titles) == 2  # Power Flow (4 columns) and Today (the full list)
        power_flow = _cards(_build(), "power-flow")
        strip = next(c for c in power_flow if c.get("title") == "Energy Today")
        assert len(strip["entities"]) == 4

    def test_battery_soc_gauge_is_only_on_the_now_strip(self):
        text = yaml.dump(self._views())
        assert text.count("type: gauge\n") >= 1
        gauges = [
            c
            for v in self._views()
            for g in v["cards"]
            for c in (g.get("cards") or [g])
            if c.get("type") == "gauge" and c.get("entity") == eid("battery_soc")
        ]
        assert len(gauges) == 1

    def test_immersion_power_chart_plots_power_not_energy(self):
        charts = [c for c in _cards(_build(), "immersion") if c.get("type") == "vertical-stack"]
        text = yaml.dump(charts)
        assert eid("immersion_power") in text
        assert "Immersion Power Today" not in text

    def test_no_immersion_or_ev_sub_view_without_the_devices(self):
        views = self._views(config=MINIMAL_CONFIG, registry=FakeRegistry(), ev_brand=None)
        paths = {v["path"] for v in views}
        assert "immersion" not in paths
        assert "ev-charger" not in paths
        assert "navigation_path: immersion" not in yaml.dump(views)
        assert "navigation_path: ev-charger" not in yaml.dump(views)

    def test_links_are_left_out_when_the_sub_view_is_empty(self):
        gone = {
            "overnight_charge_reason",
            "night_survival_reason",
            "battery_cycles",
            "battery_remaining_life",
            "days_since_full_charge",
            "inverter_temperature",
            "inverter_temperature_status",
        }
        text = _build(registry=FakeRegistry(enable_all=True, absent=gone))
        parsed = yaml.safe_load(text)
        paths = {v["path"] for v in parsed["views"]}
        assert "battery-detail" not in paths
        assert "navigation_path: battery-detail" not in text
