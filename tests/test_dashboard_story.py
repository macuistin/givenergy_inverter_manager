"""
The story layout: Home energy's chips and sentence, and what each sub-view adds.

Home energy is the one tab. It tells what the house runs on in a sentence, gives the figures
worth a glance as chips, and opens every sub-view from a row of shortcuts. The sentences are
markdown templates, so these tests render them with Jinja and the template functions Home
Assistant provides (tests/test_dashboard.py holds the stand-ins).
"""

from __future__ import annotations

import itertools

import pytest
import yaml

from custom_components.givenergy_inverter_manager.const import CONF_FORECAST_ENTITY
from custom_components.givenergy_inverter_manager.core.devices import Device
from custom_components.givenergy_inverter_manager.dashboard.cards import TABLE_CSS, TOTAL_CSS
from custom_components.givenergy_inverter_manager.dashboard.templates import (
    ChargerNow,
    DayTotals,
    PowerNow,
    WaterNow,
    ev_story_template,
    now_story_template,
    saved_template,
    today_story_template,
    tomorrow_story_template,
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
from tests.dashboard_visibility import generated_for, install, seen, seen_for, states_with
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
    for section in _view(dashboard, path)["sections"]:
        if section["cards"][0].get("heading") == heading:
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


# ── Home energy's chips ──────────────────────────────────────────────────────


class TestTheChips:
    def test_today_so_far_gives_solar_the_cost_and_self_sufficiency_and_opens_today(self):
        heading = _heading(dashboard_dict(), "Today so far")
        assert heading["heading_style"] == "subtitle"
        assert [b["entity"] for b in heading["badges"]] == [
            IDS["solar_today"],
            IDS["import_cost_today"],
            IDS["self_sufficiency"],
        ]
        assert heading["tap_action"] == {"action": "navigate", "navigation_path": "today"}

    def test_today_so_far_is_left_out_with_no_chip_to_show(self):
        """A heading with nothing under it and no chips would stand alone."""
        registry = FakeRegistry(
            enable_all=True, absent={"solar_today", "import_cost_today", "self_sufficiency"}
        )
        section = _section(dashboard_dict(registry=registry), "power-flow", "Right now")
        assert None not in section["cards"]
        assert "Today so far" not in [c.get("heading") for c in section["cards"]]

    def test_each_device_chip_opens_its_device_view(self):
        heading = _heading(dashboard_dict(), "Hot water and EV")
        opens = {b["entity"]: b["tap_action"]["navigation_path"] for b in heading["badges"]}
        assert opens == {
            IDS["immersion_water_temperature"]: "immersion",
            IDS["immersion_power"]: "immersion",
            IDS["ev_charger_state"]: "ev-charger",
        }

    def test_each_device_chip_carries_its_own_device_condition(self):
        badges = {b["entity"]: b for b in _heading(dashboard_dict(), "Hot water and EV")["badges"]}
        unavailable = {"state_not": "unavailable"}
        assert badges[IDS["immersion_water_temperature"]]["visibility"] == [
            {"condition": "state", "entity": IDS["immersion_water_temperature"], **unavailable}
        ]
        assert badges[IDS["ev_charger_state"]]["visibility"] == [
            {"condition": "state", "entity": IDS["ev_charger_state"], **unavailable}
        ]
        assert badges[IDS["immersion_power"]]["visibility"] == [
            {"condition": "state", "entity": IDS["immersion_managed"], **unavailable},
            {"condition": "numeric_state", "entity": IDS["immersion_power"], "above": 0},
        ]

    @pytest.mark.parametrize("later", COMBINATIONS, ids=_label)
    def test_a_file_made_with_no_device_shows_the_chips_of_a_device_added_later(self, later):
        ev, switch, sensor = later
        config, brand = install(ev=ev, switch=switch, sensor=sensor)
        heating = {IDS["immersion_power"]: "3000"} if switch else None
        states = states_with(devices_of(config, brand), heating)
        stored = seen(generated_for(), states)
        regenerated = seen(generated_for(ev=ev, switch=switch, sensor=sensor), states)
        assert _view(stored, "power-flow") == _view(regenerated, "power-flow")


# ── The story sentences ──────────────────────────────────────────────────────

_POWER = PowerNow("sensor.solar", "sensor.house", "sensor.battery", "sensor.grid")


def _now(values: dict[str, str], attrs: dict | None = None, *, target=None, outlook=None) -> str:
    template = now_story_template(_POWER, target, outlook)
    return _render(template, lambda e: values.get(e, "unknown"), attrs or {})


class TestTheRightNowSentence:
    def test_it_names_what_the_house_runs_on(self):
        values = {"sensor.solar": "2400", "sensor.house": "1300", "sensor.battery": "-600"}
        text = _now(values | {"sensor.grid": "300"})
        assert text == "**Running on solar and the battery and the grid.** House 1.3 kW."

    def test_it_says_the_battery_charges_and_what_is_exported(self):
        values = {"sensor.solar": "4000", "sensor.house": "800", "sensor.battery": "1500"}
        text = _now(values | {"sensor.grid": "-1700"})
        assert text == (
            "**Running on solar.** House 0.8 kW, battery charging 1.5 kW, exporting 1.7 kW."
        )

    def test_a_few_watts_of_standby_are_not_a_source(self):
        values = {"sensor.solar": "20", "sensor.house": "40", "sensor.battery": "-30"}
        assert _now(values | {"sensor.grid": "40"}).startswith("**Nothing running.**")

    def test_it_reads_the_integrations_power_sensors_on_home_energy(self):
        cards = view_cards(_view(dashboard_dict(), "power-flow"))
        (story,) = [c for c in cards if c["type"] == "markdown" and IDS["house_load"] in c["content"]]
        for key in ("solar_power", "house_load", "battery_power", "grid_power"):
            assert f"states('{IDS[key]}')" in story["content"], key
        assert f"state_attr('{IDS['overnight_charge_target']}', 'plan')" in story["content"]
        assert f"state_attr('{IDS['night_survival_confidence']}', 'outlook')" in story["content"]

    @pytest.mark.parametrize(
        ("plan", "tonight"), [("skip", "no charge needed"), ("charge", "charging to 80%")]
    )
    def test_it_says_what_tonight_holds_and_the_outlook(self, plan, tonight):
        values = {"sensor.solar": "0", "sensor.house": "500", "sensor.battery": "-500"}
        attrs = {("sensor.target", "plan"): plan, ("sensor.outlook", "outlook"): "Lasts the night"}
        values |= {"sensor.grid": "0", "sensor.target": "80"}
        text = _now(values, attrs, target="sensor.target", outlook="sensor.outlook")
        assert text.endswith(f"Tonight: {tonight}, lasts the night.")

    def test_without_the_power_sensors_there_is_no_sentence_and_the_chips_stay(self):
        registry = FakeRegistry(enable_all=True, absent={"house_load"})
        section = _section(dashboard_dict(registry=registry), "power-flow", "Right now")
        assert not [c for c in section["cards"] if c["type"] == "markdown"]
        assert [b["entity"] for b in section["cards"][0]["badges"]] == [
            IDS["battery_soc"],
            IDS["current_rate"],
            IDS["next_cheap_rate_start"],
        ]
        assert None not in section["cards"]


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
        headings = [s["cards"][0]["heading"] for s in _view(dashboard, "power-flow")["sections"]]
        assert headings[2:5] == ["Finish setting up", "Needs your attention", "Live power flow"]

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


# ── The shortcuts ────────────────────────────────────────────────────────────


def _shortcuts(dashboard: dict) -> dict[str, dict]:
    more = _section(dashboard, "power-flow", "More")
    return {c["label"]: c for c in more["cards"] if c["type"] == "shortcut"}


class TestTheShortcuts:
    def test_there_is_one_for_each_sub_view_and_each_opens_it(self):
        dashboard = dashboard_dict()
        shortcuts = _shortcuts(dashboard)
        opens = {label: c["tap_action"]["navigation_path"] for label, c in shortcuts.items()}
        assert opens == {
            "Today": "today",
            "Tonight": "plan",
            "Tomorrow": "tomorrow",
            "Bill & tariff": "bill",
            "Hot water": "immersion",
            "EV charger": "ev-charger",
            "Settings": "settings",
        }
        assert set(opens.values()) == _paths(dashboard) - {"power-flow"}

    def test_a_sub_view_that_is_left_out_has_no_shortcut(self):
        config = {k: v for k, v in MINIMAL_CONFIG.items() if k != CONF_FORECAST_ENTITY}
        registry = FakeRegistry(absent={"tomorrow_outlook"})
        dashboard = dashboard_dict(config, registry, is_admin=False, ev_brand=None)
        labels = set(_shortcuts(dashboard))
        assert not {"Tomorrow", "Settings"} & labels
        targets = {c["tap_action"]["navigation_path"] for c in _shortcuts(dashboard).values()}
        assert targets <= _paths(dashboard)

    @pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
    def test_the_device_shortcuts_show_only_with_their_device(self, combination):
        ev, switch, sensor = combination
        labels = set(_shortcuts(seen_for(ev=ev, switch=switch, sensor=sensor)))
        assert ("Hot water" in labels) == (switch or sensor)
        assert ("EV charger" in labels) == ev


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
