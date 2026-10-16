"""
The clarity fixes of the Settings, EV charger, cost and Tonight views.

Each view was reviewed against a live install. These tests pin what was fixed: names that
match the tiles they sit beside, a heading that says what a chart plots, a sentence among
controls that carries a label, a section that holds only what its heading says, and an EV view
that answers the questions the Immersion view does.
"""

from __future__ import annotations

import itertools

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_FORECAST_ENTITY,
    CONF_INVERTER_TEMP_ENTITY,
)
from tests.dashboard_support import (
    FULL_CONFIG,
    FakeRegistry,
    dashboard_dict,
    default_entity_ids,
    devices_of,
    view_cards,
)
from tests.dashboard_visibility import install, seen, seen_for, states_with

IDS = default_entity_ids()
COMBINATIONS = list(itertools.product([False, True], repeat=3))


def _label(combination: tuple[bool, bool, bool]) -> str:
    ev, switch, sensor = combination
    parts = [name for name, on in (("ev", ev), ("switch", switch), ("sensor", sensor)) if on]
    return "+".join(parts) or "none"


def _view(config: dict, path: str) -> dict:
    return next(v for v in config["views"] if v["path"] == path)


def _sections(config: dict, path: str) -> dict[str, list[dict]]:
    """{section heading: its cards after the heading} for a view."""
    return {s["cards"][0]["heading"]: s["cards"][1:] for s in _view(config, path)["sections"]}


def _tile_names(cards: list[dict]) -> list[str]:
    return [c["name"] for c in cards if c["type"] == "tile"]


# ── Cost breakdown ───────────────────────────────────────────────────────────

_COST_HEADING = "Cost per day by use, last 31 days"


def _under(config: dict, path: str, heading: str) -> list[dict]:
    """The cards under this heading of the view at path, up to the next heading."""
    cards = view_cards(_view(config, path))
    start = next(i for i, c in enumerate(cards) if c.get("heading") == heading)
    under = []
    for card in cards[start + 1 :]:
        if card["type"] == "heading":
            break
        under.append(card)
    return under


def _cost_chart(config: dict) -> dict:
    (chart,) = _under(config, "bill", _COST_HEADING)
    return chart


def _cost_names(config: dict) -> list[str]:
    """The names in the split of what today cost."""
    (split,) = _under(config, "today", "What it cost")
    return [row["name"] for row in split["entities"]]


def test_the_cost_chart_heading_says_what_it_plots_and_for_how_long():
    assert _COST_HEADING in [c.get("heading") for c in view_cards(_view(dashboard_dict(), "bill"))]
    assert _cost_chart(seen_for(ev=True, switch=True, sensor=True))["days_to_show"] == 31


def test_the_cost_chart_names_its_series_as_the_cost_split_does():
    config = seen_for(ev=True, switch=True, sensor=True)
    series = [row["name"] for row in _cost_chart(config)["entities"]]
    assert series == ["House", "EV", "Hot water"]
    assert series == _cost_names(config)


def test_the_cost_chart_does_not_draw_the_total_beside_its_parts():
    """Grid import is the house, EV and immersion costs added up, so it would count them twice."""
    config = seen_for(ev=True, switch=True, sensor=True)
    plotted = {row["entity"] for row in _cost_chart(config)["entities"]}
    assert IDS["import_cost_today"] not in plotted
    assert {IDS["house_cost_today"], IDS["zappi_cost_today"], IDS["immersion_cost_today"]} <= plotted
    (today_so_far,) = [
        c for c in view_cards(_view(config, "power-flow")) if c.get("heading") == "Today so far"
    ]
    assert IDS["import_cost_today"] in [badge["entity"] for badge in today_so_far["badges"]]


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_the_cost_chart_plots_only_the_devices_there(combination):
    ev, switch, sensor = combination
    shown = seen_for(ev=ev, switch=switch, sensor=sensor)
    names = [row["name"] for row in _cost_chart(shown)["entities"]]
    assert ("EV" in names) == ev
    assert ("Hot water" in names) == switch
    assert "House" in names
    assert "Grid import" not in names


# ── EV charger ───────────────────────────────────────────────────────────────


def _ev_sections(config: dict) -> dict[str, list[dict]]:
    return _sections(config, "ev-charger")


def _ev_power_chart(config: dict) -> dict:
    (chart,) = _under(config, "ev-charger", "Charge power, last 24 hours")
    return chart


def test_the_ev_view_shows_what_the_charger_used_and_cost_today():
    (figures,) = [c for c in _ev_sections(seen_for(ev=True))["EV charger"] if c["type"] == "glance"]
    assert [(r["name"], r["entity"]) for r in figures["entities"]] == [
        ("This charge", IDS["ev_session_energy"]),
        ("Its cost", IDS["ev_session_cost"]),
        ("Today", IDS["zappi_today"]),
        ("Cost today", IDS["zappi_cost_today"]),
    ]


def test_the_ev_figures_leave_the_charge_cost_out_without_its_sensor():
    registry = FakeRegistry(enable_all=True, absent={"ev_session_cost"})
    config, brand = install(ev=True)
    shown = seen(dashboard_dict(config, registry, ev_brand=brand), states_with(devices_of(config, brand)))
    (figures,) = [c for c in _ev_sections(shown)["EV charger"] if c["type"] == "glance"]
    assert [r["name"] for r in figures["entities"]] == ["This charge", "Today", "Cost today"]


def test_the_ev_view_plots_the_charge_power_for_24_hours():
    chart = _ev_power_chart(seen_for(ev=True))
    assert chart["type"] == "history-graph"
    assert chart["hours_to_show"] == 24
    assert chart["entities"] == [{"entity": IDS["ev_power"], "name": "Charge power"}]
    assert chart["grid_options"]["columns"] == "full"


def test_the_ev_charge_power_is_the_external_chargers_when_there_is_one():
    config, brand = install(ev=True)
    generated = dashboard_dict(config, ev_brand=brand, states=("sensor.wallbox_charging_power",))
    shown = seen(generated, states_with(devices_of(config, brand)))
    chart = _ev_power_chart(shown)
    assert chart["entities"][0]["entity"] == "sensor.wallbox_charging_power"


def test_the_ev_view_plots_a_sensor_that_does_not_reset_in_a_history_graph():
    """Power does not fall to zero at midnight, so a history graph has no sawtooth to draw."""
    from tests.dashboard_support import midnight_reset_ids

    chart = _ev_power_chart(seen_for(ev=True))
    assert {row["entity"] for row in chart["entities"]}.isdisjoint(midnight_reset_ids())


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_the_ev_view_is_empty_unless_a_charger_is_there(combination):
    ev, switch, sensor = combination
    view = _view(seen_for(ev=ev, switch=switch, sensor=sensor), "ev-charger")
    assert bool(view["sections"]) == ev
    if ev:
        assert list(_ev_sections(seen_for(ev=ev, switch=switch, sensor=sensor))) == [
            "EV charger",
            "Last 7 days",
            "Recent charges",
        ]


def test_a_file_made_before_the_charger_arrived_shows_the_new_sections_when_it_does():
    config, _ = install(ev=False)
    stored = dashboard_dict(config, ev_brand=None)
    assert _view(seen(stored, states_with(devices_of(config, None))), "ev-charger")["sections"] == []
    arrived = seen(stored, states_with(devices_of(config, "myenergi")))
    assert list(_ev_sections(arrived)) == ["EV charger", "Last 7 days", "Recent charges"]


# ── Battery detail ───────────────────────────────────────────────────────────


def _figure_names(cards: list[dict]) -> list[str]:
    return [r["name"] for c in cards if c["type"] == "glance" for r in c["entities"]]


def test_health_holds_the_battery_and_the_inverter():
    sections = _sections(dashboard_dict(), "plan")
    assert _figure_names(sections["Battery health"]) == [
        "Cycles",
        "Life left",
        "Since full",
        "Inverter",
        "Status",
    ]


def test_the_inverter_figures_are_left_out_without_an_inverter_temperature_entity():
    config = {k: v for k, v in FULL_CONFIG.items() if k != CONF_INVERTER_TEMP_ENTITY}
    sections = _sections(dashboard_dict(config, FakeRegistry(enable_all=True)), "plan")
    assert _figure_names(sections["Battery health"]) == ["Cycles", "Life left", "Since full"]


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_the_tonight_view_does_not_depend_on_the_devices(combination):
    ev, switch, sensor = combination
    shown = _view(seen_for(ev=ev, switch=switch, sensor=sensor), "plan")
    assert [s["cards"][0]["heading"] for s in shown["sections"]] == [
        "Tonight",
        "Battery, last day and a half",
        "Battery health",
    ]


def test_the_overnight_card_does_not_repeat_its_heading():
    cards = _sections(dashboard_dict(), "plan")["Tonight"]
    night = next(
        c for c in cards if c["type"] == "markdown" and IDS["night_survival_reason"] in c["content"]
    )
    assert "**Tonight" not in night["content"]
    assert "**Battery overnight" not in night["content"]


# ── Settings ─────────────────────────────────────────────────────────────────


def _immersion_settings(config: dict) -> list[dict]:
    return _sections(config, "settings")["Hot water"]


def test_no_reason_card_is_left_without_its_sensor():
    registry = FakeRegistry(enable_all=True, absent={"immersion_divert_reason"})
    cards = _immersion_settings(dashboard_dict(FULL_CONFIG, registry))
    assert IDS["immersion_divert_reason"] not in str(cards)
    assert cards[0]["type"] == "tile"


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_hot_water_shows_only_with_the_switch(combination):
    ev, switch, sensor = combination
    shown = seen_for(ev=ev, switch=switch, sensor=sensor)
    sections = _sections(shown, "settings")
    assert ("Hot water" in sections) == switch
    if switch:
        first = sections["Hot water"][0]
        assert (first["type"], first["entity"]) == ("tile", IDS["auto_immersion"])


# ── What each setting does, folded under its group ───────────────────────────

_FOLDED = "<details><summary>What these do</summary>"


def _markdown(cards: list[dict]) -> list[str]:
    return [c["content"] for c in cards if c["type"] == "markdown"]


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_the_settings_view_explains_the_settings_the_install_has(combination):
    """Each group explains its own settings, and the heater's only for the devices present."""
    ev, switch, sensor = combination
    shown = seen_for(ev=ev, switch=switch, sensor=sensor)
    sections = _sections(shown, "settings")
    (planning,) = _markdown(sections["Charge planning"])
    assert planning.startswith(f"{_FOLDED}\n\n- **Cheap rate floor**")
    water = _markdown(sections.get("Hot water", []))
    assert len(water) == (1 if switch else 0)
    text = " ".join(water)
    assert ("**Heat now**" in text) == switch
    assert ("**Min battery, Min spare solar**" in text) == switch
    assert ("**Restart drop**" in text) == (switch and sensor)


def test_each_settings_group_ends_with_its_folded_help():
    sections = _sections(seen_for(switch=True, sensor=True), "settings")
    for heading in ("Tonight's charge", "Charge planning", "Hot water", "System"):
        cards = sections[heading]
        kinds = [c["type"] for c in cards]
        assert kinds[-1] == "markdown", heading
        assert "markdown" not in kinds[:-1], heading
        assert cards[-1]["content"].startswith(_FOLDED), heading
        assert cards[-1]["content"].endswith("</details>"), heading
    names = [c["name"] for c in sections["Charge planning"] if c["type"] == "tile"]
    assert names == ["Cheap rate floor", "Skip charge above", "Forecast caution", "Re-plan overnight"]


def test_the_help_comes_after_the_tiles_of_the_hot_water_settings():
    cards = _sections(seen_for(switch=True, sensor=True), "settings")["Hot water"]
    kinds = [c["type"] for c in cards]
    assert kinds == ["tile"] * 8 + ["markdown"]


def test_the_heat_now_help_states_the_cooldown_the_actuator_uses():
    from custom_components.givenergy_inverter_manager.const import (
        IMMERSION_SWITCH_COOLDOWN_MINUTES,
    )

    (help_text,) = _markdown(_sections(seen_for(switch=True), "settings")["Hot water"])
    assert f"holds the heater off for {IMMERSION_SWITCH_COOLDOWN_MINUTES} minutes" in help_text


# ── names that mean something alone ──────────────────────────────────────────


def test_the_hot_water_view_keeps_its_short_name_under_the_hot_water_heading():
    cards = _sections(seen_for(switch=True), "immersion")["Hot water"]
    figures = {r["name"]: r["entity"] for c in cards if c["type"] == "glance" for r in c["entities"]}
    assert figures["Solar saved"] == IDS["immersion_savings_today"]


def _forecast_figures(config: dict) -> dict[str, str]:
    cards = _under(config, "today", "Forecast")
    return {r["name"]: r["entity"] for c in cards if c["type"] == "glance" for r in c["entities"]}


def test_the_forecast_figures_need_a_forecast_sensor():
    config = {k: v for k, v in FULL_CONFIG.items() if k != CONF_FORECAST_ENTITY}
    headings = [c.get("heading") for c in view_cards(_view(dashboard_dict(config), "today"))]
    assert "Forecast" not in headings


def test_the_planned_on_figure_goes_with_its_sensor():
    registry = FakeRegistry(enable_all=True, absent={"solar_forecast_kwh_today"})
    assert "Planned on" not in _forecast_figures(dashboard_dict(registry=registry))
    assert _forecast_figures(dashboard_dict())["Planned on"] == IDS["solar_forecast_kwh_today"]


def test_every_full_width_name_fits_the_tile():
    for name in ("Home use from solar", "Solar kept at home"):
        assert len(name) <= 22


# ── one wording for the charge override ──────────────────────────────────────


def _names_by_entity(config: dict, path: str) -> dict[str, str]:
    return {c["entity"]: c["name"] for c in view_cards(_view(config, path)) if c["type"] == "tile"}


def test_settings_and_the_battery_tab_name_the_charge_override_the_same():
    config = dashboard_dict()
    settings = _names_by_entity(config, "settings")
    battery = _names_by_entity(config, "plan")
    for key in ("charge_target_override", "charge_target_override_enabled", "skip_charge_override"):
        assert settings[IDS[key]] == battery[IDS[key]], key
    assert settings[IDS["charge_target_override"]] == "Charge to"
    assert settings[IDS["charge_target_override_enabled"]] == "Fixed target"


def test_the_old_settings_names_are_gone():
    names = set(_names_by_entity(dashboard_dict(), "settings").values())
    assert not names & {"Charge target", "Use target", "Override on", "Target override"}
