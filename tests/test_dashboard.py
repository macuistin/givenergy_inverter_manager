"""
test_dashboard.py — Tests for the dashboard generator (the dashboard package).

The service actions that write the generated file are tested in test_services.py.

What is tested:
  - _build_dashboard_yaml produces syntactically valid YAML
  - All expected sensor entity references appear in the output
  - The output is stable (same config → same YAML)
  - Dry run sensor entities are included in the Controls view
"""

import math
import re

import pytest
import yaml

from custom_components.givenergy_inverter_manager.const import CONF_FORECAST_ENTITY
from custom_components.givenergy_inverter_manager.core.battery import (
    OUTLOOK_CRITICAL,
    OUTLOOK_SAFE,
    OUTLOOK_WARNING,
)
from tests.dashboard_support import (
    ENTRY_ID,
    FULL_CONFIG,
    MINIMAL_CONFIG,
    FakeRegistry,
    all_cards,
    dashboard_dict,
    dashboard_text,
    default_entity_ids,
    view_cards,
)
from tests.dashboard_visibility import seen_for, shown_text

_IDS = default_entity_ids()


def eid(key: str) -> str:
    """Entity ID Home Assistant gives the entity with this unique ID suffix."""
    return _IDS[key]


def _build(config=None, registry=None, **kw) -> str:
    """Dashboard YAML. Defaults to every feature configured and every sensor enabled."""
    return dashboard_text(config, registry, **kw)


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

    def test_has_four_tabs_and_seven_sub_views(self):
        result = _build()
        parsed = yaml.safe_load(result)
        tabs = [v for v in parsed["views"] if not v.get("subview")]
        subs = [v for v in parsed["views"] if v.get("subview")]
        assert len(tabs) == 4
        assert len(subs) == 7

    def test_view_titles(self):
        result = _build()
        parsed = yaml.safe_load(result)
        titles = [v["title"] for v in parsed["views"] if not v.get("subview")]
        assert titles == ["Power Flow", "Today", "Bill", "Battery"]

    def test_view_paths(self):
        result = _build()
        parsed = yaml.safe_load(result)
        paths = [v["path"] for v in parsed["views"] if not v.get("subview")]
        assert paths == ["power-flow", "today", "bill", "battery"]
        sub_paths = [v["path"] for v in parsed["views"] if v.get("subview")]
        assert sub_paths == [
            "immersion",
            "ev-charger",
            "cost",
            "solar",
            "tariff",
            "battery-detail",
            "settings",
        ]

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

    def test_dry_run_sensors_on_power_flow(self):
        """The Power Flow tab shows the dry run state, which anyone may read."""
        result = _build()
        parsed = yaml.safe_load(result)
        view_yaml = yaml.dump(next(v for v in parsed["views"] if v["path"] == "power-flow"))
        assert eid("dry_run_active") in view_yaml
        assert eid("dry_run_last_skipped") in view_yaml

    def test_dry_run_warning_is_only_shown_while_dry_run_is_active(self):
        """The dry run section carries a visibility condition on the dry run sensor."""
        parsed = yaml.safe_load(_build())
        power_flow = next(v for v in parsed["views"] if v["path"] == "power-flow")
        banner = [s for s in power_flow["sections"] if s["cards"][0]["heading"] == "Dry run is on"]
        assert len(banner) == 1
        assert banner[0]["visibility"] == [
            {"condition": "state", "entity": eid("dry_run_active"), "state": "True"}
        ]

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
        pf_card = next(c for c in view_cards(pf_view) if "power-flow-card-plus" in c["type"])
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
        pf_card = next(c for c in view_cards(pf_view) if "power-flow-card-plus" in c["type"])
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


class TestPowerFlowTabChanges:
    """Verify the power flow tab layout improvements."""

    def test_only_the_battery_node_is_inverted(self):
        """Battery Power is positive while charging, but the flow card reads positive as
        discharging, so the battery node inverts it. Inverting any other node makes Home show 0W."""
        parsed = yaml.safe_load(_build())
        pf_view = next(v for v in parsed["views"] if v["path"] == "power-flow")
        pf_card = next(c for c in view_cards(pf_view) if "power-flow-card-plus" in c["type"])
        inverted = {
            node for node, cfg in pf_card["entities"].items()
            if isinstance(cfg, dict) and cfg.get("invert_state") is True
        }
        assert inverted == {"battery"}

    def test_clipping_as_secondary_info_on_solar(self):
        yaml = _build()
        solar_section = yaml[yaml.find("solar:") : yaml.find("battery:")]
        assert "secondary_info_entity:" in solar_section, (
            "Clipping must be secondary_info_entity on solar — not a separate large card."
        )

    def test_power_flow_sections_are_now_flow_and_totals(self):
        parsed = yaml.safe_load(_build())
        pf_view = next(v for v in parsed["views"] if v["path"] == "power-flow")
        assert [s["cards"][0]["heading"] for s in pf_view["sections"]] == [
            "Now",
            "Dry run is on",
            "Live power flow",
            "Energy today",
        ]

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

        text = shown_text({CONF_IMMERSION_SWITCH: "switch.immersion_heater"}, ev_brand=None)
        immersion = _cards(text, "immersion")
        assert not [c for c in immersion if c["type"] == "history-graph"]
        assert eid("immersion_water_temperature") not in text
        assert eid("immersion_today") in text

    def test_immersion_section_present_when_configured(self):
        """With a temperature sensor and a switch, the sub-view has one apexcharts chart."""
        yaml_text = shown_text()

        assert "apexcharts-card" in yaml_text, "Immersion section must use apexcharts-card"
        assert "graph_span: 12h" in yaml_text, "Must show 12 hours of history"
        assert eid("immersion_water_temperature") in yaml_text
        charts = [c for c in _cards(yaml_text, "immersion") if c["type"].startswith("custom:")]
        assert len(charts) == 1
        assert charts[0]["header"] == {"show": False}


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

    def test_immersion_temp_numbers_in_settings(self):
        """Immersion temperature number entities must appear in the Settings view."""
        result = _build()
        parsed = yaml.safe_load(result)
        controls_view = next(v for v in parsed["views"] if v.get("path") == "settings")
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
        markdown = [c for c in _cards(_build(), "power-flow") if c["type"] == "markdown"]
        assert all("Dry Run" in c["content"] for c in markdown), (
            "Income bar is now on the grid node — only the dry run banner is markdown"
        )

    def test_income_bar_references_grid_power(self):
        result = _build()
        assert "grid_power" in result

    def test_live_cost_rate_in_dashboard(self):
        result = _build()
        assert "live_grid_cost_rate" in result

    def test_grid_node_shows_the_live_cost_rate(self):
        parsed = yaml.safe_load(_build())
        pf_view = next(v for v in parsed["views"] if v["path"] == "power-flow")
        pf_card = next(c for c in view_cards(pf_view) if "power-flow-card-plus" in c["type"])
        assert pf_card["entities"]["grid"]["secondary_info"]["entity"] == eid("live_grid_cost_rate")


class TestSolarForecastCards:
    """Solar vs forecast section is present on the Today tab."""

    def test_solar_forecast_entities_in_today_view(self):
        result = _build()
        for key in (
            "solar_forecast_kwh_today",
            "solar_forecast_raw_today",
            "solar_actual_vs_forecast_pct",
            "yesterday_forecast_accuracy_pct",
        ):
            assert eid(key) in result

    @staticmethod
    def _tiles(text: str, path: str, heading: str) -> dict[str, str]:
        """{tile name: entity} of the section of the view at path that starts with heading."""
        view = next(v for v in yaml.safe_load(text)["views"] if v["path"] == path)
        section = next(s for s in view["sections"] if s["cards"][0].get("heading") == heading)
        return {c["name"]: c["entity"] for c in section["cards"][1:] if c["type"] == "tile"}

    def test_energy_today_shows_the_provider_forecast_and_the_share_generated(self):
        tiles = self._tiles(_build(), "power-flow", "Energy today")
        assert tiles["Forecast"] == eid("solar_forecast_raw_today")
        assert tiles["% of forecast"] == eid("solar_actual_vs_forecast_pct")
        assert list(tiles)[:3] == ["Generated", "Forecast", "% of forecast"]

    def test_energy_today_has_no_forecast_tiles_without_a_forecast_sensor(self):
        without_forecast = {k: v for k, v in FULL_CONFIG.items() if k != CONF_FORECAST_ENTITY}
        for config in (MINIMAL_CONFIG, without_forecast):
            tiles = self._tiles(_build(config=config), "power-flow", "Energy today")
            assert list(tiles)[:4] == ["Generated", "Used", "Imported", "Exported"]
            assert "Forecast" not in tiles and "% of forecast" not in tiles

    def test_the_sub_view_tells_the_provider_forecast_from_the_plan_forecast(self):
        tiles = self._tiles(_build(), "solar", "Against the forecast")
        assert tiles["Forecast"] == eid("solar_forecast_raw_today")
        assert tiles["% of forecast"] == eid("solar_actual_vs_forecast_pct")
        assert tiles["Plan forecast"] == eid("solar_forecast_kwh_today")

    def test_solar_graph_in_today_view_uses_statistics(self):
        graphs = [c for c in _cards(_build(), "solar") if c.get("type") == "statistics-graph"]
        assert [[r["entity"] for r in g["entities"]] for g in graphs] == [[eid("solar_today")]]


class TestSoCHistoryChart:
    """Battery SoC 24h history graph is present on the Battery tab."""

    def test_soc_history_graph_in_battery_view(self):
        graphs = [c for c in _cards(_build(), "battery") if c["type"] == "history-graph"]
        assert [[r["entity"] for r in g["entities"]] for g in graphs] == [[eid("battery_soc")]]

    def test_soc_and_power_are_not_drawn_on_one_axis(self):
        """A graph that mixes % and W squashes one of them flat."""
        for graph in (c for c in _cards(_build(), "battery") if c["type"] == "history-graph"):
            assert len(graph["entities"]) == 1


class TestYamlSerialisation:
    """The dashboard is built as a dict and serialised once."""

    def _dict(self):
        return dashboard_dict()

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
    """Section headings and tile names, which is what a person reads on the dashboard."""
    parsed = yaml.safe_load(text)
    out: list[str] = []
    for card in all_cards(parsed["views"]):
        if card["type"] == "heading":
            out.append(card["heading"])
        elif card["type"] == "tile":
            out.append(card["name"])
    return out


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
        assert [v["path"] for v in parsed["views"] if not v.get("subview")] == ["power-flow", "today", "bill", "battery"]


class TestFeatureGating:
    """EV, immersion, inverter temperature and forecast rows need the feature configured."""

    def _minimal(self, **kw) -> str:
        """What a dashboard shows for an install with none of the optional devices."""
        return shown_text(MINIMAL_CONFIG, **kw)

    def test_minimal_config_has_no_ev_rows(self):
        text = self._minimal(ev_brand=None)
        assert not {"EV charger", "EV", "EV charging"} & set(_titles(text))
        for key in ("ev_power", "ev_charger_state", "zappi_today", "zappi_cost_today"):
            assert eid(key) not in text
        assert "Car Charger" not in text

    def test_minimal_config_has_no_immersion_rows(self):
        text = self._minimal(ev_brand=None)
        assert not {"Immersion", "Immersion heater"} & set(_titles(text))
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
        assert "Against the forecast" not in _titles(text)
        assert eid("solar_forecast_kwh_today") not in text

    def test_full_config_has_every_feature(self):
        text = _build(config=FULL_CONFIG, registry=FakeRegistry(enable_all=True))
        titles = _titles(text)
        for title in ("EV charger", "Immersion heater", "Against the forecast"):
            assert title in titles
        for key in ("ev_power", "immersion_power", "inverter_temperature", "zappi_today"):
            assert eid(key) in text

    def test_each_feature_switches_on_independently(self):
        from custom_components.givenergy_inverter_manager.const import (
            CONF_INVERTER_TEMP_ENTITY,
        )

        text = shown_text({CONF_INVERTER_TEMP_ENTITY: "sensor.x"}, ev_brand=None)
        assert eid("inverter_temperature") in text
        assert eid("immersion_power") not in text
        assert eid("ev_power") not in text

    def test_the_temperature_rows_show_for_a_givtcp_entity_found_from_the_serial(self):
        from custom_components.givenergy_inverter_manager.const import CONF_INVERTER_SERIAL

        config = {CONF_INVERTER_SERIAL: "ab1234g567"}
        found = ("sensor.givtcp_ab1234g567_invertor_temperature",)
        assert eid("inverter_temperature") in shown_text(config, ev_brand=None, states=found)
        assert eid("inverter_temperature") not in shown_text(config, ev_brand=None)

    def test_a_charger_discovery_has_not_found_shows_nothing(self):
        """The EV cards follow the integration's own entities, which exist once it finds one."""
        text = shown_text(
            MINIMAL_CONFIG, ev_brand=None, states=("sensor.wallbox_charging_power",)
        )
        assert "EV charger" not in _titles(text)
        assert "sensor.wallbox_charging_power" not in text

    def test_immersion_with_only_a_temperature_sensor(self):
        from custom_components.givenergy_inverter_manager.const import (
            CONF_IMMERSION_TEMP_SENSOR,
        )

        text = shown_text({CONF_IMMERSION_TEMP_SENSOR: "sensor.t"}, ev_brand=None)
        assert "Water temperature" in _titles(text)
        assert eid("immersion_water_temperature") in text
        assert eid("immersion_power") not in text


def _cards(text: str, path: str) -> list[dict]:
    """Every card of the view at path, headings included."""
    parsed = yaml.safe_load(text)
    return view_cards(next(v for v in parsed["views"] if v["path"] == path))


class TestNowSection:
    """The first section of the first view holds the numbers worth a glance."""

    def _now(self, text: str) -> dict:
        parsed = yaml.safe_load(text)
        view = next(v for v in parsed["views"] if v["path"] == "power-flow")
        return view["sections"][0]

    def test_now_is_the_first_section_of_the_first_view(self):
        first = yaml.safe_load(_build())["views"][0]
        assert first["path"] == "power-flow"
        assert first["sections"][0]["cards"][0]["heading"] == "Now"

    def test_now_has_the_five_core_entities_battery_first(self):
        tiles = self._now(_build())["cards"][1:]
        assert [c["entity"] for c in tiles] == [
            eid("battery_soc"),
            eid("current_rate"),
            eid("import_cost_today"),
            eid("night_survival_confidence"),
            eid("next_cheap_rate_start"),
        ]
        assert [c["name"] for c in tiles] == [
            "Battery",
            "Rate per kWh",
            "Cost today",
            "Battery overnight",
            "Cheap from",
        ]

    def test_cheap_from_shows_the_countdown_summary_in_one_tile(self):
        """One tile reads like "23:00 (in 8 h 56 min)", so there is no tile of its own for the wait."""
        cards = self._now(_build())["cards"][1:]
        tile = next(c for c in cards if c["name"] == "Cheap from")
        assert tile["entity"] == eid("next_cheap_rate_start")
        assert tile["state_content"] == ["summary"]
        assert tile["grid_options"]["columns"] == "full"
        assert "Cheap in" not in [c["name"] for c in cards]
        assert eid("hours_to_cheap_rate") not in [c["entity"] for c in cards]

    def test_now_uses_only_tiles(self):
        assert {c["type"] for c in self._now(_build())["cards"][1:]} == {"tile"}

    def test_battery_tile_shows_a_bar_and_is_the_biggest(self):
        battery = self._now(_build())["cards"][1]
        assert battery["features"] == [{"type": "bar-gauge", "min": 0, "max": 100}]
        assert battery["grid_options"]["rows"] > 1

    def test_battery_overnight_opens_the_explanation(self):
        """The tile gives a short phrase, so a tap leads to the sentence behind it."""
        tile = self._now(_build())["cards"][4]
        assert tile["name"] == "Battery overnight"
        assert tile["tap_action"] == {"action": "navigate", "navigation_path": "battery-detail"}

    def test_now_drops_sensors_that_are_disabled_by_default(self):
        """Battery overnight confidence is off on a fresh install."""
        text = _build(registry=FakeRegistry())
        assert [c["entity"] for c in self._now(text)["cards"][1:]] == [
            eid("battery_soc"),
            eid("current_rate"),
            eid("import_cost_today"),
            eid("next_cheap_rate_start"),
        ]
        header = text[: text.index("views:")]
        assert "Battery Overnight Confidence" in header
        for name in ("Hours to Cheap Rate", "Next Cheap Rate Start"):
            assert name not in header


class TestLongTextStates:
    """Sentences go in a markdown card, not in a tile where they are cut off."""

    _SENTENCES = (
        "overnight_charge_reason",
        "night_survival_reason",
        "immersion_divert_reason",
        "ev_protection_reason",
    )

    def _battery(self):
        return _cards(_build(), "battery-detail")

    def test_sentence_entities_are_never_tiles(self):
        tiles = {c["entity"] for c in all_cards(yaml.safe_load(_build())["views"]) if "entity" in c}
        for key in self._SENTENCES:
            assert eid(key) not in tiles, key

    def test_sentence_entities_are_read_by_markdown_cards(self):
        markdown = " ".join(
            c["content"] for c in all_cards(yaml.safe_load(_build())["views"]) if "content" in c
        )
        for key in self._SENTENCES:
            assert f"{{{{ states('{eid(key)}') }}}}" in markdown, key

    def test_battery_detail_leads_with_night_survival_then_the_charge_reason(self):
        markdown = [c for c in self._battery() if c["type"] == "markdown"]
        assert len(markdown) == 2
        assert self._battery()[0]["heading"] == "Battery overnight"
        assert self._battery()[1] == markdown[0]
        assert f"{{{{ states('{eid('overnight_charge_reason')}') }}}}" == markdown[1]["content"]
        night = markdown[0]["content"]
        for key in ("night_survival_confidence", "estimated_soc_at_sunrise", "night_survival_reason"):
            assert eid(key) in night, key

    def test_markdown_cards_are_valid_jinja(self):
        for card in all_cards(yaml.safe_load(_build())["views"]):
            if card["type"] == "markdown":
                assert _render(card["content"], lambda entity: "x")

    def test_battery_heading_opens_the_battery_detail_view(self):
        heading = next(c for c in _cards(_build(), "battery") if c["type"] == "heading")
        assert heading["tap_action"] == {"action": "navigate", "navigation_path": "battery-detail"}
        assert "Tonight's charge plan" in [
            c["heading"] for c in _cards(_build(), "battery") if c["type"] == "heading"
        ]


def _render(content: str, states, attrs=None) -> str:
    """Render a markdown card the way the frontend does, with the template functions we use."""
    from jinja2 import Environment

    attrs = attrs or {}
    return Environment().from_string(content).render(
        states=states,
        state_attr=lambda entity, name: attrs.get((entity, name)),
        has_value=lambda entity: states(entity) not in ("unknown", "unavailable", ""),
        is_number=_is_number,
    )


def _is_number(value) -> bool:
    """Home Assistant's is_number: true for a finite number or a string that holds one."""
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


_OUTLOOKS = {
    "Safe": OUTLOOK_SAFE,
    "Warning": OUTLOOK_WARNING,
    "Critical": OUTLOOK_CRITICAL,
}


class TestNightSurvivalCard:
    """The reason behind the level is shown today, from entities that exist today."""

    _CONF = eid("night_survival_confidence")
    _SUNRISE = eid("estimated_soc_at_sunrise")
    _STATUS = eid("night_survival_reason")

    def _card(self, **kw) -> str:
        cards = _cards(_build(**kw), "battery-detail")
        return next(c for c in cards if c["type"] == "markdown")["content"]

    def _text(self, level, *, sunrise="13.6", status="Battery should last.", explanation=None):
        states = {self._CONF: level, self._SUNRISE: sunrise, self._STATUS: status}
        attrs = {(self._CONF, "outlook"): _OUTLOOKS[level]} if level in _OUTLOOKS else {}
        if explanation:
            attrs[(self._CONF, "explanation")] = explanation
        return _render(self._card(), lambda e: states.get(e, "unknown"), attrs).strip()

    def test_the_level_is_bold_and_comes_first(self):
        text = self._text("Warning")
        assert text.startswith("**Only just lasts the night**")

    def test_warning_is_explained_from_the_sunrise_estimate(self):
        text = self._text("Warning")
        assert text.endswith(
            "The battery should last until solar starts, but only just. It is expected to "
            "reach about 14% at sunrise, close to your minimum charge. A warning shows when "
            "the estimate is within 5 points of the minimum."
        )

    def test_warning_rounds_the_sunrise_estimate_to_whole_percent(self):
        assert "about 16% at sunrise" in self._text("Warning", sunrise="15.8")
        assert "about 13% at sunrise" in self._text("Warning", sunrise="12.6000001")

    def test_warning_copes_with_an_unavailable_estimate(self):
        text = self._text("Warning", sunrise="unavailable")
        assert "the minimum at sunrise" in text
        assert "0%" not in text

    def test_the_explanation_attribute_wins_when_present(self):
        text = self._text("Warning", explanation="Short by 1.2 kWh before 08:00.")
        assert text.endswith("Short by 1.2 kWh before 08:00.")
        assert "only just" not in text

    def test_critical_shows_the_status_text_with_the_shortfall(self):
        text = self._text("Critical", status="Short by 2.1 kWh before 08:00.")
        assert text == "**May run low**\n\nShort by 2.1 kWh before 08:00."

    def test_safe_shows_the_status_text(self):
        text = self._text("Safe", status="Battery should last until solar.")
        assert text == "**Lasts the night**\n\nBattery should last until solar."

    def test_without_the_confidence_sensor_only_the_status_text_is_shown(self):
        """Battery Overnight Confidence is disabled by default."""
        card = self._card(registry=FakeRegistry())
        assert self._CONF not in card
        text = _render(card, lambda e: "Battery should last.").strip()
        assert text == "**Battery overnight**\n\nBattery should last."

    def test_the_level_word_shows_when_the_sensor_has_no_outlook_attribute(self):
        states = {self._CONF: "Safe", self._SUNRISE: "40", self._STATUS: "ok"}
        text = _render(self._card(), lambda e: states.get(e, "unknown")).strip()
        assert text.startswith("**Safe**")

    def test_every_battery_overnight_tile_opens_the_explanation(self):
        tiles = [
            c
            for c in all_cards(yaml.safe_load(_build())["views"])
            if c["type"] == "tile" and c["entity"] == self._CONF
        ]
        assert tiles
        go = {"action": "navigate", "navigation_path": "battery-detail"}
        for tile in tiles:
            assert tile["tap_action"] == go
            assert tile["icon_tap_action"] == go


class TestStatisticsGraphs:
    """Sensors that reset at midnight draw a sawtooth in a history graph."""

    def test_no_history_graph_plots_a_midnight_reset_sensor(self):
        from tests.dashboard_support import midnight_reset_ids

        resets = midnight_reset_ids()
        graphs = [
            c
            for c in all_cards(yaml.safe_load(_build())["views"])
            if c.get("type") == "history-graph"
        ]
        assert graphs
        for card in graphs:
            plotted = {r["entity"] for r in card["entities"]}
            assert plotted.isdisjoint(resets), plotted

    def test_cost_and_solar_use_statistics_graphs(self):
        graphs = [
            c
            for path in ("cost", "solar")
            for c in _cards(shown_text(), path)
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
        assert types == {"heading", "tile"}

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
        titles = [c.get("heading") for c in _cards(_build(), "today")]
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
    return all_cards(yaml.safe_load(text)["views"])


class TestMissingHacsCards:
    """The custom cards are optional: without their resource the view uses built-in cards."""

    def _types(self, resources) -> set[str]:
        return {c["type"] for c in _all_cards(self._text(resources))}

    def _text(self, resources) -> str:
        return dashboard_text(resources=resources)

    def _shown(self, resources) -> str:
        return shown_text(resources=resources)

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
        text = self._shown([_APEX])
        assert "custom:power-flow-card-plus" not in text
        card = next(
            c
            for c in _cards(text, "power-flow")
            if c["type"] == "entities" and eid("solar_power") in yaml.dump(c)
        )
        assert "title" not in card
        rows = [r["entity"] for r in card["entities"]]
        for key in ("solar_power", "battery_power", "battery_soc", "grid_power", "house_load"):
            assert eid(key) in rows
        assert eid("ev_power") in rows
        assert eid("immersion_power") in rows

    def test_immersion_charts_fall_back_to_built_in_cards(self):
        text = self._shown([_PFC])
        assert "custom:apexcharts-card" not in text
        cards = _cards(text, "immersion")
        charts = [c["type"] for c in cards if c["type"].endswith("graph")]
        assert charts == ["history-graph"]
        graph = next(c for c in cards if c["type"] == "history-graph")
        rows = [r["entity"] for r in graph["entities"]]
        assert rows[0] == eid("immersion_water_temperature")
        assert rows[-1] == eid("immersion_power")
        assert all(c["type"] != "vertical-stack" for c in cards)

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
        text = dashboard_text(MINIMAL_CONFIG, resources=[_PFC], ev_brand=None)
        assert "not installed" not in text[: text.index("views:")]

    def test_fallback_dashboard_references_only_usable_entities(self):
        assert _referenced(self._text([])) <= set(default_entity_ids().values())


class TestReadingLovelaceResources:
    """async_lovelace_resource_urls reads hass.data['lovelace'] and fails open."""

    @staticmethod
    def _urls(data):
        import asyncio
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.dashboard import (
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
        """Counted on what is shown, with every optional device present."""
        for view in seen_for(ev=True, switch=True, sensor=True)["views"]:
            if not view.get("subview"):
                assert len(view["sections"]) <= 4, view["path"]
                assert len(view_cards(view)) <= 20, view["path"]

    def test_energy_today_totals_are_not_repeated_in_full(self):
        views = {v["path"]: v for v in self._views()}

        def tiles_after(path: str, heading: str) -> list[str]:
            for section in views[path]["sections"]:
                if section["cards"][0].get("heading") == heading:
                    return [c["name"] for c in section["cards"][1:] if c["type"] == "tile"]
            raise AssertionError(heading)

        assert tiles_after("power-flow", "Energy today")[:7] == [
            "Generated",
            "Forecast",
            "% of forecast",
            "Used",
            "Imported",
            "Exported",
            "Self-sufficient",
        ]
        assert tiles_after("today", "Energy") == [
            "Generated",
            "Used",
            "Imported",
            "Exported",
            "EV",
            "Immersion",
        ]

    def test_battery_soc_is_shown_as_a_bar_on_two_tiles_and_never_a_gauge_card(self):
        cards = all_cards(self._views())
        assert not [c for c in cards if c["type"] == "gauge"]
        bars = [
            c
            for c in cards
            if c["type"] == "tile"
            and c["entity"] == eid("battery_soc")
            and c["features"] == [{"type": "bar-gauge", "min": 0, "max": 100}]
        ]
        assert len(bars) == 2  # the Now section and the Battery tab

    def test_the_heater_is_a_stepped_band_on_the_temperature_chart(self):
        """The sensor only updates on change, so a smooth line would draw false ramps."""
        charts = [c for c in _cards(_build(), "immersion") if c["type"] == "custom:apexcharts-card"]
        heater = [s for c in charts for s in c["series"] if s["entity"] == eid("immersion_power")]
        assert heater
        assert {s["curve"] for s in heater} == {"stepline"}
        assert "Immersion Power Today" not in yaml.dump(charts)

    def test_no_immersion_or_ev_view_is_shown_without_the_devices(self):
        """The views stay in a stored file, so a device added later has somewhere to show."""
        views = seen_for()["views"]
        assert {v["path"] for v in views} >= {"immersion", "ev-charger"}
        for view in views:
            if view["path"] in ("immersion", "ev-charger"):
                assert view["sections"] == []
        assert "navigation_path: immersion" not in yaml.dump(views)
        assert "navigation_path: ev-charger" not in yaml.dump(views)

    def test_links_are_left_out_when_the_sub_view_is_empty(self):
        gone = {
            "overnight_charge_reason",
            "night_survival_reason",
            "night_survival_confidence",
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


class TestSectionsLayout:
    """Every view is a sections view of headed sections of tiles."""

    _COLOURS = {"amber", "green", "blue", "orange", "teal", "indigo"}

    def _views(self, **kw):
        return yaml.safe_load(_build(**kw))["views"]

    def test_every_view_is_a_sections_view(self):
        for view in self._views():
            assert view["type"] == "sections", view["path"]
            assert view["max_columns"] in (3, 4), view["path"]
            assert "cards" not in view, view["path"]
            assert view["sections"], view["path"]

    def test_every_section_is_a_grid_that_starts_with_a_heading(self):
        for view in self._views():
            for section in view["sections"]:
                assert section["type"] == "grid", view["path"]
                first = section["cards"][0]
                assert first["type"] == "heading", (view["path"], first)
                assert first["heading_style"] == "title"
                assert first["heading"]
                assert len(section["cards"]) > 1, (view["path"], first["heading"])

    def test_no_heading_is_left_alone_at_the_end_of_a_section(self):
        for view in self._views():
            for section in view["sections"]:
                assert section["cards"][-1]["type"] != "heading", view["path"]

    def test_no_nested_grids_or_stacks(self):
        for card in all_cards(self._views()):
            assert card["type"] not in {"grid", "vertical-stack", "horizontal-stack"}, card
            assert "cards" not in card, card

    def test_no_card_title_repeats_a_heading(self):
        for card in all_cards(self._views()):
            assert "title" not in card, card

    def test_each_view_has_unique_headings(self):
        for view in self._views():
            headings = [c["heading"] for c in view_cards(view) if c["type"] == "heading"]
            assert len(headings) == len(set(headings)), view["path"]

    def test_tile_names_are_short_enough_not_to_truncate(self):
        for card in all_cards(self._views()):
            if card["type"] != "tile":
                continue
            assert len(card["name"]) <= 22, card["name"]
            if card["grid_options"]["columns"] == 6:
                assert len(card["name"]) <= 15, card["name"]
            assert card["name"] == card["name"].strip() and card["name"], card

    def test_tiles_are_horizontal_and_sized_on_the_grid(self):
        for card in all_cards(self._views()):
            if card["type"] == "tile":
                assert "vertical" not in card
                assert card["grid_options"]["columns"] in (6, "full"), card["name"]

    def test_tile_colours_come_from_the_palette(self):
        colours = {c["color"] for c in all_cards(self._views()) if c["type"] == "tile" and "color" in c}
        assert colours <= self._COLOURS
        assert {"amber", "green", "blue"} <= colours

    def test_graphs_and_charts_take_the_full_width(self):
        graphs = [
            c
            for c in all_cards(self._views())
            if c["type"] in {"history-graph", "statistics-graph", "custom:apexcharts-card"}
            or c["type"].startswith("custom:power-flow")
        ]
        assert graphs
        for card in graphs:
            assert card["grid_options"]["columns"] == "full", card["type"]
            if card["type"].endswith("-graph"):
                assert card["grid_options"]["rows"] >= 3, card["type"]

    def test_markdown_cards_take_the_full_width(self):
        for card in all_cards(self._views()):
            if card["type"] == "markdown":
                assert card["grid_options"]["columns"] == "full"

    def test_settings_use_tile_features(self):
        tiles = [c for c in _cards(_build(), "settings") if c["type"] == "tile"]
        by_domain = {}
        for tile in tiles:
            by_domain.setdefault(tile["entity"].split(".")[0], []).append(tile)
        assert by_domain["number"] and by_domain["switch"]
        for tile in by_domain["number"]:
            assert tile["features"] == [{"type": "numeric-input", "style": "slider"}]
        for tile in by_domain["switch"]:
            assert tile["features"] == [{"type": "toggle"}]
        assert {t["entity"] for t in by_domain["number"]} == {
            eid("charge_target_override"),
            eid("immersion_target_temp"),
            eid("immersion_min_temp"),
            eid("immersion_hysteresis"),
        }

    def test_settings_have_no_entities_lists(self):
        assert "entities" not in {c["type"] for c in _cards(_build(), "settings")}

    def test_every_headed_section_opens_a_view_that_exists_when_it_has_a_tap_action(self):
        paths = {v["path"] for v in self._views()}
        for card in all_cards(self._views()):
            if card["type"] == "heading" and "tap_action" in card:
                assert card["tap_action"]["navigation_path"] in paths

    def test_only_built_in_card_types_without_the_hacs_cards(self):
        text = _build()
        parsed = yaml.safe_load(text)
        built = yaml.safe_load(dashboard_text(resources=[]))
        types = {c["type"] for c in all_cards(built["views"])}
        assert not {t for t in types if t.startswith("custom:")}
        assert types <= {"heading", "tile", "markdown", "entities", "history-graph", "statistics-graph"}
        assert len(parsed["views"]) == len(built["views"])

    def test_minimal_install_still_has_every_tab_with_headed_sections(self):
        views = yaml.safe_load(_build(config=MINIMAL_CONFIG, registry=FakeRegistry(), ev_brand=None))["views"]
        tabs = [v for v in views if not v.get("subview")]
        assert [v["path"] for v in tabs] == ["power-flow", "today", "bill", "battery"]
        for view in views:
            for section in view["sections"]:
                assert section["cards"][0]["type"] == "heading"
