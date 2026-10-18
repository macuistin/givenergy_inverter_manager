"""
The story layout: Home energy's heading, Tonight line and sources, and what each view adds.

Home energy is the first of five tabs. Its Energy heading carries the Settings button and the
day's chips over the power flow. Under it, one line says whether tonight charges and one bar says
where the day's energy came from. The hot water and the EV charger each have a box of tiles. The
sentences are markdown templates, so these tests render them with Jinja and the template
functions Home Assistant provides (tests/test_dashboard.py holds the stand-ins).
"""

from __future__ import annotations

import itertools
from datetime import time

import pytest
import yaml

from custom_components.givenergy_inverter_manager.const import CONF_FORECAST_ENTITY
from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
from custom_components.givenergy_inverter_manager.core.charge_window import ChargeWindow
from custom_components.givenergy_inverter_manager.core.devices import Device
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.core.reporting import (
    PLAN_CHARGE_WORDS,
    PLAN_SKIP_WORDS,
    build_charge_plan_state,
)
from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision
from custom_components.givenergy_inverter_manager.dashboard.cards import TABLE_CSS, TOTAL_CSS
from custom_components.givenergy_inverter_manager.dashboard.templates import (
    ChargerNow,
    DayTotals,
    WaterNow,
    ev_story_template,
    saved_template,
    today_story_template,
    tomorrow_story_template,
    tonight_line_template,
    water_story_template,
)
from tests.dashboard_support import (
    ADMIN_ID,
    FULL_CONFIG,
    MINIMAL_CONFIG,
    FakeRegistry,
    dashboard_dict,
    default_entity_ids,
    devices_of,
    view_cards,
)
from tests.dashboard_visibility import generated_for, install, seen, states_with
from tests.test_dashboard import _render

IDS = default_entity_ids()
FORECAST = FULL_CONFIG[CONF_FORECAST_ENTITY]
CARD_MOD = ["/hacsfiles/lovelace-card-mod/card-mod.js"]
APEX = ["/hacsfiles/apexcharts-card/apexcharts-card.js"]
COMBINATIONS = list(itertools.product([False, True], repeat=3))

REPAIRS = IDS["active_repairs"]
OUTLOOK = IDS["tomorrow_outlook"]
SESSION_COST = IDS["ev_session_cost"]


def _label(combination: tuple[bool, bool, bool]) -> str:
    ev, switch, sensor = combination
    parts = [name for name, on in (("ev", ev), ("switch", switch), ("sensor", sensor)) if on]
    return "+".join(parts) or "none"


def _view(dashboard: dict, path: str) -> dict:
    return next(v for v in dashboard["views"] if v["path"] == path)


def _paths(dashboard: dict) -> set[str]:
    return {v["path"] for v in dashboard["views"]}


def _heading(dashboard: dict, text: str) -> dict:
    (card,) = [c for c in view_cards(_view(dashboard, "power-flow")) if c.get("heading") == text]
    return card


def _section(dashboard: dict, path: str, heading: str) -> dict | None:
    """The section of the view at path that holds this heading, which may follow a line."""
    for section in _view(dashboard, path)["sections"]:
        if heading in [c.get("heading") for c in section["cards"]]:
            return section
    return None


def _without(*keys: str) -> FakeRegistry:
    """A registry with every sensor enabled except these, which are not registered."""
    return FakeRegistry(enable_all=True, absent=set(keys))


def _every_node(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _every_node(value)
    elif isinstance(node, list):
        for item in node:
            yield from _every_node(item)


# ── Home energy's heading ────────────────────────────────────────────────────


class TestTheEnergyHeading:
    def test_it_has_no_icon_and_a_short_title_so_it_fits_one_line_on_a_phone(self):
        heading = _heading(dashboard_dict(), "Energy")
        assert heading["heading_style"] == "title"
        assert "icon" not in heading
        assert "tap_action" not in heading

    def test_the_settings_button_comes_first_then_solar_the_cost_and_self_sufficiency(self):
        """The button leads so the chips after it are the ones a narrow screen cuts."""
        badges = _heading(dashboard_dict(), "Energy")["badges"]
        button, *chips = badges
        assert button["type"] == "button"
        assert button["text"] == "Settings"
        assert "icon" not in button
        assert button["tap_action"] == {"action": "navigate", "navigation_path": "settings"}
        assert [b["entity"] for b in chips] == [
            IDS["solar_today"],
            IDS["import_cost_today"],
            IDS["self_sufficiency"],
        ]
        assert {b["type"] for b in chips} == {"entity"}
        assert all(b["show_state"] and b["show_icon"] for b in chips)

    @pytest.mark.parametrize("kw", [{"is_admin": False}, {"admin_ids": ()}], ids=["viewer", "none"])
    def test_without_an_administrator_to_show_it_to_there_is_no_button(self, kw):
        badges = _heading(dashboard_dict(**kw), "Energy")["badges"]
        assert [b["entity"] for b in badges] == [
            IDS["solar_today"],
            IDS["import_cost_today"],
            IDS["self_sufficiency"],
        ]

    def test_the_chips_are_left_out_with_their_sensors_and_the_button_stays(self):
        registry = FakeRegistry(
            enable_all=True, absent={"solar_today", "import_cost_today", "self_sufficiency"}
        )
        dashboard = dashboard_dict(registry=registry)
        assert [b["type"] for b in _heading(dashboard, "Energy")["badges"]] == ["button"]
        assert None not in _section(dashboard, "power-flow", "Energy")["cards"]

    def test_the_heading_is_just_a_title_when_there_is_nothing_to_put_in_it(self):
        registry = FakeRegistry(
            enable_all=True, absent={"solar_today", "import_cost_today", "self_sufficiency"}
        )
        dashboard = dashboard_dict(registry=registry, admin_ids=())
        assert "badges" not in _heading(dashboard, "Energy")

    def test_the_power_flow_cards_follow_the_heading_in_its_section(self):
        section = _section(dashboard_dict(), "power-flow", "Energy")
        assert section["column_span"] == 2
        assert section["cards"][0]["heading"] == "Energy"
        assert {c["type"] for c in section["cards"][1:]} == {"custom:power-flow-card-plus"}


# ── Home energy's Tonight line ───────────────────────────────────────────────

_PLAN = "sensor.plan"


def _plan_data(*, skip: bool, window: ChargeWindow | None = None) -> CoordinatorData:
    """The data the Tonight's Charge Plan sensor reads, for a skipped or a charging night."""
    data = CoordinatorData()
    data.currency_symbol = "€"
    data.battery_stats = BatteryStats()
    data.published_charge_window = window
    data.charge_decision = ChargeDecision(
        target_soc=80,
        skip_charge=skip,
        reason="Reason",
        forecast_kwh=12.0,
        current_soc=40.0,
        battery_capacity=10.0,
        car_plugged_in=False,
        cost_to_charge=1.5,
    )
    return data


def _tonight(plan_state: str) -> str:
    """The Tonight line, rendered for what the plan sensor says."""
    template = tonight_line_template(_PLAN)
    return _render(template, lambda e: {_PLAN: plan_state}.get(e, "unknown")).strip()


class TestTheTonightLine:
    def test_a_skipped_charge_says_it_will_not_charge(self):
        state = build_charge_plan_state(_plan_data(skip=True))
        assert state.startswith(PLAN_SKIP_WORDS)
        text = _tonight(state)
        assert "**Tonight:** won't charge" in text
        assert "mdi:battery-check" in text
        assert "will charge" not in text

    def test_a_charge_says_the_percentage_it_charges_to(self):
        state = build_charge_plan_state(_plan_data(skip=False))
        assert state.startswith(PLAN_CHARGE_WORDS)
        text = _tonight(state)
        assert text.endswith("**Tonight:** will charge to 80%")
        assert "mdi:battery-charging-high" in text
        assert "won't" not in text

    def test_a_charge_with_a_window_still_reads_the_percentage_not_the_time(self):
        window = ChargeWindow(
            time(2, 0), time(4, 0), extended=False, expected_kwh=None, finish_time=None
        )
        state = build_charge_plan_state(_plan_data(skip=False, window=window))
        assert "02:00 to 04:00" in state
        assert _tonight(state).endswith("will charge to 80%")

    def test_a_plan_the_engine_has_not_made_yet_says_so(self):
        data = _plan_data(skip=False)
        data.charge_decision = None
        state = build_charge_plan_state(data)
        assert _tonight(state).endswith("**Tonight:** no plan yet")
        assert "mdi:battery-clock" in _tonight(state)

    @pytest.mark.parametrize("state", ["unknown", "unavailable", ""])
    def test_an_unknown_state_says_no_plan_yet(self, state):
        assert _tonight(state).endswith("**Tonight:** no plan yet")

    def test_it_reads_the_charge_plan_sensor_on_home_energy(self):
        section = _section(dashboard_dict(), "power-flow", "Where it came from")
        line = section["cards"][0]
        assert line["type"] == "markdown"
        assert line["content"] == tonight_line_template(IDS["charge_plan"])
        assert f"states('{IDS['charge_plan']}')" in line["content"]
        assert line["grid_options"] == {"columns": "full"}

    def test_it_reads_the_plan_the_inverter_is_written_from_not_the_held_target(self):
        """The charge target sensor can still show last night's charge while tonight is skipped."""
        content = tonight_line_template(IDS["charge_plan"])
        assert IDS["overnight_charge_target"] not in content
        assert "state_attr" not in content

    def test_without_the_plan_sensor_the_line_is_left_out_and_the_bar_stays(self):
        dashboard = dashboard_dict(registry=_without("charge_plan"))
        section = _section(dashboard, "power-flow", "Where it came from")
        assert [c["type"] for c in section["cards"]] == ["heading", "distribution"]
        assert IDS["charge_plan"] not in yaml.safe_dump(_view(dashboard, "power-flow"))


# ── Home energy's Where it came from bar ─────────────────────────────────────


class TestTheSourcesBar:
    @staticmethod
    def _bar(dashboard: dict, path: str) -> dict:
        (bar,) = [
            c
            for c in view_cards(_view(dashboard, path))
            if c["type"] == "distribution" and IDS["solar_today"] in str(c["entities"])
        ]
        return bar

    def test_it_splits_the_day_into_solar_battery_and_grid(self):
        bar = self._bar(dashboard_dict(), "power-flow")
        assert [(r["name"], r["entity"]) for r in bar["entities"]] == [
            ("Solar", IDS["solar_today"]),
            ("Battery", IDS["battery_discharge_kwh_today"]),
            ("Grid", IDS["import_today"]),
        ]
        assert bar["grid_options"] == {"columns": "full"}

    @pytest.mark.parametrize("series_colours", [False, True], ids=["plain", "coloured"])
    def test_it_is_the_same_bar_as_the_today_view_shows(self, series_colours):
        dashboard = dashboard_dict(series_colours=series_colours)
        assert self._bar(dashboard, "power-flow") == self._bar(dashboard, "today")

    def test_it_sits_under_its_own_heading(self):
        section = _section(dashboard_dict(), "power-flow", "Where it came from")
        assert section["column_span"] == 2
        assert [c["type"] for c in section["cards"]] == ["markdown", "heading", "distribution"]

    def test_it_is_left_out_with_its_heading_when_no_source_is_there(self):
        registry = _without("solar_today", "battery_discharge_kwh_today", "import_today")
        dashboard = dashboard_dict(registry=registry)
        assert "Where it came from" not in [
            c.get("heading") for c in view_cards(_view(dashboard, "power-flow"))
        ]
        assert not [c for c in view_cards(_view(dashboard, "power-flow")) if c["type"] == "distribution"]


class TestTheOtherSentences:
    def test_today_gives_the_share_of_the_forecast_the_use_and_the_cost(self):
        day = DayTotals("s.solar", "s.forecast", "s.house", "s.self", "s.cost", "s.earned")
        values = {
            "s.solar": "12.34",
            "s.forecast": "16",
            "s.house": "9.06",
            "s.self": "71.6",
            "s.cost": "1.2",
            "s.earned": "0.456",
        }
        text = _render(today_story_template(day, "£"), lambda e: values[e])
        assert text == (
            "**Solar made 12.3 kWh**, 77% of the forecast. The house used 9.1 kWh, 72% of it "
            "without the grid. You paid £1.20 and earned £0.46 for exports."
        )

    def test_today_leaves_out_the_clauses_of_sensors_it_has_not(self):
        day = DayTotals("s.solar", None, None, None, "s.cost", None)
        text = _render(today_story_template(day, "€"), lambda e: {"s.solar": "3", "s.cost": "0.5"}[e])
        assert text == "**Solar made 3.0 kWh**. You paid €0.50."

    def test_tomorrow_gives_the_typical_and_the_low_estimate_and_the_dawn(self):
        attrs = {("s.fc", "estimate10"): 5.6, ("s.target", "plan"): "charge"}
        values = {"s.fc": "14.4", "s.target": "60", "s.dawn": "57.4"}
        text = _render(tomorrow_story_template("s.fc", "s.target", "s.dawn"), values.get, attrs)
        assert text == (
            "**About 14 kWh of solar expected**, at least 6 kWh on a dull day. Tonight charges "
            "to 60%, so the battery should start the day at about 57%."
        )

    def test_tomorrow_reads_the_configured_forecast(self):
        tomorrow = _section(dashboard_dict(), "tomorrow", "Tomorrow")
        story = next(c for c in tomorrow["cards"] if c["type"] == "markdown")
        assert f"states('{FORECAST}')" in story["content"]
        assert f"state_attr('{FORECAST}', 'estimate10')" in story["content"]
        assert IDS["estimated_soc_at_sunrise_with_charge"] in story["content"]

    def test_the_water_sentence_does_not_repeat_that_it_is_at_its_target(self):
        water = WaterNow("s.water", "s.target", "s.heater", "s.reason")
        values = {"s.water": "55.04", "s.target": "55", "s.heater": "0", "s.reason": "x"}
        at = _render(
            water_story_template(water),
            values.get,
            {("s.reason", "full_text"): "Water already at 55 °C."},
        )
        assert at == "**Water at 55.0 °C, at its target.** Heater off. "
        values |= {"s.water": "41.2", "s.heater": "3000"}
        heating = _render(
            water_story_template(water), values.get, {("s.reason", "full_text"): "Spare solar."}
        )
        assert heating == "**Water at 41.2 °C.** Heating now. Spare solar."

    def test_the_ev_sentence_says_from_what_it_charges_or_why_not(self):
        ev = ChargerNow("s.power", "s.state", "s.source", "s.surplus", None)
        values = {"s.power": "3600", "s.state": "Charging", "s.source": "Solar", "s.surplus": "Yes"}
        text = _render(ev_story_template(ev), values.get)
        assert text == "**Charging at 3.6 kW** from solar. Spare solar: yes."
        values |= {"s.power": "0", "s.state": "Waiting"}
        assert _render(ev_story_template(ev), values.get).startswith(
            "**Not charging.** The charger is waiting."
        )

    def test_the_bill_saving_is_what_solar_and_the_battery_took_off(self):
        text = _render(saved_template("s.paid", "s.without", "€"), {"s.paid": "40", "s.without": "65.5"}.get)
        assert text == (
            "### Saved €25.50 so far\nSolar and the battery have taken €25.50 off this bill. "
            "Without them it would be €65.50."
        )


# ── Optional cards: card-mod, colours, apexcharts and the weather ────────────


def _styled(dashboard: dict) -> list[dict]:
    return [card for view in dashboard["views"] for card in view_cards(view) if "card_mod" in card]


class TestCardMod:
    @pytest.mark.parametrize("resources", [None, [], APEX], ids=["unknown", "none", "apex"])
    def test_no_card_is_styled_without_the_card_mod_resource(self, resources):
        assert _styled(dashboard_dict(resources=resources)) == []

    def test_the_tables_are_styled_with_card_mod(self):
        bill = _view(dashboard_dict(resources=CARD_MOD), "bill")
        styles = {
            section["cards"][0]["heading"]: card["card_mod"]["style"]
            for section in bill["sections"]
            for card in section["cards"]
            if "card_mod" in card
        }
        inner = {".": ""}
        assert styles == {
            "Tariff": {"ha-markdown $": TABLE_CSS, **inner},
            "This bill, line by line": {"ha-markdown $": TABLE_CSS + TOTAL_CSS, **inner},
            "Each day": {"ha-markdown $": TABLE_CSS, **inner},
            "Last bill": {"ha-markdown $": TABLE_CSS + TOTAL_CSS, **inner},
        }

    def test_with_card_mod_only_tables_and_the_titled_charts_change(self):
        """Without the resource the same cards are there, unstyled."""
        plain = dashboard_dict(resources=[])
        styled = dashboard_dict(resources=CARD_MOD)
        assert {c["type"] for c in _styled(styled)} == {"markdown", "statistics-graph"}
        for card in _styled(styled):
            if card["type"] == "statistics-graph":
                assert card["title"] in ("Heated", "Charged", "Cost")
        for view, bare in zip(styled["views"], plain["views"], strict=True):
            stripped = [{k: v for k, v in c.items() if k != "card_mod"} for c in view_cards(view)]
            assert stripped == view_cards(bare), view["path"]


def _series_rows(dashboard: dict) -> list[dict]:
    charts = ("statistics-graph", "history-graph", "distribution")
    return [
        row
        for view in dashboard["views"]
        for card in view_cards(view)
        if card["type"] in charts
        for row in card["entities"]
    ]


class TestSeriesColours:
    def test_no_series_carries_a_colour_before_the_release_that_draws_it(self):
        assert [row for row in _series_rows(dashboard_dict()) if "color" in row] == []

    def test_the_series_take_the_power_flows_colours_from_that_release(self):
        rows = _series_rows(dashboard_dict(series_colours=True))
        colours = {(row["entity"], row["name"]): row.get("color") for row in rows}
        assert colours[(IDS["solar_today"], "Solar")] == "#ff9800"
        assert colours[(IDS["battery_discharge_kwh_today"], "Battery")] == "#4db6ac"
        assert colours[(IDS["import_today"], "Grid")] == "#9575cd"
        assert colours[(IDS["house_cost_today"], "House")] == "#29b6f6"
        assert colours[(IDS["battery_soc"], "Battery")] == "#4db6ac"

    def test_the_week_of_energy_takes_its_devices_colour(self):
        """Hot water is orange and the EV teal, as in the cost split, not the solar amber."""
        rows = _series_rows(dashboard_dict(series_colours=True))
        colours = {(row["entity"], row["name"]): row.get("color") for row in rows}
        assert colours[(IDS["immersion_today"], "Heated")] == "#ff7043"
        assert colours[(IDS["zappi_today"], "Charged")] == "#4db6ac"

    def test_only_the_colour_differs_between_the_releases(self):
        plain = yaml.safe_dump(dashboard_dict())
        coloured = dashboard_dict(series_colours=True)
        for row in _series_rows(coloured):
            row.pop("color", None)
        assert yaml.safe_dump(coloured) == plain


_HALF_HOURLY = {FORECAST: {"detailedForecast": [{"period_start": "2026-10-17T07:00:00+01:00"}]}}


def _tomorrow_curves(dashboard: dict) -> list[dict]:
    if "tomorrow" not in _paths(dashboard):
        return []
    return [c for c in view_cards(_view(dashboard, "tomorrow")) if c["type"].startswith("custom:")]


class TestTomorrowsCurve:
    def test_it_is_drawn_with_apexcharts_and_the_half_hourly_forecast(self):
        dashboard = dashboard_dict(resources=APEX, states=(FORECAST,), attributes=_HALF_HOURLY)
        (curve,) = _tomorrow_curves(dashboard)
        assert curve["type"] == "custom:apexcharts-card"
        assert {s["entity"] for s in curve["series"]} == {FORECAST}
        assert [s["name"] for s in curve["series"]] == ["Forecast", "Dull day"]
        assert "detailedForecast" in curve["series"][0]["data_generator"]
        assert curve["span"] == {"start": "day", "offset": "+1d"}

    @pytest.mark.parametrize(
        ("resources", "attributes"),
        [
            ([], _HALF_HOURLY),
            (None, _HALF_HOURLY),
            (APEX, {FORECAST: {"estimate10": 3.2}}),
            (APEX, None),
        ],
        ids=["no-apex", "unknown-resources", "no-half-hours", "no-forecast-state"],
    )
    def test_it_is_left_out_without_both(self, resources, attributes):
        states = (FORECAST,) if attributes else ()
        dashboard = dashboard_dict(resources=resources, states=states, attributes=attributes)
        assert _tomorrow_curves(dashboard) == []
        headings = [c.get("heading") for c in view_cards(_view(dashboard, "tomorrow"))]
        assert "Solar through the day" not in headings

    def test_without_a_forecast_tomorrow_keeps_only_what_the_day_should_cost(self):
        config = {k: v for k, v in FULL_CONFIG.items() if k != CONF_FORECAST_ENTITY}
        dashboard = dashboard_dict(config, resources=APEX, states=(FORECAST,), attributes=_HALF_HOURLY)
        assert _tomorrow_curves(dashboard) == []
        cards = view_cards(_view(dashboard, "tomorrow"))
        assert [c["heading"] for c in cards if c["type"] == "heading"] == ["What it should cost"]

    def test_there_is_no_tomorrow_view_without_a_forecast_or_the_outlook(self):
        config = {k: v for k, v in FULL_CONFIG.items() if k != CONF_FORECAST_ENTITY}
        registry = FakeRegistry(enable_all=True, absent={"tomorrow_outlook"})
        assert "tomorrow" not in _paths(dashboard_dict(config, registry, resources=APEX))


def _weather_cards(dashboard: dict) -> list[dict]:
    return [
        card
        for view in dashboard["views"]
        for card in view_cards(view)
        if card["type"] == "weather-forecast"
    ]


class TestTheWeather:
    @pytest.mark.parametrize(
        ("states", "chosen"),
        [
            (("weather.attic", "weather.forecast_home", "weather.home"), "weather.forecast_home"),
            (("weather.zebra", "weather.home"), "weather.home"),
            (("weather.zebra", "weather.attic"), "weather.attic"),
        ],
        ids=["met-no-first", "met-no-older-name", "first-by-name"],
    )
    def test_the_weather_entity_is_met_nos_default_or_the_first_by_name(self, states, chosen):
        cards = _weather_cards(dashboard_dict(states=states))
        assert [c["entity"] for c in cards] == [chosen, chosen]

    def test_the_weather_shows_on_tonight_and_tomorrow(self):
        dashboard = dashboard_dict(states=("weather.forecast_home",))
        assert _section(dashboard, "plan", "Next few days") is not None
        tomorrow = view_cards(_view(dashboard, "tomorrow"))
        assert "Weather" in [c.get("heading") for c in tomorrow]

    def test_without_a_weather_entity_there_is_no_weather_card_or_heading(self):
        dashboard = dashboard_dict(states=("sensor.not_weather",))
        assert _weather_cards(dashboard) == []
        assert _section(dashboard, "plan", "Next few days") is None
        assert "Weather" not in [c.get("heading") for c in view_cards(_view(dashboard, "tomorrow"))]


# ── Sections that wait for a sensor another change adds ──────────────────────


class TestTheRepairsBanner:
    def test_it_is_left_out_without_the_sensor(self):
        dashboard = dashboard_dict(registry=_without("active_repairs"))
        assert _section(dashboard, "power-flow", "Needs your attention") is None
        assert REPAIRS not in yaml.safe_dump(dashboard)

    def test_it_shows_the_repairs_to_administrators_while_there_is_one(self):
        dashboard = dashboard_dict(registry=FakeRegistry(enable_all=True))
        section = _section(dashboard, "power-flow", "Needs your attention")
        assert section["column_span"] == 3
        assert section["visibility"] == [
            {"condition": "numeric_state", "entity": REPAIRS, "above": 0},
            {"condition": "user", "users": [ADMIN_ID]},
        ]
        assert [c["content"] for c in section["cards"][1:]] == [
            f"{{{{ state_attr('{REPAIRS}', 'summary') }}}}"
        ]

    def test_it_sits_after_the_other_banners_and_before_the_power_flow(self):
        dashboard = dashboard_dict(registry=FakeRegistry(enable_all=True))
        headings = [
            next(c["heading"] for c in s["cards"] if c["type"] == "heading")
            for s in _view(dashboard, "power-flow")["sections"]
        ]
        assert headings[2:6] == [
            "Finish setting up",
            "Needs your attention",
            "Start the alternative heating",
            "Energy",
        ]

    @pytest.mark.parametrize(("count", "shown"), [("0", False), ("2", True), ("unknown", False)])
    def test_it_hides_while_there_is_no_repair(self, count, shown):
        dashboard = dashboard_dict(registry=FakeRegistry(enable_all=True))
        states = states_with(frozenset(Device), {REPAIRS: count})
        assert (_section(seen(dashboard, states), "power-flow", "Needs your attention") is not None) == shown

    def test_it_is_left_out_for_a_viewer_who_is_not_an_administrator(self):
        dashboard = dashboard_dict(registry=FakeRegistry(enable_all=True), is_admin=False)
        assert _section(dashboard, "power-flow", "Needs your attention") is None


class TestTheTomorrowOutlook:
    def test_it_is_left_out_without_the_sensor(self):
        dashboard = dashboard_dict(registry=_without("tomorrow_outlook"))
        assert _section(dashboard, "tomorrow", "What it should cost") is None
        assert OUTLOOK not in yaml.safe_dump(dashboard)

    def test_it_prints_the_outlook_table_with_a_total(self):
        dashboard = dashboard_dict(registry=FakeRegistry(enable_all=True), resources=CARD_MOD)
        section = _section(dashboard, "tomorrow", "What it should cost")
        (table,) = [c for c in section["cards"] if c["type"] == "markdown"]
        assert table["content"] == f"{{{{ state_attr('{OUTLOOK}', 'table') }}}}"
        assert table["card_mod"]["style"]["ha-markdown $"] == TABLE_CSS + TOTAL_CSS


class TestTheRecentCharges:
    def _recent(self, dashboard: dict) -> dict | None:
        return _section(dashboard, "ev-charger", "Recent charges")

    def test_they_are_left_out_without_the_sensor(self):
        dashboard = dashboard_dict(registry=_without("ev_session_cost"))
        assert self._recent(dashboard) is None
        assert SESSION_COST not in yaml.safe_dump(dashboard)

    def test_they_print_the_session_table_while_a_charger_is_there(self):
        section = self._recent(dashboard_dict(registry=FakeRegistry(enable_all=True)))
        assert section["visibility"] == [
            {"condition": "state", "entity": IDS["ev_charger_state"], "state_not": "unavailable"}
        ]
        assert section["cards"][1]["content"] == (
            f"{{{{ state_attr('{SESSION_COST}', 'recent_table') }}}}"
        )

    def test_the_charge_cost_joins_the_figures_with_the_sensor(self):
        section = _section(dashboard_dict(registry=FakeRegistry(enable_all=True)), "ev-charger", "EV charger")
        (figures,) = [c for c in section["cards"] if c["type"] == "glance"]
        assert [r["name"] for r in figures["entities"]] == [
            "This charge",
            "Its cost",
            "Today",
            "Cost today",
        ]
        assert figures["entities"][1]["entity"] == SESSION_COST

    def test_they_wait_for_a_charger_without_one(self):
        """The file names the id the sensor will get, so the table arrives with the charger."""
        config, _ = install(ev=False)
        registry = FakeRegistry(enable_all=True, devices=devices_of(config, None))
        dashboard = dashboard_dict(config, registry, ev_brand=None)
        assert SESSION_COST not in {e.entity_id for e in registry._entries.values()}
        section = self._recent(dashboard)
        assert section["visibility"] == [
            {"condition": "state", "entity": IDS["ev_charger_state"], "state_not": "unavailable"}
        ]
        assert SESSION_COST in section["cards"][1]["content"]
        assert self._recent(seen(dashboard, states_with(devices_of(config, None)))) is None
        arrived = seen(dashboard, states_with(devices_of(config, "myenergi")))
        assert self._recent(arrived) is not None


# ── The tabs and the way to the sub-views ────────────────────────────────────


def _links(dashboard: dict) -> dict[str, set[str]]:
    """{view path: the views its cards and chips open}."""
    out: dict[str, set[str]] = {}
    for view in dashboard["views"]:
        targets = set()
        for node in _every_node(view):
            for key in ("tap_action", "icon_tap_action"):
                action = node.get(key)
                if isinstance(action, dict) and action.get("action") == "navigate":
                    targets.add(action["navigation_path"])
        out[view["path"]] = targets
    return out


class TestTheTabsAndTheWayToTheSubViews:
    def test_the_four_day_and_bill_views_are_tabs_and_nothing_links_to_them(self):
        """They sit in the tab bar, so no shortcut leads to them."""
        dashboard = dashboard_dict()
        tabs = {"today", "plan", "tomorrow", "bill"}
        assert tabs <= _paths(dashboard)
        assert not tabs & set().union(*_links(dashboard).values())

    def test_home_energy_opens_the_devices_and_settings_and_a_sub_view_opens_no_other(self):
        links = _links(dashboard_dict())
        assert links["power-flow"] == {"immersion", "ev-charger", "settings"}
        for path in ("immersion", "ev-charger", "settings"):
            assert links[path] == set(), path

    def test_a_sub_view_that_is_left_out_is_not_linked(self):
        config = {k: v for k, v in MINIMAL_CONFIG.items() if k != CONF_FORECAST_ENTITY}
        registry = FakeRegistry(absent={"tomorrow_outlook"})
        dashboard = dashboard_dict(config, registry, is_admin=False, ev_brand=None)
        assert "settings" not in _paths(dashboard)
        targets = set().union(*_links(dashboard).values())
        assert targets <= _paths(dashboard)
        assert "settings" not in targets


# ── The rules every generated dashboard keeps ────────────────────────────────


_FLOOR_CONDITIONS = {"state", "numeric_state", "user", "or"}


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
@pytest.mark.parametrize("resources", [None, CARD_MOD + APEX], ids=["core", "hacs"])
def test_every_visibility_condition_works_on_the_home_assistant_floor(combination, resources):
    """The wider set of condition types needs a later release than the floor."""
    ev, switch, sensor = combination
    config, brand = install(ev=ev, switch=switch, sensor=sensor)
    registry = FakeRegistry(enable_all=True, devices=devices_of(config, brand))
    dashboard = dashboard_dict(config, registry, ev_brand=brand, resources=resources)
    kinds = {
        node["condition"]
        for node in _every_node(dashboard)
        if isinstance(node.get("condition"), str)
    }
    assert kinds
    assert kinds <= _FLOOR_CONDITIONS


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
@pytest.mark.parametrize("schedule", ["on", "off"])
def test_no_heading_is_shown_with_nothing_under_it(combination, schedule):
    """A heading shows chips of its own, or the card that follows it is not a heading."""
    ev, switch, sensor = combination
    config, brand = install(ev=ev, switch=switch, sensor=sensor)
    states = states_with(devices_of(config, brand))
    if IDS["immersion_schedule"] in states:
        states[IDS["immersion_schedule"]] = schedule
    shown = seen(generated_for(ev=ev, switch=switch, sensor=sensor), states)
    for view in shown["views"]:
        for section in view["sections"]:
            cards = section["cards"]
            for index, card in enumerate(cards):
                if card["type"] != "heading" or card.get("badges"):
                    continue
                following = cards[index + 1] if index + 1 < len(cards) else None
                assert following is not None, (view["path"], card["heading"])
                assert following["type"] != "heading", (view["path"], card["heading"])


@pytest.mark.parametrize(
    "registry",
    [
        FakeRegistry(),
        FakeRegistry(enable_all=True),
        FakeRegistry(enable_all=True, absent={"active_repairs", "tomorrow_outlook", "ev_session_cost"}),
        FakeRegistry(
            enable_all=True,
            absent={"solar_today", "import_cost_today", "self_sufficiency", "house_load"},
        ),
    ],
    ids=["fresh", "all-enabled", "without-pr-481-sensors", "few-sensors"],
)
def test_every_section_holds_only_cards(registry):
    """A section that held None would break the frontend's grid."""
    dashboard = dashboard_dict(registry=registry)
    for view in dashboard["views"]:
        for section in view["sections"]:
            assert all(isinstance(card, dict) for card in section["cards"]), view["path"]
