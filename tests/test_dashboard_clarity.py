"""
The clarity fixes of the Settings, EV charger, Cost breakdown and Battery detail views.

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


def _cost_chart(config: dict) -> dict:
    (chart,) = _sections(config, "today")["Cost per day, last 14 days"]
    return chart


def _cost_names(config: dict) -> list[str]:
    """The tile names in the Cost section."""
    return _tile_names(_sections(config, "today")["Cost"])


def test_the_cost_chart_heading_says_what_it_plots_and_for_how_long():
    assert "Cost per day, last 14 days" in _sections(dashboard_dict(), "today")
    assert _cost_chart(seen_for(ev=True, switch=True, sensor=True))["days_to_show"] == 14


def test_the_cost_chart_names_its_series_as_the_cost_section_does():
    config = seen_for(ev=True, switch=True, sensor=True)
    series = [row["name"] for row in _cost_chart(config)["entities"]]
    assert series == ["Rest of house", "EV charging", "Immersion", "Export earnings"]
    assert set(series) <= set(_cost_names(config))


def test_the_cost_chart_does_not_draw_the_total_beside_its_parts():
    """Grid import is the house, EV and immersion costs added up, so it would count them twice."""
    config = seen_for(ev=True, switch=True, sensor=True)
    plotted = {row["entity"] for row in _cost_chart(config)["entities"]}
    assert IDS["import_cost_today"] not in plotted
    assert {IDS["house_cost_today"], IDS["zappi_cost_today"], IDS["immersion_cost_today"]} <= plotted
    tiles = [c["entity"] for c in _sections(config, "today")["Cost"] if c["type"] == "tile"]
    assert IDS["import_cost_today"] in tiles


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_the_cost_chart_plots_only_the_devices_there(combination):
    ev, switch, sensor = combination
    shown = seen_for(ev=ev, switch=switch, sensor=sensor)
    names = [row["name"] for row in _cost_chart(shown)["entities"]]
    assert ("EV charging" in names) == ev
    assert ("Immersion" in names) == switch
    assert {"Rest of house", "Export earnings"} <= set(names)
    assert "Grid import" not in names


# ── EV charger ───────────────────────────────────────────────────────────────


def _ev_sections(config: dict) -> dict[str, list[dict]]:
    return _sections(config, "ev-charger")


def test_the_ev_view_shows_what_the_charger_used_and_cost_today():
    today = _ev_sections(seen_for(ev=True))["Today"]
    assert [(c["name"], c["entity"]) for c in today] == [
        ("Energy", IDS["zappi_today"]),
        ("Cost", IDS["zappi_cost_today"]),
    ]


def test_the_ev_view_plots_the_charge_power_for_24_hours():
    cards = _ev_sections(seen_for(ev=True))["Charge power, last 24 hours"]
    (chart,) = cards
    assert chart["type"] == "history-graph"
    assert chart["hours_to_show"] == 24
    assert chart["entities"] == [{"entity": IDS["ev_power"], "name": "Charge power"}]
    assert chart["grid_options"]["columns"] == "full"


def test_the_ev_charge_power_is_the_external_chargers_when_there_is_one():
    config, brand = install(ev=True)
    generated = dashboard_dict(config, ev_brand=brand, states=("sensor.wallbox_charging_power",))
    shown = seen(generated, states_with(devices_of(config, brand)))
    (chart,) = _ev_sections(shown)["Charge power, last 24 hours"]
    assert chart["entities"][0]["entity"] == "sensor.wallbox_charging_power"


def test_the_ev_view_plots_a_sensor_that_does_not_reset_in_a_history_graph():
    """Power does not fall to zero at midnight, so a history graph has no sawtooth to draw."""
    from tests.dashboard_support import midnight_reset_ids

    cards = _ev_sections(seen_for(ev=True))["Charge power, last 24 hours"]
    assert {row["entity"] for row in cards[0]["entities"]}.isdisjoint(midnight_reset_ids())


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_the_ev_view_is_empty_unless_a_charger_is_there(combination):
    ev, switch, sensor = combination
    view = _view(seen_for(ev=ev, switch=switch, sensor=sensor), "ev-charger")
    assert bool(view["sections"]) == ev
    if ev:
        assert list(_ev_sections(seen_for(ev=ev, switch=switch, sensor=sensor))) == [
            "Charging now",
            "Why",
            "Today",
            "Charge power, last 24 hours",
        ]


def test_a_file_made_before_the_charger_arrived_shows_the_new_sections_when_it_does():
    config, _ = install(ev=False)
    stored = dashboard_dict(config, ev_brand=None)
    assert _view(seen(stored, states_with(devices_of(config, None))), "ev-charger")["sections"] == []
    arrived = seen(stored, states_with(devices_of(config, "myenergi")))
    assert "Today" in _ev_sections(arrived)


# ── Battery detail ───────────────────────────────────────────────────────────


def test_health_holds_the_battery_and_the_inverter():
    sections = _sections(dashboard_dict(), "plan")
    assert _tile_names(sections["Health"]) == [
        "Total cycles",
        "Life remaining",
        "Since full",
        "Inverter temp",
        "Inverter status",
    ]


def test_the_inverter_tiles_are_left_out_without_an_inverter_temperature_entity():
    config = {k: v for k, v in FULL_CONFIG.items() if k != CONF_INVERTER_TEMP_ENTITY}
    sections = _sections(dashboard_dict(config, FakeRegistry(enable_all=True)), "plan")
    assert _tile_names(sections["Health"]) == ["Total cycles", "Life remaining", "Since full"]


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_the_plan_tab_does_not_depend_on_the_devices(combination):
    ev, switch, sensor = combination
    shown = _view(seen_for(ev=ev, switch=switch, sensor=sensor), "plan")
    assert [s["cards"][0]["heading"] for s in shown["sections"]] == [
        "Tonight's charge",
        "Battery overnight",
        "Battery",
        "Bill",
        "Cost per day, last 31 days",
        "Health",
    ]


def test_the_overnight_card_does_not_repeat_its_heading():
    cards = _sections(dashboard_dict(), "plan")["Battery overnight"]
    first = next(c for c in cards if c["type"] == "markdown")
    assert "**Battery overnight" not in first["content"]


# ── Settings ─────────────────────────────────────────────────────────────────


def _immersion_settings(config: dict) -> list[dict]:
    return _sections(config, "settings")["Hot water"]


def test_the_divert_reason_leads_the_hot_water_section():
    """What the heater is doing now comes first, so the controls below read against it."""
    cards = _immersion_settings(dashboard_dict())
    assert cards[0]["type"] == "markdown"
    assert IDS["immersion_divert_reason"] in cards[0]["content"]


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
        assert IDS["immersion_divert_reason"] in sections["Hot water"][0]["content"]


# ── Managed and Restart gap, in words ────────────────────────────────────────

MANAGED = (
    "**Heat now**: turn it on to force a heating run until the water reaches the target. "
    "Turn it off to hold the heater off for 10 minutes."
)
RESTART_GAP = (
    "**Restart drop**: how far the water must fall below the target before a new heating run "
    "starts."
)


def _markdown(cards: list[dict]) -> list[str]:
    return [c["content"] for c in cards if c["type"] == "markdown"]


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_the_immersion_settings_in_force_explain_the_settings_the_install_has(combination):
    ev, switch, sensor = combination
    shown = seen_for(ev=ev, switch=switch, sensor=sensor)
    cards = _sections(shown, "immersion").get("Settings in force", [])
    text = _markdown(cards)
    assert (MANAGED in text) == switch
    assert (RESTART_GAP in text) == (switch and sensor)


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_the_settings_view_explains_the_settings_the_install_has(combination):
    """Hot water explains Heat now. Fine-tuning explains each of its numbers in one card."""
    ev, switch, sensor = combination
    shown = seen_for(ev=ev, switch=switch, sensor=sensor)
    sections = _sections(shown, "settings")
    assert (MANAGED in _markdown(sections.get("Hot water", []))) == switch
    (note,) = _markdown(sections["Fine-tuning"])
    assert note.startswith("- **Cheap rate floor**")
    assert ("**Min battery**" in note) == switch
    assert ("**Restart drop**" in note) == (switch and sensor)


def test_the_fine_tuning_note_follows_its_controls():
    cards = _sections(seen_for(switch=True, sensor=True), "settings")["Fine-tuning"]
    kinds = [c["type"] for c in cards]
    assert kinds[-1] == "markdown"
    assert "markdown" not in kinds[:-1]
    names = [c["name"] for c in cards if c["type"] == "tile"]
    assert names == [
        "Cheap rate floor",
        "Skip charge above",
        "Forecast caution",
        "Min battery",
        "Min surplus",
        "Restart drop",
        "Re-plan charge",
        "Verbose logging",
    ]


def test_the_help_comes_after_the_tiles_of_the_immersion_view():
    cards = _sections(seen_for(switch=True, sensor=True), "immersion")["Settings in force"]
    kinds = [c["type"] for c in cards]
    assert kinds == ["tile"] * 6 + ["markdown"] * 2


def test_the_managed_help_states_the_cooldown_the_actuator_uses():
    from custom_components.givenergy_inverter_manager.const import (
        IMMERSION_SWITCH_COOLDOWN_MINUTES,
    )

    assert f"{IMMERSION_SWITCH_COOLDOWN_MINUTES} minutes" in MANAGED


# ── names that mean something alone ──────────────────────────────────────────


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
def test_the_cost_view_says_whose_saving_the_solar_tile_is(combination):
    ev, switch, sensor = combination
    cards = _sections(seen_for(ev=ev, switch=switch, sensor=sensor), "today")["Cost"]
    tiles = {c["name"]: c for c in cards if c["type"] == "tile"}
    assert ("Immersion solar saving" in tiles) == switch
    assert "Saved by solar" not in tiles
    if switch:
        tile = tiles["Immersion solar saving"]
        assert tile["entity"] == IDS["immersion_savings_today"]
        assert tile["grid_options"]["columns"] == "full"


def test_the_immersion_view_keeps_its_short_name_under_the_immersion_heading():
    cards = _sections(seen_for(switch=True), "immersion")["Today"]
    assert "Saved by solar" in [c["name"] for c in cards if c["type"] == "tile"]


def test_the_solar_view_says_what_the_yesterday_figure_is():
    cards = _sections(dashboard_dict(), "today")["Against the forecast"]
    tiles = {c["name"]: c for c in cards if c["type"] == "tile"}
    assert "Yesterday" not in tiles
    tile = tiles["Yesterday's accuracy"]
    assert tile["entity"] == IDS["yesterday_forecast_accuracy_pct"]
    assert tile["grid_options"]["columns"] == "full"


def _caption(config: dict) -> list[dict]:
    cards = _sections(config, "today").get("Against the forecast", [])
    return [c for c in cards if c["type"] == "markdown"]


def test_the_solar_view_explains_plan_forecast_under_the_tiles():
    cards = _sections(dashboard_dict(), "today")["Against the forecast"]
    assert cards[-1]["type"] == "markdown"
    assert cards[-1]["content"] == (
        "**Plan forecast** is the forecast the charge plan uses: blended toward the low "
        "estimate and corrected by past accuracy."
    )
    assert cards[-1]["grid_options"]["columns"] == "full"


def test_the_plan_forecast_caption_needs_a_forecast_sensor():
    config = {k: v for k, v in FULL_CONFIG.items() if k != CONF_FORECAST_ENTITY}
    assert _caption(dashboard_dict(config)) == []


def test_the_plan_forecast_caption_goes_with_its_tile():
    registry = FakeRegistry(enable_all=True, absent={"solar_forecast_kwh_today"})
    config = dashboard_dict(registry=registry)
    assert _caption(config) == []
    names = [c.get("name") for c in _sections(config, "today")["Against the forecast"]]
    assert "Plan forecast" not in names


def test_every_full_width_name_fits_the_tile():
    for name in ("Immersion solar saving", "Yesterday's accuracy"):
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
