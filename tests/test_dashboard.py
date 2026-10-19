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
from custom_components.givenergy_inverter_manager.dashboard.templates import (
    RUN_LIMIT_BANNER_TEXT,
    tonight_line_template,
)
from custom_components.givenergy_inverter_manager.dashboard.views import TABS
from tests.dashboard_support import (
    ENTRY_ID,
    FULL_CONFIG,
    MINIMAL_CONFIG,
    FakeRegistry,
    all_cards,
    dashboard_text,
    default_entity_ids,
    devices_of,
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

    def test_has_five_tabs_and_three_sub_views(self):
        result = _build()
        parsed = yaml.safe_load(result)
        tabs = [v for v in parsed["views"] if not v.get("subview")]
        subs = [v for v in parsed["views"] if v.get("subview")]
        assert len(tabs) == 5
        assert len(subs) == 3

    def test_view_titles(self):
        result = _build()
        parsed = yaml.safe_load(result)
        titles = [v["title"] for v in parsed["views"] if not v.get("subview")]
        assert titles == ["Home energy", "Today", "Tonight", "Tomorrow", "Bill & tariff"]
        sub_titles = [v["title"] for v in parsed["views"] if v.get("subview")]
        assert sub_titles == ["Hot water", "EV charger", "Settings"]

    def test_view_paths(self):
        result = _build()
        parsed = yaml.safe_load(result)
        paths = [v["path"] for v in parsed["views"] if not v.get("subview")]
        assert paths == ["power-flow", "today", "plan", "tomorrow", "bill"]
        sub_paths = [v["path"] for v in parsed["views"] if v.get("subview")]
        assert sub_paths == ["immersion", "ev-charger", "settings"]

    def test_the_tabs_come_first_each_with_its_icon_and_no_back_arrow(self):
        views = yaml.safe_load(_build())["views"]
        tabs = views[:5]
        assert {v["path"]: v["icon"] for v in tabs} == {
            "power-flow": "mdi:home-lightning-bolt",
            "today": "mdi:calendar-today",
            "plan": "mdi:battery-clock",
            "tomorrow": "mdi:weather-sunset-up",
            "bill": "mdi:receipt-text",
        }
        assert {v["path"] for v in tabs} == TABS
        for tab in tabs:
            assert "subview" not in tab, tab["path"]
            assert "back_path" not in tab, tab["path"]

    def test_the_sub_views_go_back_to_home_energy(self):
        views = yaml.safe_load(_build())["views"]
        for view in views[5:]:
            assert view["subview"] is True, view["path"]
            assert view["back_path"] == "power-flow", view["path"]
            assert view["path"] not in TABS

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
        banner = [s for s in power_flow["sections"] if _heading_of(s) == "Dry run is on"]
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
            node
            for node, cfg in pf_card["entities"].items()
            if isinstance(cfg, dict) and cfg.get("invert_state") is True
        }
        assert inverted == {"battery"}

    def test_clipping_as_secondary_info_on_solar(self):
        yaml = _build()
        solar_section = yaml[yaml.find("solar:") : yaml.find("battery:")]
        assert "secondary_info_entity:" in solar_section, (
            "Clipping must be secondary_info_entity on solar — not a separate large card."
        )

    def test_home_energy_sections_are_banners_flow_tonight_and_a_section_for_each_device(self):
        parsed = yaml.safe_load(_build())
        pf_view = next(v for v in parsed["views"] if v["path"] == "power-flow")
        assert [_heading_of(s) for s in pf_view["sections"]] == [
            "Dry run is on",
            "Something else is setting your charge target",
            "Finish setting up",
            "Needs your attention",
            "Start the alternative heating",
            "The immersion stopped at its longest run",
            "Energy",
            "Where it came from",
            "Hot water",
            "EV charger",
        ]

    def test_home_energy_has_no_repairs_banner_without_the_repairs_sensor(self):
        registry = FakeRegistry(enable_all=True, absent={"active_repairs"})
        parsed = yaml.safe_load(_build(registry=registry))
        pf_view = next(v for v in parsed["views"] if v["path"] == "power-flow")
        headings = [_heading_of(s) for s in pf_view["sections"]]
        assert "Needs your attention" not in headings
        assert headings[5] == "Energy"

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
        """Clipping is the solar node's secondary info, never a card of its own."""
        clipping = eid("is_clipping")
        for resources in (None, ["/hacsfiles/power-flow-card-plus/power-flow-card-plus.js"]):
            cards = all_cards(yaml.safe_load(_build(resources=resources))["views"])
            naming = [c for c in cards if clipping in yaml.dump(c)]
            assert all(c["type"] == "custom:power-flow-card-plus" for c in naming), naming
            for card in naming:
                solar = card["entities"]["solar"]
                assert solar["secondary_info_entity"] == clipping
                assert clipping not in yaml.dump({k: v for k, v in card["entities"].items() if k != "solar"})

    def test_immersion_section_absent_without_temperature_sensor(self):
        """A switch but no temperature sensor gives the heater's figures and week, no chart."""
        from custom_components.givenergy_inverter_manager.const import CONF_IMMERSION_SWITCH

        text = shown_text({CONF_IMMERSION_SWITCH: "switch.immersion_heater"}, ev_brand=None)
        immersion = _cards(text, "immersion")
        assert not [c for c in immersion if c["type"] == "history-graph"]
        assert eid("immersion_water_temperature") not in text
        assert eid("immersion_today") in text

    def test_immersion_section_present_when_configured(self):
        """With a temperature sensor and a switch, the sub-view has one built-in history graph."""
        yaml_text = shown_text()

        assert "apexcharts" not in yaml_text
        assert eid("immersion_water_temperature") in yaml_text
        charts = [c for c in _cards(yaml_text, "immersion") if c["type"] == "history-graph"]
        assert len(charts) == 1
        assert charts[0]["hours_to_show"] == 12, "Must show 12 hours of history"


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


class TestIncomeBar:
    """Live cost rate is embedded in the grid node secondary_info (no separate markdown card)."""

    def test_no_income_markdown_card_on_power_flow(self):
        markdown = [c for c in _cards(_build(), "power-flow") if c["type"] == "markdown"]
        assert all(
            "dry run" in c["content"].lower()
            or "charge target" in c["content"].lower()
            or "state_attr('" in c["content"]
            or c["content"] == tonight_line_template(eid("charge_plan"))
            or c["content"] == RUN_LIMIT_BANNER_TEXT
            for c in markdown
        ), "Income bar is on the grid node: only the banners, the checklist and Tonight are markdown"

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


class TestGridCostRateUnit:
    """The grid node names the unit of the live cost rate: the currency symbol per hour."""

    @staticmethod
    def _secondary_info(currency: str | None) -> dict:
        config = {**FULL_CONFIG, **({"currency": currency} if currency else {})}
        parsed = yaml.safe_load(_build(config))
        pf_view = next(v for v in parsed["views"] if v["path"] == "power-flow")
        pf_card = next(c for c in view_cards(pf_view) if "power-flow-card-plus" in c["type"])
        return pf_card["entities"]["grid"]["secondary_info"]

    @pytest.mark.parametrize(
        ("currency", "unit"),
        [(None, "€/h"), ("EUR", "€/h"), ("GBP", "£/h"), ("SEK", "kr/h"), ("USD", "$/h")],
    )
    def test_the_unit_is_the_configured_currency_symbol_per_hour(self, currency, unit):
        info = self._secondary_info(currency)
        assert info["unit_of_measurement"] == unit
        assert info["entity"] == eid("live_grid_cost_rate")

    def test_the_node_still_shows_a_zero_rate(self):
        assert self._secondary_info("GBP")["display_zero"] is True


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
    def _figures(text: str, path: str, heading: str) -> dict[str, str]:
        """{figure name: entity} of the glance cards under this heading of the view at path."""
        cards = _cards(text, path)
        start = next(i for i, c in enumerate(cards) if c.get("heading") == heading)
        under = []
        for card in cards[start + 1 :]:
            if card["type"] == "heading":
                break
            under.append(card)
        return {r["name"]: r["entity"] for c in under if c["type"] == "glance" for r in c["entities"]}

    def test_today_has_no_forecast_figures_without_a_forecast_sensor(self):
        without_forecast = {k: v for k, v in FULL_CONFIG.items() if k != CONF_FORECAST_ENTITY}
        for config in (MINIMAL_CONFIG, without_forecast):
            text = _build(config=config)
            assert "Forecast" not in _titles(text)
            for key in ("solar_forecast_raw_today", "solar_actual_vs_forecast_pct"):
                assert eid(key) not in yaml.dump(_cards(text, "today")), key
            # Tomorrow keeps only what the day should cost, which needs no forecast sensor.
            tomorrow = [c.get("heading") for c in _cards(text, "tomorrow") if c["type"] == "heading"]
            assert tomorrow == ["What it should cost"]
            registry = FakeRegistry(enable_all=True, absent={"tomorrow_outlook"})
            views = yaml.safe_load(_build(config=config, registry=registry))["views"]
            assert "tomorrow" not in [v["path"] for v in views]

    def test_the_today_view_tells_the_provider_forecast_from_the_plan_forecast(self):
        figures = self._figures(_build(), "today", "Forecast")
        assert figures["Forecast"] == eid("solar_forecast_raw_today")
        assert figures["Reached"] == eid("solar_actual_vs_forecast_pct")
        assert figures["Planned on"] == eid("solar_forecast_kwh_today")

    def test_solar_graphs_on_the_today_tab_use_statistics(self):
        """The hour by hour chart stacks solar with the battery and the grid, and the last
        seven days plot what was generated."""
        cards = _cards(_build(), "today")
        graphs = [c for c in cards if c.get("type") == "statistics-graph"]
        solar = [g for g in graphs if eid("solar_today") in [r["entity"] for r in g["entities"]]]
        assert [(g["period"], g["chart_type"]) for g in solar] == [
            ("hour", "bar-stack"),
            ("day", "bar"),
        ]
        assert [r["entity"] for r in solar[0]["entities"]] == [
            eid("solar_today"),
            eid("battery_discharge_kwh_today"),
            eid("import_today"),
        ]
        assert [r["entity"] for r in solar[1]["entities"]] == [eid("solar_today")]


class TestSoCHistoryChart:
    """Battery SoC 24h history graph is present on the Battery tab."""

    def test_the_charge_draws_its_last_day_and_a_half_on_the_tonight_view(self):
        """One line of the charge, so the night before and today read on one chart."""
        battery = _section_cards(_build(), "plan", "Battery, last day and a half")
        (graph,) = [c for c in _cards(_build(), "plan") if c["type"] == "history-graph"]
        assert graph in battery
        assert [r["entity"] for r in graph["entities"]] == [eid("battery_soc")]
        assert graph["hours_to_show"] == 36

    def test_soc_and_power_are_not_drawn_on_one_axis(self):
        """A graph that mixes % and W squashes one of them flat."""
        for graph in (c for c in _cards(_build(), "plan") if c["type"] == "history-graph"):
            assert len(graph["entities"]) == 1


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

    def test_unregistered_entity_is_left_out(self):
        text = _build(registry=FakeRegistry(enable_all=True, absent={"cheap_rate_floor_status"}))
        assert eid("cheap_rate_floor_status") not in text
        assert "Cheap Rate Floor" not in text

    def test_dashboard_is_never_empty(self):
        parsed = yaml.safe_load(_build(config=MINIMAL_CONFIG, registry=FakeRegistry()))
        assert [v["path"] for v in parsed["views"] if not v.get("subview")] == [
            "power-flow",
            "today",
            "plan",
            "tomorrow",
            "bill",
        ]
        for view in parsed["views"]:
            assert view["sections"], view["path"]


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
        assert not {"Forecast", "Tomorrow"} & set(_titles(text))
        assert eid("solar_forecast_kwh_today") not in text

    def test_full_config_has_every_feature(self):
        text = _build(config=FULL_CONFIG, registry=FakeRegistry(enable_all=True))
        titles = _titles(text)
        for title in ("EV charger", "Hot water", "Forecast", "Tomorrow"):
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
        text = shown_text(MINIMAL_CONFIG, ev_brand=None, states=("sensor.wallbox_charging_power",))
        assert "EV charger" not in _titles(text)
        assert "sensor.wallbox_charging_power" not in text

    def test_immersion_with_only_a_temperature_sensor(self):
        from custom_components.givenergy_inverter_manager.const import (
            CONF_IMMERSION_TEMP_SENSOR,
        )

        text = shown_text({CONF_IMMERSION_TEMP_SENSOR: "sensor.t"}, ev_brand=None)
        assert "Hot water" in _titles(text)
        assert eid("immersion_water_temperature") in text
        assert eid("immersion_power") not in text
        assert eid("immersion_target_temp") not in text
        assert eid("immersion_divert_reason") not in text


def _cards(text: str, path: str) -> list[dict]:
    """Every card of the view at path, headings included."""
    parsed = yaml.safe_load(text)
    return view_cards(next(v for v in parsed["views"] if v["path"] == path))


def _heading_of(section: dict) -> str:
    """The first heading of a section. Home energy's Tonight section opens with a line instead."""
    return next(c["heading"] for c in section["cards"] if c["type"] == "heading")


def _section_cards(text: str, path: str, heading: str) -> list[dict]:
    """Every card of the section of the view at path that starts with this heading."""
    view = next(v for v in yaml.safe_load(text)["views"] if v["path"] == path)
    section = next(s for s in view["sections"] if s["cards"][0].get("heading") == heading)
    return view_cards({"sections": [section]})


class TestHomeEnergyOrder:
    """Home energy: the Energy heading with the flow, the Tonight line and sources, the devices."""

    @staticmethod
    def _view():
        return next(v for v in yaml.safe_load(_build())["views"] if v["path"] == "power-flow")

    def test_home_energy_is_the_first_view_and_the_power_flow_its_first_lasting_section(self):
        """The banners above it show only while they apply."""
        first = yaml.safe_load(_build())["views"][0]
        assert first["path"] == "power-flow"
        lasting = [s for s in first["sections"] if "visibility" not in s]
        assert [_heading_of(s) for s in lasting] == [
            "Energy",
            "Where it came from",
            "Hot water",
            "EV charger",
        ]

    def test_the_flow_and_the_tonight_line_are_two_columns_wide_and_the_devices_one(self):
        spans = {_heading_of(s): s.get("column_span", 1) for s in self._view()["sections"]}
        assert spans["Energy"] == 2
        assert spans["Where it came from"] == 2
        assert spans["Hot water"] == 1
        assert spans["EV charger"] == 1

    def test_hot_water_and_the_ev_charger_are_sections_of_their_own(self):
        """Two one-column sections sit side by side on a tablet and stack on a phone."""
        sections = {_heading_of(s): s for s in self._view()["sections"]}
        for title in ("Hot water", "EV charger"):
            headings = [c["heading"] for c in sections[title]["cards"] if c["type"] == "heading"]
            assert headings == [title]

    def test_the_tonight_line_opens_the_section_under_the_flow(self):
        section = next(s for s in self._view()["sections"] if _heading_of(s) == "Where it came from")
        first, heading, bar = section["cards"]
        assert first["type"] == "markdown"
        assert first["content"] == tonight_line_template(eid("charge_plan"))
        assert heading["heading"] == "Where it came from"
        assert bar["type"] == "distribution"

    def test_the_old_story_is_gone_from_home_energy(self):
        """Right now, its sentence, the day chips, the device chips and the shortcuts left."""
        view = self._view()
        headings = {c["heading"] for c in view_cards(view) if c["type"] == "heading"}
        assert not headings & {
            "Live power flow",
            "Right now",
            "Today so far",
            "Hot water and EV",
            "More",
        }
        assert not [c for c in view_cards(view) if c["type"] == "shortcut"]
        text = yaml.dump(view)
        assert "Running on" not in text
        for key in ("current_rate", "next_cheap_rate_start", "night_survival_confidence"):
            assert eid(key) not in text, key

    def test_the_heading_chips_are_the_only_chips_of_home_energy(self):
        badges = [b for c in view_cards(self._view()) for b in c.get("badges", [])]
        assert [b.get("entity") or b["text"] for b in badges] == [
            "Settings",
            eid("solar_today"),
            eid("import_cost_today"),
            eid("self_sufficiency"),
        ]


class TestLongTextStates:
    """Sentences go in a markdown card, not in a tile where they are cut off."""

    _SENTENCES = (
        "overnight_charge_reason",
        "night_survival_reason",
        "immersion_divert_reason",
        "ev_protection_reason",
    )

    def _tonight(self):
        return _section_cards(_build(), "plan", "Tonight")

    def test_sentence_entities_are_never_tiles(self):
        tiles = {c["entity"] for c in all_cards(yaml.safe_load(_build())["views"]) if "entity" in c}
        for key in self._SENTENCES:
            assert eid(key) not in tiles, key

    def test_sentence_entities_are_read_by_markdown_cards(self):
        markdown = " ".join(
            c["content"] for c in all_cards(yaml.safe_load(_build())["views"]) if "content" in c
        )
        for key in self._SENTENCES:
            assert self._full_text_expression(key) in markdown, key

    @staticmethod
    def _full_text_expression(key: str) -> str:
        """The expression that reads the full text kept in the attribute, else the state."""
        entity = eid(key)
        return f"state_attr('{entity}', 'full_text') or states('{entity}')"

    @classmethod
    def _full_text(cls, key: str) -> str:
        """The template that prints the full text kept in the attribute, else the state."""
        return f"{{{{ {cls._full_text_expression(key)} }}}}"

    def test_a_sentence_card_prints_the_full_text_attribute_over_the_cut_state(self):
        entity = eid("overnight_charge_reason")
        cut, full = "A long reason…", "A long reason that the state had to cut."
        card = self._full_text("overnight_charge_reason")

        shown = _render(card, lambda e: cut, {(entity, "full_text"): full})

        assert shown == full

    def test_a_sentence_card_falls_back_to_the_state_without_the_attribute(self):
        card = self._full_text("overnight_charge_reason")

        assert _render(card, lambda e: "The state.", {}) == "The state."

    def test_tonight_leads_with_the_charge_then_night_survival_then_folds_the_reason(self):
        tonight = self._tonight()
        markdown = [c for c in tonight if c["type"] == "markdown"]
        assert len(markdown) == 3
        assert tonight[0]["heading"] == "Tonight"
        assert tonight[1:3] == markdown[:2]
        assert eid("overnight_charge_target") in markdown[0]["content"]
        assert markdown[2]["content"] == (
            "<details><summary>Why this plan</summary>\n\n"
            f"{self._full_text('overnight_charge_reason')}\n\n</details>"
        )
        night = markdown[1]["content"]
        for key in (
            "night_survival_confidence",
            "estimated_soc_at_sunrise",
            "night_survival_reason",
        ):
            assert eid(key) in night, key

    def test_markdown_cards_are_valid_jinja(self):
        checklist = {
            (eid("setup_progress"), "items"): [
                {"label": "Tariff set", "done": True, "required": True}
            ]
        }
        for card in all_cards(yaml.safe_load(_build())["views"]):
            if card["type"] == "markdown":
                assert _render(card["content"], lambda entity: "x", checklist)

    def test_the_tonight_view_leads_with_tonights_charge_then_the_battery(self):
        """The overnight detail sits on the same view, so no heading opens another view."""
        headings = [c for c in _cards(_build(), "plan") if c["type"] == "heading"]
        assert [h["heading"] for h in headings] == [
            "Tonight",
            "Battery, last day and a half",
            "Battery health",
        ]
        assert not [h for h in headings if "tap_action" in h]


def _render(content: str, states, attrs=None) -> str:
    """Render a markdown card the way the frontend does, with the template functions we use."""
    from jinja2 import Environment

    attrs = attrs or {}
    return (
        Environment()
        .from_string(content)
        .render(
            states=states,
            state_attr=lambda entity, name: attrs.get((entity, name)),
            # True, so the banner's start_now branches render and are checked for syntax.
            is_state=lambda entity, state: True,
            has_value=lambda entity: states(entity) not in ("unknown", "unavailable", ""),
            is_number=_is_number,
        )
    )


def _is_number(value) -> bool:
    """Home Assistant's is_number: true for a finite number or a string that holds one."""
    try:
        return math.isfinite(float(value))
    except TypeError, ValueError:
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
    _WITH_CHARGE = eid("estimated_soc_at_sunrise_with_charge")
    _STATUS = eid("night_survival_reason")

    def _card(self, **kw) -> str:
        """The night survival card of Tonight: the one that reads the status sentence."""
        cards = _section_cards(_build(**kw), "plan", "Tonight")
        markdown = [c["content"] for c in cards if c["type"] == "markdown"]
        (card,) = [content for content in markdown if self._STATUS in content]
        return card

    def _text(
        self,
        level,
        *,
        sunrise="13.6",
        status="Battery should last.",
        explanation=None,
        with_charge=None,
        added=None,
    ):
        states = {self._CONF: level, self._SUNRISE: sunrise, self._STATUS: status}
        attrs = {(self._CONF, "outlook"): _OUTLOOKS[level]} if level in _OUTLOOKS else {}
        if explanation:
            attrs[(self._CONF, "explanation")] = explanation
        if with_charge is not None:
            states[self._WITH_CHARGE] = with_charge
            attrs[(self._WITH_CHARGE, "charge_added_pct")] = added
        return _render(self._card(), lambda e: states.get(e, "unknown"), attrs).strip()

    def test_the_level_is_bold_and_comes_first(self):
        """The heading above the card says what the level is of, so the card does not repeat it."""
        text = self._text("Warning")
        assert text.startswith("**Only just lasts the night**")

    def test_warning_is_explained_from_the_sunrise_estimate(self):
        text = self._text("Warning")
        assert text.endswith(
            "The battery should last until solar starts, but only just. Without a charge it "
            "is expected to reach about 14% at sunrise, close to your minimum charge. A "
            "warning shows when the estimate is within 5 points of the minimum."
        )

    def test_warning_also_gives_the_figure_with_the_planned_charge_while_one_counts(self):
        text = self._text("Warning", with_charge="89.2", added=64.5)
        assert text.endswith(
            "Without a charge it is expected to reach about 14% at sunrise, close to your "
            "minimum charge. With tonight's planned charge it should reach about 89%. A "
            "warning shows when the estimate is within 5 points of the minimum."
        )

    @pytest.mark.parametrize("added", [0, 0.0, None, "unknown"])
    def test_warning_leaves_the_planned_charge_out_when_it_adds_nothing(self, added):
        text = self._text("Warning", with_charge="13.6", added=added)
        assert "planned charge" not in text
        assert "about 14% at sunrise, close to your minimum charge." in text

    def test_warning_leaves_the_planned_charge_out_when_its_figure_is_unavailable(self):
        text = self._text("Warning", with_charge="unavailable", added=64.5)
        assert "planned charge" not in text

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
        assert text == "Battery should last."

    def test_the_level_word_shows_when_the_sensor_has_no_outlook_attribute(self):
        states = {self._CONF: "Safe", self._SUNRISE: "40", self._STATUS: "ok"}
        text = _render(self._card(), lambda e: states.get(e, "unknown")).strip()
        assert text.startswith("**Safe**")

    def test_the_outlook_is_explained_on_tonight_and_not_repeated_on_home_energy(self):
        """Home energy states only whether tonight charges. The outlook and its reason stay on
        the Tonight tab, under the heading that explains them."""
        views = yaml.safe_load(_build())["views"]
        home = next(v for v in views if v["path"] == "power-flow")
        assert self._CONF not in yaml.dump(home)
        tonight = next(v for v in views if v["path"] == "plan")
        sections = [s for s in tonight["sections"] if self._CONF in yaml.dump(s)]
        assert [_heading_of(s) for s in sections] == ["Tonight"]


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

    def test_the_today_view_uses_statistics_graphs(self):
        graphs = [c for c in _cards(shown_text(), "today") if c["type"] == "statistics-graph"]
        assert [(g["period"], g["chart_type"]) for g in graphs] == [
            ("hour", "bar-stack"),
            ("day", "bar"),
        ]
        for g in graphs:
            assert g["stat_types"] == ["change"]

    def test_the_only_history_graphs_plot_power_and_the_water(self):
        """Power and temperature do not reset, so a line graph is right for them."""
        graphs = [
            c for c in all_cards(yaml.safe_load(_build())["views"]) if c["type"] == "history-graph"
        ]
        assert graphs


class TestBillView:
    """A view of the month so far and the tariff behind it, to compare with a real bill."""

    def test_bill_view_has_the_month_figures(self):
        """Days elapsed and the cheap share are left out: the days left and the average rate
        say the same, and both sensors are disabled by default."""
        text = yaml.dump(_cards(_build(), "bill"))
        for key in (
            "import_cost_this_month",
            "export_earnings_this_month",
            "accrued_bill",
            "projected_bill",
            "days_remaining_in_period",
            "avg_import_rate_this_month",
        ):
            assert eid(key) in text, key

    def test_bill_sections_use_only_built_in_cards(self):
        types = {c["type"] for c in _section_cards(_build(), "bill", "This bill period")}
        assert types == {"heading", "markdown", "glance", "statistics-graph"}

    def test_disabled_by_default_figures_are_left_out(self):
        text = _build(registry=FakeRegistry())
        bill = yaml.dump(_cards(text, "bill"))
        for key in (
            "days_in_period",
            "avg_import_rate_this_month",
            "cheap_import_fraction_this_month",
        ):
            assert eid(key) not in bill

    def test_bill_prediction_moved_off_the_today_view(self):
        titles = [c.get("heading") for c in _cards(_build(), "today")]
        assert "Bill Prediction" not in titles

    def _tariff_markdown(self, config=None) -> str:
        """The table the view builds itself, which it does when the Tariff in use sensor is off."""
        shown = FULL_CONFIG if config is None else config
        registry = FakeRegistry(
            enable_all=True, devices=devices_of(shown, "myenergi"), absent={"tariff_in_use"}
        )
        cards = _section_cards(_build(config=config, registry=registry), "bill", "Tariff")
        return next(c for c in cards if c["type"] == "markdown")["content"]

    def test_the_tariff_reads_the_report_sensor_while_it_is_there(self):
        """The sensor builds its tables each cycle, so a stored copy follows a tariff change."""
        cards = _section_cards(_build(), "bill", "Tariff")
        markdown = [c["content"] for c in cards if c["type"] == "markdown"]
        assert markdown == [f"{{{{ state_attr('{eid('tariff_in_use')}', 'html') }}}}"]

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

    def test_unknown_resources_use_the_built_in_cards(self):
        """The custom card is used only when it is seen to be installed."""
        types = self._types(None)
        assert "custom:power-flow-card-plus" not in types
        assert not {t for t in types if t.startswith("custom:")}

    def test_the_power_flow_card_is_used_when_its_resource_is_registered(self):
        assert "custom:power-flow-card-plus" in self._types([_PFC])

    def test_apexcharts_card_draws_the_immersion_chart_only_when_installed(self):
        installed = self._types([_PFC, _APEX])
        assert "custom:apexcharts-card" in installed
        assert "custom:apexcharts-card" not in self._types([_PFC])

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

    def test_immersion_chart_is_a_built_in_card(self):
        text = self._shown([_PFC])
        assert "custom:apexcharts-card" not in text
        cards = _cards(text, "immersion")
        charts = [c["type"] for c in cards if c["type"].endswith("graph")]
        assert charts == ["history-graph", "statistics-graph", "statistics-graph"]
        graph = next(c for c in cards if c["type"] == "history-graph")
        rows = [r["entity"] for r in graph["entities"]]
        assert rows[0] == eid("immersion_water_temperature")
        assert rows[-1] == eid("immersion_power")
        assert all(c["type"] != "vertical-stack" for c in cards)

    def test_matching_ignores_case_and_path(self):
        types = self._types(["/local/Community/PowerFlowCard/POWER-FLOW-CARD-PLUS.js", _APEX])
        assert "custom:power-flow-card-plus" in types

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
    """Home energy and the four day and bill views are tabs. The devices and Settings are one tap
    away, on sub-views."""

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
                    if (
                        key in ("tap_action", "icon_tap_action")
                        and value.get("action") == "navigate"
                    ):
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

    def test_views_hold_their_detail_without_running_on(self):
        """Counted on what is shown, with every optional device present.

        Home energy holds the story and the way to the detail, and each sub-view a few
        sections, so no view runs on.
        """
        for view in seen_for(ev=True, switch=True, sensor=True)["views"]:
            assert len(view["sections"]) <= 10, view["path"]
            assert len(view_cards(view)) <= 60, view["path"]

    def test_energy_today_totals_are_not_repeated_in_full(self):
        """Home energy gives three chips for the day, and Today the figures behind them."""
        cards = all_cards(self._views())
        (energy,) = [c for c in cards if c.get("heading") == "Energy"]
        chips = [b["entity"] for b in energy["badges"] if b["type"] == "entity"]
        assert chips == [eid("solar_today"), eid("import_cost_today"), eid("self_sufficiency")]
        in_numbers = _cards(_build(), "today")
        start = next(i for i, c in enumerate(in_numbers) if c.get("heading") == "In numbers")
        figures = in_numbers[start + 1]
        assert figures["type"] == "glance"
        assert [r["name"] for r in figures["entities"]] == ["Solar", "Used", "Imported", "Exported"]
        assert {r["entity"] for r in figures["entities"]} & set(chips) == {eid("solar_today")}

    def test_the_battery_charge_is_a_bar_now_and_a_line_over_time_and_never_a_gauge(self):
        """Tonight sets the charge now beside the charge at sunrise, as two bars, and draws
        its last day and a half as a line."""
        cards = all_cards(self._views())
        assert not [c for c in cards if c["type"] == "gauge"]
        battery = [
            c["features"]
            for c in cards
            if c["type"] == "tile" and c["entity"] == eid("battery_soc")
        ]
        assert battery == [[{"type": "bar-gauge", "min": 0, "max": 100}]]
        lines = [
            c
            for c in cards
            if c["type"] == "history-graph" and eid("battery_soc") in yaml.dump(c["entities"])
        ]
        assert len(lines) == 1

    def test_the_heater_is_a_row_of_the_temperature_chart(self):
        """The built-in history graph steps between values, so it draws no false ramps."""
        charts = [c for c in _cards(_build(), "immersion") if c["type"] == "history-graph"]
        heater = [r for c in charts for r in c["entities"] if r["entity"] == eid("immersion_power")]
        assert heater
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


class TestSectionsLayout:
    """Every view is a sections view of headed sections of tiles."""

    _COLOURS = {"amber", "green", "blue", "orange", "teal", "indigo", "red", "purple", "deep-orange"}

    def _views(self, **kw):
        return yaml.safe_load(_build(**kw))["views"]

    def test_every_view_is_a_sections_view(self):
        for view in self._views():
            assert view["type"] == "sections", view["path"]
            assert view["max_columns"] in (3, 4), view["path"]
            assert "cards" not in view, view["path"]
            assert view["sections"], view["path"]

    def test_every_section_is_a_grid_that_starts_with_a_heading_or_the_tonight_line(self):
        lines = []
        for view in self._views():
            for section in view["sections"]:
                assert section["type"] == "grid", view["path"]
                first = section["cards"][0]
                if first["type"] == "markdown":
                    lines.append((view["path"], first["content"]))
                    assert section["cards"][1]["type"] == "heading", view["path"]
                    continue
                assert first["type"] == "heading", (view["path"], first)
                assert first["heading_style"] == "title"
                assert first["heading"]
                assert len(section["cards"]) > 1, (view["path"], first["heading"])
        assert lines == [("power-flow", tonight_line_template(eid("charge_plan")))]

    def test_no_heading_is_left_alone_at_the_end_of_a_section(self):
        """A heading may end a section only when it shows chips of its own."""
        for view in self._views():
            for section in view["sections"]:
                last = section["cards"][-1]
                assert last["type"] != "heading" or last.get("badges"), view["path"]

    def test_no_stacks_and_the_only_nested_grids_hold_device_tiles_on_home_energy_and_hot_water(self):
        for view in self._views():
            for card in view_cards(view):
                assert card["type"] not in {"vertical-stack", "horizontal-stack"}, card
                if "cards" not in card:
                    continue
                assert view["path"] in {"power-flow", "immersion"}, card
                assert card["type"] == "grid", card
                assert card["columns"] == 2, card
                assert {c["type"] for c in card["cards"]} == {"tile"}, card

    def test_no_card_title_repeats_a_heading(self):
        """Only the charts that share a row carry a small title, and it names its own chart."""
        titled = 0
        for view in self._views():
            headings = {c["heading"] for c in view_cards(view) if c["type"] == "heading"}
            for card in view_cards(view):
                if "title" not in card:
                    continue
                titled += 1
                assert card["type"] == "statistics-graph", card
                assert card["grid_options"]["columns"] == 12, card
                assert card["title"] not in headings, card
        assert titled == 4

    def test_each_view_has_unique_headings(self):
        for view in self._views():
            headings = [c["heading"] for c in view_cards(view) if c["type"] == "heading"]
            assert len(headings) == len(set(headings)), view["path"]

    def _tiles(self):
        """Every tile with the width it gets, in the 12 columns of a section.

        A tile in a grid card takes its share of the grid, which the tiles do not size
        themselves.
        """
        for view in self._views():
            for section in view["sections"]:
                for card in section["cards"]:
                    if card["type"] == "grid":
                        assert "grid_options" in card, card
                        for tile in card["cards"]:
                            assert "grid_options" not in tile, tile["name"]
                            yield tile, 12 // card["columns"]
                    elif card["type"] == "tile":
                        yield card, card["grid_options"]["columns"]

    def test_tile_names_are_short_enough_not_to_truncate(self):
        tiles = list(self._tiles())
        assert tiles
        for card, columns in tiles:
            assert len(card["name"]) <= 22, card["name"]
            if columns == 6:
                assert len(card["name"]) <= 15, card["name"]
            assert card["name"] == card["name"].strip() and card["name"], card

    def test_tiles_are_horizontal_and_sized_on_the_grid(self):
        for card, columns in self._tiles():
            assert "vertical" not in card
            assert columns in (6, "full"), card["name"]

    def test_tile_colours_come_from_the_palette(self):
        colours = {
            c["color"] for c in all_cards(self._views()) if c["type"] == "tile" and "color" in c
        }
        assert colours <= self._COLOURS
        assert {"amber", "green", "blue"} <= colours

    def test_graphs_and_charts_take_the_full_width(self):
        """The week pairs sit side by side in a two column section, half of it each. The rate
        strip is one row of colour, so it takes no fixed height."""
        graphs = [
            c
            for c in all_cards(self._views())
            if c["type"] in {"history-graph", "statistics-graph"}
            or c["type"].startswith("custom:power-flow")
        ]
        assert graphs
        strip = [{"entity": eid("current_rate_period"), "name": "Rate"}]
        for card in graphs:
            if "title" in card:
                assert card["grid_options"] == {"columns": 12, "rows": 3}, card
                continue
            assert card["grid_options"]["columns"] == "full", card["type"]
            if card.get("entities") == strip:
                assert card["grid_options"] == {"columns": "full"}
            elif card["type"].endswith("-graph"):
                assert card["grid_options"]["rows"] >= 3, card["type"]

    def test_markdown_cards_take_the_full_width(self):
        for card in all_cards(self._views()):
            if card["type"] == "markdown":
                assert card["grid_options"]["columns"] == "full"

    def test_settings_use_tile_features(self):
        """A number has − and + beside its name. A switch turns on or off when tapped."""
        tiles = [c for c in _cards(_build(), "settings") if c["type"] == "tile"]
        by_domain = {}
        for tile in tiles:
            by_domain.setdefault(tile["entity"].split(".")[0], []).append(tile)
        assert by_domain["number"] and by_domain["switch"]
        for tile in by_domain["number"]:
            assert tile["features"] == [{"type": "numeric-input", "style": "buttons"}]
            assert tile["features_position"] == "inline"
        toggle = {"action": "toggle"}
        for tile in by_domain["switch"]:
            assert "features" not in tile, tile["name"]
            assert tile["tap_action"] == tile["icon_tap_action"] == toggle
        assert {t["entity"] for t in by_domain["number"]} == {
            eid("charge_target_override"),
            eid("immersion_target_temp"),
            eid("immersion_min_temp"),
            eid("immersion_hysteresis"),
            eid("surplus_divert_soc_pct"),
            eid("surplus_divert_min_power_w"),
            eid("cheap_rate_floor_soc"),
            eid("skip_charge_soc_threshold_pct"),
            eid("forecast_conservatism"),
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
        assert types <= {
            "heading",
            "tile",
            "markdown",
            "entities",
            "glance",
            "distribution",
            "grid",
            "weather-forecast",
            "history-graph",
            "statistics-graph",
            "logbook",
        }
        assert len(parsed["views"]) == len(built["views"])

    def test_minimal_install_still_has_every_tab_with_headed_sections(self):
        views = yaml.safe_load(
            _build(config=MINIMAL_CONFIG, registry=FakeRegistry(), ev_brand=None)
        )["views"]
        tabs = [v for v in views if not v.get("subview")]
        assert [v["path"] for v in tabs] == ["power-flow", "today", "plan", "tomorrow", "bill"]
        for view in views:
            for section in view["sections"]:
                first = section["cards"][0]
                assert first["type"] == "heading" or first["content"] == tonight_line_template(
                    eid("charge_plan")
                )


class TestResponsiveLayout:
    """Sections reflow to the screen: wide sections on a laptop, one column on a phone."""

    def _views(self, **kw):
        return yaml.safe_load(_build(**kw))["views"]

    def test_every_view_places_its_sections_densely_in_at_most_three_columns(self):
        """A short section moves up into the gap beside a tall one, so no column ends early."""
        for view in self._views():
            assert view["max_columns"] == 3, view["path"]
            assert view["dense_section_placement"] is True, view["path"]

    def test_banners_and_view_wide_charts_span_every_column(self):
        wide = {
            (view["path"], section["cards"][0]["heading"])
            for view in self._views()
            for section in view["sections"]
            if section.get("column_span") == 3
        }
        assert wide == {
            ("power-flow", "Dry run is on"),
            ("power-flow", "Something else is setting your charge target"),
            ("power-flow", "Finish setting up"),
            ("power-flow", "Needs your attention"),
            ("power-flow", "Start the alternative heating"),
            ("power-flow", "The immersion stopped at its longest run"),
        }

    def test_settings_is_five_sections_of_one_column_so_a_laptop_fills_every_column(self):
        settings = next(v for v in self._views() if v["path"] == "settings")
        assert [s["cards"][0]["heading"] for s in settings["sections"]] == [
            "Tonight's charge",
            "Charge planning",
            "Hot water",
            "System",
            "Recent changes",
        ]
        assert not [s for s in settings["sections"] if "column_span" in s]
        for section in settings["sections"]:
            headings = [c for c in section["cards"] if c["type"] == "heading"]
            assert len(headings) == 1, headings

    def test_the_numbers_take_the_section_width_and_the_switches_half(self):
        settings = next(v for v in self._views() if v["path"] == "settings")
        columns = {
            c["name"]: c["grid_options"]["columns"]
            for c in view_cards(settings)
            if c["type"] == "tile"
        }
        assert columns == {
            "Fixed target": 6,
            "Skip tonight": 6,
            "Charge to": "full",
            "Cheap rate floor": "full",
            "Skip charge above": "full",
            "Forecast caution": "full",
            "Re-plan overnight": "full",
            "Use spare solar": 6,
            "Heat now": 6,
            "Scheduled heat": 6,
            "Heat to": "full",
            "Never below": "full",
            "Restart drop": "full",
            "Min battery": "full",
            "Min spare solar": "full",
            "Dry run": 6,
            "Verbose logging": 6,
        }

    def test_every_toggle_tile_says_it_takes_the_full_width(self):
        """Home Assistant gives a tile with an inline toggle at least 12 columns."""
        toggles = [
            c
            for c in all_cards(self._views())
            if c["type"] == "tile" and c.get("features_position") == "inline"
        ]
        assert toggles
        assert {c["grid_options"]["columns"] for c in toggles} == {"full"}

    def test_no_stepper_is_left_alone_at_half_width(self):
        """Every number takes the section width, with − and + beside its name."""
        settings = next(v for v in self._views() if v["path"] == "settings")
        widths = {
            c["name"]: c["grid_options"]["columns"]
            for c in view_cards(settings)
            if c["type"] == "tile" and c.get("features", [{}])[0].get("type") == "numeric-input"
        }
        assert len(widths) == 9
        assert set(widths.values()) == {"full"}


class TestRecentChanges:
    """The Settings view lists what changed a setting in the last day."""

    def _logbooks(self, **kw) -> list[dict]:
        return [c for c in _cards(_build(**kw), "settings") if c["type"] == "logbook"]

    def test_it_is_the_last_section_of_settings(self):
        settings = next(v for v in yaml.safe_load(_build())["views"] if v["path"] == "settings")
        section = settings["sections"][-1]
        assert section["cards"][0]["heading"] == "Recent changes"
        assert {c["type"] for c in section["cards"][1:]} == {"logbook"}

    def test_it_covers_a_day_of_the_settings_on_the_view(self):
        full = self._logbooks()[-1]
        assert full["hours_to_show"] == 24
        listed = set(full["target"]["entity_id"])
        settings_tiles = {c["entity"] for c in _cards(_build(), "settings") if c["type"] == "tile"}
        assert listed == settings_tiles

    def test_it_names_the_heater_only_for_the_devices_present(self):
        """One list per combination of the switch and thermostat, each shown by a condition."""
        for view in seen_for()["views"]:
            if view["path"] == "settings":
                (shown,) = [c for c in view_cards(view) if c["type"] == "logbook"]
                assert eid("auto_immersion") not in shown["target"]["entity_id"]
                assert eid("dry_run") in shown["target"]["entity_id"]
        for view in seen_for(switch=True, sensor=True)["views"]:
            if view["path"] == "settings":
                (shown,) = [c for c in view_cards(view) if c["type"] == "logbook"]
                assert eid("auto_immersion") in shown["target"]["entity_id"]
                assert eid("immersion_target_temp") in shown["target"]["entity_id"]
