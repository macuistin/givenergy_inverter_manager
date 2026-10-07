"""
The dashboard for every combination of the optional devices, and for a device that comes or goes.

The EV charger, the immersion switch and the immersion temperature sensor are optional. The
generator hides the cards of a missing device with visibility conditions. These tests render
the config for each combination, play the part of the Lovelace frontend with
tests/dashboard_visibility.py, and assert on what a person would see.
"""

from __future__ import annotations

import itertools

import pytest
import yaml

from custom_components.givenergy_inverter_manager.core.devices import Device, installed_devices
from custom_components.givenergy_inverter_manager.dashboard.devices import (
    SENTINELS,
    expected_entity_id,
)
from tests.dashboard_support import (
    all_cards,
    default_entity_ids,
    keys_needing_devices,
    view_cards,
)
from tests.dashboard_visibility import (
    condition_holds,
    generated_for,
    install,
    seen,
    seen_for,
    states_with,
)

IDS = default_entity_ids()
COMBINATIONS = list(itertools.product([False, True], repeat=3))


def _label(combination: tuple[bool, bool, bool]) -> str:
    ev, switch, sensor = combination
    parts = [name for name, on in (("ev", ev), ("switch", switch), ("sensor", sensor)) if on]
    return "+".join(parts) or "none"


def _view(config: dict, path: str) -> dict:
    return next(v for v in config["views"] if v["path"] == path)


def _titles(view: dict) -> list[str]:
    return [c["heading"] for c in view_cards(view) if c["type"] == "heading"]


def _tile_entities(view: dict) -> set[str]:
    return {c["entity"] for c in view_cards(view) if c["type"] == "tile"}


def _devices_section_tiles(config: dict) -> list[str]:
    cards = view_cards(_view(config, "power-flow"))
    names = [c["name"] for c in cards if c["type"] == "tile" and c["name"] in ("Immersion", "EV charger")]
    return names


# ── what each combination shows ──────────────────────────────────────────────


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
class TestEveryCombination:
    def _seen(self, combination) -> dict:
        ev, switch, sensor = combination
        return seen_for(ev=ev, switch=switch, sensor=sensor)

    def test_the_devices_tiles_are_the_devices_present(self, combination):
        ev, switch, sensor = combination
        shown = _devices_section_tiles(self._seen(combination))
        assert shown.count("Immersion") == (1 if switch or sensor else 0)
        assert shown.count("EV charger") == (1 if ev else 0)

    def test_the_devices_heading_shows_only_with_a_device(self, combination):
        ev, switch, sensor = combination
        power_flow = _view(self._seen(combination), "power-flow")
        assert ("Devices" in _titles(power_flow)) == (ev or switch or sensor)

    def test_the_nav_tiles_open_a_view_that_has_something_to_show(self, combination):
        config = self._seen(combination)
        for tile in (c for c in view_cards(_view(config, "power-flow")) if c["type"] == "tile"):
            target = tile.get("tap_action", {}).get("navigation_path")
            if target in ("immersion", "ev-charger"):
                assert _view(config, target)["sections"], (target, _label(combination))

    def test_the_ev_view_shows_with_a_charger_and_is_empty_without_one(self, combination):
        ev, _, _ = combination
        view = _view(self._seen(combination), "ev-charger")
        assert bool(view["sections"]) == ev

    def test_the_water_temperature_chart_needs_the_sensor(self, combination):
        _, _, sensor = combination
        titles = _titles(_view(self._seen(combination), "immersion"))
        assert ("Water temperature" in titles) == sensor

    def test_the_heater_cards_need_the_switch(self, combination):
        _, switch, _ = combination
        titles = _titles(_view(self._seen(combination), "immersion"))
        for heading in ("Why", "Heater power", "Today", "Settings in force"):
            assert (heading in titles) == switch, heading

    def test_the_why_text_is_not_shown_without_a_switch(self, combination):
        """The reason says the heater is on or off, so it only makes sense with a heater."""
        _, switch, _ = combination
        config = self._seen(combination)
        text = yaml.safe_dump(config)
        assert (IDS["immersion_divert_reason"] in text) == switch

    def test_no_chart_plots_a_heater_that_does_not_exist(self, combination):
        _, switch, _ = combination
        view = _view(self._seen(combination), "immersion")
        plotted = yaml.safe_dump(view)
        for key in ("immersion_power", "immersion_today"):
            assert (IDS[key] in plotted) == switch, key

    def test_the_temperature_tiles_do_something_only_with_both_devices(self, combination):
        """Target, minimum and restart gap act on a switch with a sensor, so show only then."""
        _, switch, sensor = combination
        config = self._seen(combination)
        entities = _tile_entities(_view(config, "immersion"))
        for key in ("immersion_target_temp", "immersion_min_temp", "immersion_hysteresis"):
            assert (IDS[key] in entities) == (switch and sensor), key

    def test_the_settings_view_holds_the_controls_that_exist(self, combination):
        ev, switch, sensor = combination
        entities = _tile_entities(_view(self._seen(combination), "settings"))
        assert (IDS["auto_immersion"] in entities) == switch
        assert (IDS["immersion_managed"] in entities) == switch
        assert (IDS["immersion_target_temp"] in entities) == (switch and sensor)

    def test_the_today_tab_lists_the_ev_and_immersion_energy_for_the_devices_present(self, combination):
        ev, switch, _ = combination
        names = [
            c["name"]
            for c in view_cards(_view(self._seen(combination), "today"))
            if c["type"] == "tile"
        ]
        assert ("EV" in names) == ev
        assert ("Immersion" in names) == switch

    def test_the_sources_card_names_the_ev_and_immersion_energy_for_the_devices_present(
        self, combination
    ):
        ev, switch, _ = combination
        cards = view_cards(_view(self._seen(combination), "today"))
        lines = [c["content"] for c in cards if c["type"] == "markdown" and "Of the house use" in c["content"]]
        assert len(lines) == (1 if ev or switch else 0)
        text = " ".join(lines)
        assert ("the EV took" in text) == ev
        assert ("the immersion took" in text) == switch
        assert (IDS["zappi_today"] in text) == ev
        assert (IDS["immersion_today"] in text) == switch

    def test_the_sources_card_is_shown_whatever_the_devices(self, combination):
        today = _view(self._seen(combination), "today")
        assert "Where today's energy came from" in _titles(today)

    def test_the_cost_view_lists_the_ev_and_immersion_costs_for_the_devices_present(self, combination):
        ev, switch, _ = combination
        names = [
            c["name"]
            for c in view_cards(_view(self._seen(combination), "cost"))
            if c["type"] == "tile"
        ]
        assert ("EV charging" in names) == ev
        assert ("Immersion" in names) == switch
        assert ("Saved by solar" in names) == switch

    def test_exactly_one_power_flow_card_is_shown_and_it_draws_the_devices_present(self, combination):
        ev, switch, _ = combination
        config = self._seen(combination)
        flows = [
            c
            for c in view_cards(_view(config, "power-flow"))
            if c["type"] == "custom:power-flow-card-plus"
        ]
        assert len(flows) == 1
        drawn = [row["name"] for row in flows[0]["entities"].get("individual", [])]
        assert ("Car Charger" in drawn) == ev
        assert ("Immersion" in drawn) == switch

    def test_the_cost_history_plots_only_the_costs_that_exist(self, combination):
        ev, switch, _ = combination
        graphs = [
            c for c in view_cards(_view(self._seen(combination), "cost")) if c["type"] == "statistics-graph"
        ]
        assert len(graphs) == 1
        plotted = {row["entity"] for row in graphs[0]["entities"]}
        assert (IDS["zappi_cost_today"] in plotted) == ev
        assert (IDS["immersion_cost_today"] in plotted) == switch

    def test_the_views_that_never_depend_on_a_device_are_unchanged(self, combination):
        ev, switch, sensor = combination
        config = self._seen(combination)
        nothing = seen_for()
        for path in ("bill", "battery", "tariff", "battery-detail", "solar"):
            assert _view(config, path) == _view(nothing, path), path


# ── the stored file waits for a device and shows it when it comes ────────────


def _states(combination) -> dict[str, str]:
    config, brand = install(ev=combination[0], switch=combination[1], sensor=combination[2])
    return states_with(installed_devices(config, ev_charger_found=brand is not None))


@pytest.mark.parametrize("later", COMBINATIONS, ids=_label)
class TestADeviceAddedLater:
    def test_a_file_made_with_no_device_shows_what_one_made_after_would(self, later):
        """The stored file is not generated again. The same file shows the new device's cards."""
        stored = generated_for()
        regenerated = generated_for(ev=later[0], switch=later[1], sensor=later[2])
        assert seen(stored, _states(later)) == seen(regenerated, _states(later))

    def test_a_file_made_with_every_device_hides_the_ones_that_go(self, later):
        stored = generated_for(ev=True, switch=True, sensor=True)
        regenerated = generated_for(ev=later[0], switch=later[1], sensor=later[2])
        assert seen(stored, _states(later)) == seen(regenerated, _states(later))


@pytest.mark.parametrize(
    ("first", "then"),
    [(a, b) for a in COMBINATIONS for b in COMBINATIONS if a != b],
    ids=lambda c: _label(c),
)
def test_a_file_follows_any_change_of_devices_with_no_regeneration(first, then):
    stored = generated_for(ev=first[0], switch=first[1], sensor=first[2])
    regenerated = generated_for(ev=then[0], switch=then[1], sensor=then[2])
    assert seen(stored, _states(then)) == seen(regenerated, _states(then))


def test_a_cylinder_sensor_added_later_shows_its_chart_in_the_old_file():
    stored = generated_for(switch=True)
    before = seen(stored, _states((False, True, False)))
    after = seen(stored, _states((False, True, True)))
    assert "Water temperature" not in _titles(_view(before, "immersion"))
    assert "Water temperature" in _titles(_view(after, "immersion"))
    assert "Target temp" not in [c["name"] for c in view_cards(_view(before, "immersion")) if c["type"] == "tile"]
    assert "Target temp" in [c["name"] for c in view_cards(_view(after, "immersion")) if c["type"] == "tile"]


# ── the conditions themselves ────────────────────────────────────────────────

DEVICE_ENTITY_IDS = {
    expected_entity_id(key): device for key, device in keys_needing_devices().items()
}


def _cards_with_their_conditions(nodes, inherited=()):
    """Every card of a section list, paired with the visibility conditions above it."""
    for node in nodes:
        here = [*inherited, *node.get("visibility", [])]
        yield node, here
        yield from _cards_with_their_conditions(node.get("cards", []), here)


def _device_entities_named_by(card: dict) -> set[str]:
    """The entity IDs of ours that need a device, in the card apart from its own conditions."""
    text = yaml.safe_dump({k: v for k, v in card.items() if k != "visibility"})
    return {entity_id for entity_id in DEVICE_ENTITY_IDS if entity_id in text}


def _guarded_by(conditions: list[dict], device_name: str) -> bool:
    sentinel = expected_entity_id(SENTINELS[Device[device_name]])
    return sentinel in yaml.safe_dump(conditions)


# Cards that list many entities cannot hide one row. They are built once for each
# combination of devices, and the variants test below covers them.
_LISTS = ("custom:power-flow-card-plus", "entities", "statistics-graph", "history-graph")
_CHARTS = ("custom:apexcharts-card",)


def test_every_card_that_names_a_device_entity_is_hidden_without_that_device():
    """A card for the EV charger or the heater always sits under a condition on that device."""
    config = generated_for(ev=True, switch=True, sensor=True)
    unguarded = []
    for view in config["views"]:
        for section in view["sections"]:
            cards = _cards_with_their_conditions(section["cards"], section.get("visibility", []))
            for card, conditions in cards:
                if card["type"] in (*_LISTS, *_CHARTS):
                    continue
                for entity_id in _device_entities_named_by(card):
                    device = DEVICE_ENTITY_IDS[entity_id]
                    if not _guarded_by(conditions, device):
                        unguarded.append((view["path"], card.get("name"), entity_id))
    assert unguarded == []


def test_every_list_card_that_names_a_device_entity_carries_a_condition():
    """The cards that list entities, and the charts, are shown only for the right devices."""
    config = generated_for(ev=True, switch=True, sensor=True)
    for view in config["views"]:
        for section in view["sections"]:
            cards = _cards_with_their_conditions(section["cards"], section.get("visibility", []))
            for card, conditions in cards:
                if card["type"] in (*_LISTS, *_CHARTS) and _device_entities_named_by(card):
                    assert conditions, (view["path"], card["type"])


def test_no_card_is_shown_for_a_device_when_its_sentinel_is_unavailable_or_missing():
    config = generated_for(ev=True, switch=True, sensor=True)
    for device, sentinel_key in SENTINELS.items():
        sentinel = IDS[sentinel_key]
        for state in ("unavailable", None):
            states = states_with(Device)
            if state is None:
                del states[sentinel]
            else:
                states[sentinel] = state
            shown = yaml.safe_dump(seen(config, states))
            assert IDS[sentinel_key] not in shown, (device, state)


class TestTheFrontendRules:
    def test_a_missing_entity_counts_as_unavailable(self):
        condition = {"condition": "state", "entity": "sensor.gone", "state_not": "unavailable"}
        assert condition_holds(condition, {}) is False
        assert condition_holds({**condition, "state_not": "unknown"}, {}) is True

    def test_or_needs_one_condition_and_and_needs_all(self):
        up = {"condition": "state", "entity": "sensor.a", "state_not": "unavailable"}
        down = {"condition": "state", "entity": "sensor.b", "state_not": "unavailable"}
        states = {"sensor.a": "on"}
        assert condition_holds({"condition": "or", "conditions": [up, down]}, states)
        assert not condition_holds({"condition": "and", "conditions": [up, down]}, states)


def test_expected_ids_are_the_ones_home_assistant_assigns():
    """Name-derived IDs for the entities that wait for a device match the naming rule."""
    for key in keys_needing_devices():
        assert expected_entity_id(key) == IDS[key], key


def test_an_entity_with_no_device_has_no_expected_id():
    assert expected_entity_id("solar_power") is None


def test_the_visibility_a_device_card_carries_names_its_sentinel_entity():
    config = generated_for()
    flow = [
        c
        for c in view_cards(_view(config, "power-flow"))
        if c["type"] == "custom:power-flow-card-plus"
    ]
    assert len(flow) == 4  # one for each combination of the car charger and the heater
    conditions = {yaml.safe_dump(c["visibility"]) for c in flow}
    assert len(conditions) == 4
    for variant in flow:
        entities = {c["entity"] for c in variant["visibility"]}
        assert entities == {IDS["ev_charger_state"], IDS["immersion_managed"]}


def test_a_device_view_exists_with_no_device_so_a_later_device_has_somewhere_to_show():
    config = generated_for()
    assert {v["path"] for v in config["views"]} >= {"immersion", "ev-charger"}
    assert all_cards(config["views"])
