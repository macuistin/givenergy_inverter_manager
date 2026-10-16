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


def _device_chips(config: dict) -> list[str]:
    """The entities of the chips under Hot water and EV on Home energy, as a person sees them."""
    cards = view_cards(_view(config, "power-flow"))
    headings = [c for c in cards if c.get("heading") == "Hot water and EV"]
    return [badge["entity"] for c in headings for badge in c.get("badges", [])]


def _glance_entities(view: dict) -> set[str]:
    return {r["entity"] for c in view_cards(view) if c["type"] == "glance" for r in c["entities"]}


def _plan_cards(view: dict) -> list[dict]:
    """The planned heating cards of the Hot water view."""
    return [
        c
        for c in view_cards(view)
        if c["type"] == "markdown" and "'planned_heating'" in c["content"]
    ]


# ── what each combination shows ──────────────────────────────────────────────


@pytest.mark.parametrize("combination", COMBINATIONS, ids=_label)
class TestEveryCombination:
    def _seen(self, combination) -> dict:
        ev, switch, sensor = combination
        return seen_for(ev=ev, switch=switch, sensor=sensor)

    def test_the_device_chips_are_the_devices_present(self, combination):
        """The heater's chip shows only while it heats, so it is hidden here."""
        ev, switch, sensor = combination
        assert _device_chips(self._seen(combination)) == [
            *([IDS["immersion_water_temperature"]] if sensor else []),
            *([IDS["ev_charger_state"]] if ev else []),
        ]

    def test_the_heater_chip_shows_while_it_heats_with_the_switch(self, combination):
        ev, switch, sensor = combination
        config, brand = install(ev=ev, switch=switch, sensor=sensor)
        devices = installed_devices(config, ev_charger_found=brand is not None)
        states = states_with(devices, {IDS["immersion_power"]: "3000"} if switch else None)
        chips = _device_chips(seen(generated_for(ev=ev, switch=switch, sensor=sensor), states))
        assert (IDS["immersion_power"] in chips) == switch

    def test_the_devices_heading_shows_only_with_a_chip(self, combination):
        ev, switch, sensor = combination
        power_flow = _view(self._seen(combination), "power-flow")
        assert ("Hot water and EV" in _titles(power_flow)) == (ev or sensor)

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
        charts = [
            c
            for c in view_cards(_view(self._seen(combination), "immersion"))
            if c["type"] == "history-graph"
        ]
        plotted = [r["entity"] for c in charts for r in c["entities"]]
        assert (IDS["immersion_water_temperature"] in plotted) == sensor
        assert len(charts) == (1 if sensor else 0)

    def test_the_heater_cards_need_the_switch(self, combination):
        _, switch, _ = combination
        view = _view(self._seen(combination), "immersion")
        titles = _titles(view)
        for heading in ("Settings in force", "Last 7 days"):
            assert (heading in titles) == switch, heading
        figures = [
            [r["name"] for r in c["entities"]]
            for c in view_cards(view)
            if c["type"] == "glance" and IDS["immersion_today"] in yaml.safe_dump(c)
        ]
        assert figures == ([["Heater", "Heated", "Cost", "Solar saved"]] if switch else [])
        assert "Heater power" not in titles

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

    def test_the_temperature_settings_show_only_with_both_devices(self, combination):
        """Scheduled heating, the target and the minimum need a switch and a sensor."""
        _, switch, sensor = combination
        config = self._seen(combination)
        entities = _glance_entities(_view(config, "immersion"))
        for key in ("immersion_schedule", "immersion_target_temp", "immersion_min_temp"):
            assert (IDS[key] in entities) == (switch and sensor), key

    def test_the_plan_shows_only_with_both_devices_and_scheduled_heating_on(self, combination):
        _, switch, sensor = combination
        view = _view(self._seen(combination), "immersion")
        assert len(_plan_cards(view)) == (1 if switch and sensor else 0)
        assert ("Plan" in _titles(view)) == (switch and sensor)

    def test_the_plan_is_hidden_while_scheduled_heating_is_off(self, combination):
        ev, switch, sensor = combination
        config, brand = install(ev=ev, switch=switch, sensor=sensor)
        states = states_with(
            installed_devices(config, ev_charger_found=brand is not None),
            {IDS["immersion_schedule"]: "off"},
        )
        shown = seen(generated_for(ev=ev, switch=switch, sensor=sensor), states)
        assert _plan_cards(_view(shown, "immersion")) == []
        assert "Plan" not in _titles(_view(shown, "immersion"))

    def test_the_plan_reads_the_water_sensor_and_names_no_entity_that_is_missing(self, combination):
        _, switch, sensor = combination
        cards = _plan_cards(_view(self._seen(combination), "immersion"))
        text = " ".join(c["content"] for c in cards)
        both = switch and sensor
        assert (f"state_attr('{IDS['immersion_water_temperature']}', 'planned_heating')" in text) == both

    def test_the_settings_view_holds_the_controls_that_exist(self, combination):
        ev, switch, sensor = combination
        entities = _tile_entities(_view(self._seen(combination), "settings"))
        assert (IDS["auto_immersion"] in entities) == switch
        assert (IDS["immersion_managed"] in entities) == switch
        assert (IDS["immersion_target_temp"] in entities) == (switch and sensor)
        assert (IDS["immersion_schedule"] in entities) == (switch and sensor)

    def test_the_sources_bar_is_shown_whatever_the_devices(self, combination):
        today = _view(self._seen(combination), "today")
        assert "Where it came from" in _titles(today)

    def test_the_cost_split_lists_the_ev_and_immersion_costs_for_the_devices_present(self, combination):
        ev, switch, _ = combination
        cards = view_cards(_view(self._seen(combination), "today"))
        splits = [
            c for c in cards if c["type"] == "distribution" and IDS["house_cost_today"] in str(c)
        ]
        assert len(splits) == 1
        names = [r["name"] for r in splits[0]["entities"]]
        assert names == ["House", *(["EV"] if ev else []), *(["Hot water"] if switch else [])]

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
            c
            for c in view_cards(_view(self._seen(combination), "bill"))
            if c["type"] == "statistics-graph" and IDS["house_cost_today"] in str(c["entities"])
        ]
        assert len(graphs) == 1
        plotted = {row["entity"] for row in graphs[0]["entities"]}
        assert (IDS["zappi_cost_today"] in plotted) == ev
        assert (IDS["immersion_cost_today"] in plotted) == switch

    def test_the_views_that_never_depend_on_a_device_are_unchanged(self, combination):
        ev, switch, sensor = combination
        config = self._seen(combination)
        nothing = seen_for()
        for path in ("plan",):
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


def _states_with_schedule(combination, schedule: str) -> dict[str, str]:
    """The states of that device set. The schedule switch exists only with a switch and a sensor."""
    states = _states(combination)
    if IDS["immersion_schedule"] in states:
        states[IDS["immersion_schedule"]] = schedule
    return states


@pytest.mark.parametrize("schedule", ["on", "off"])
@pytest.mark.parametrize(
    ("first", "then"),
    [(a, b) for a in COMBINATIONS for b in COMBINATIONS if a != b],
    ids=lambda c: _label(c),
)
def test_a_file_follows_any_change_of_devices_whatever_scheduled_heating_does(
    first, then, schedule
):
    """The planned heating follows the switch of the new device set, in the old file."""
    stored = generated_for(ev=first[0], switch=first[1], sensor=first[2])
    regenerated = generated_for(ev=then[0], switch=then[1], sensor=then[2])
    states = _states_with_schedule(then, schedule)
    assert seen(stored, states) == seen(regenerated, states)
    ready = bool(_plan_cards(_view(seen(stored, states), "immersion")))
    assert ready == (then[1] and then[2] and schedule == "on")


def _figure_names(view: dict) -> list[str]:
    return [r["name"] for c in view_cards(view) if c["type"] == "glance" for r in c["entities"]]


def test_a_cylinder_sensor_added_later_shows_its_chart_in_the_old_file():
    stored = generated_for(switch=True)
    before = seen(stored, _states((False, True, False)))
    after = seen(stored, _states((False, True, True)))
    water = IDS["immersion_water_temperature"]
    charts = [c for c in view_cards(_view(before, "immersion")) if c["type"] == "history-graph"]
    assert charts == []
    charts = [c for c in view_cards(_view(after, "immersion")) if c["type"] == "history-graph"]
    assert [r["entity"] for r in charts[0]["entities"]][0] == water
    assert "Heat to" not in _figure_names(_view(before, "immersion"))
    assert "Heat to" in _figure_names(_view(after, "immersion"))
    assert "Scheduled" not in _figure_names(_view(before, "immersion"))
    assert "Scheduled" in _figure_names(_view(after, "immersion"))


# ── the oil advice tile ──────────────────────────────────────────────────────

OIL_SENTINEL = IDS["water_heating_cheapest_source"]


def _oil_section_cards(config: dict) -> list[dict]:
    """The cards of the Hot water view that read the oil advice, as a person would see them."""
    immersion = _view(config, "immersion")
    return [
        c
        for c in view_cards(immersion)
        if c["type"] == "markdown" and OIL_SENTINEL in c["content"]
    ]


@pytest.mark.parametrize("sensor", [False, True], ids=["no-sensor", "sensor"])
@pytest.mark.parametrize("ev", [False, True], ids=["no-ev", "ev"])
@pytest.mark.parametrize("switch", [False, True], ids=["no-switch", "switch"])
@pytest.mark.parametrize("oil", [False, True], ids=["no-oil", "oil"])
def test_the_oil_advice_shows_only_with_an_oil_price_and_the_switch(oil, switch, ev, sensor):
    shown = seen_for(ev=ev, switch=switch, sensor=sensor, oil=oil)
    assert bool(_oil_section_cards(shown)) == (oil and switch)


def test_the_oil_advice_reads_the_suggestion_and_the_schedule_of_the_oil_sensor():
    (card,) = _oil_section_cards(seen_for(switch=True, oil=True))
    assert f"state_attr('{OIL_SENTINEL}', 'suggestion')" in card["content"]
    assert f"state_attr('{OIL_SENTINEL}', 'alt_schedule_suggestion')" in card["content"]


def test_the_oil_advice_waits_for_its_sensor_in_a_file_made_without_one():
    stored = generated_for(switch=True)
    states = states_with({Device.IMMERSION_SWITCH})
    assert _oil_section_cards(seen(stored, states)) == []
    states = states_with({Device.IMMERSION_SWITCH, Device.ALTERNATIVE_HEAT})
    assert _oil_section_cards(seen(stored, states)) != []


def test_the_oil_advice_hides_while_the_sensor_is_unavailable():
    """With the price sensor unreadable and no saved number there is no advice to show."""
    stored = generated_for(switch=True, oil=True)
    devices = {Device.IMMERSION_SWITCH, Device.ALTERNATIVE_HEAT}
    states = states_with(devices, {OIL_SENTINEL: "unavailable"})
    assert _oil_section_cards(seen(stored, states)) == []


def test_the_oil_advice_goes_when_the_price_is_cleared_without_regenerating():
    stored = generated_for(switch=True, oil=True)
    states = states_with({Device.IMMERSION_SWITCH})
    assert _oil_section_cards(seen(stored, states)) == []


def test_the_oil_advice_sentinel_is_the_oil_sensor():
    assert SENTINELS[Device.ALTERNATIVE_HEAT] == "water_heating_cheapest_source"


# ── the conditions themselves ────────────────────────────────────────────────

DEVICE_ENTITY_IDS = {
    expected_entity_id(key): device for key, device in keys_needing_devices().items()
}


def _cards_with_their_conditions(nodes, inherited=()):
    """Every card of a section list, and every chip of a heading, paired with the visibility
    conditions above it."""
    for node in nodes:
        here = [*inherited, *node.get("visibility", [])]
        yield node, here
        yield from _cards_with_their_conditions(node.get("cards", []), here)
        yield from _cards_with_their_conditions(node.get("badges", []), here)


def _device_entities_named_by(card: dict) -> set[str]:
    """The entity IDs of ours that need a device, in the card apart from its own conditions
    and its chips, which are checked on their own."""
    text = yaml.safe_dump({k: v for k, v in card.items() if k not in ("visibility", "badges")})
    return {entity_id for entity_id in DEVICE_ENTITY_IDS if entity_id in text}


def _guarded_by(conditions: list[dict], device_name: str) -> bool:
    sentinel = expected_entity_id(SENTINELS[Device[device_name]])
    return sentinel in yaml.safe_dump(conditions)


# Cards that list many entities cannot hide one row. They are built once for each
# combination of devices, and the variants test below covers them.
_LISTS = ("custom:power-flow-card-plus", "entities", "statistics-graph", "history-graph")


def test_every_card_that_names_a_device_entity_is_hidden_without_that_device():
    """A card for the EV charger or the heater always sits under a condition on that device."""
    config = generated_for(ev=True, switch=True, sensor=True)
    unguarded = []
    for view in config["views"]:
        for section in view["sections"]:
            cards = _cards_with_their_conditions(section["cards"], section.get("visibility", []))
            for card, conditions in cards:
                if card["type"] in _LISTS:
                    continue
                for entity_id in _device_entities_named_by(card):
                    device = DEVICE_ENTITY_IDS[entity_id]
                    if not _guarded_by(conditions, device):
                        unguarded.append((view["path"], card.get("name"), entity_id))
    assert unguarded == []


def test_every_list_card_that_names_a_device_entity_carries_a_condition():
    """The cards that list entities are shown only for the right devices."""
    config = generated_for(ev=True, switch=True, sensor=True)
    for view in config["views"]:
        for section in view["sections"]:
            cards = _cards_with_their_conditions(section["cards"], section.get("visibility", []))
            for card, conditions in cards:
                if card["type"] in _LISTS and _device_entities_named_by(card):
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


# ── the planned heating and the oil advice in the Plan section ───────────────


def _plan_section_cards(config: dict) -> list[dict]:
    """The markdown cards of the Plan section of the Hot water view."""
    for section in _view(config, "immersion")["sections"]:
        headings = [c.get("heading") for c in section["cards"] if c["type"] == "heading"]
        if "Plan" in headings:
            return [c for c in section["cards"] if c["type"] == "markdown"]
    return []


def _oil_cards_in_plan(config: dict) -> list[dict]:
    return [c for c in _plan_section_cards(config) if OIL_SENTINEL in c["content"]]


@pytest.mark.parametrize("sensor", [False, True], ids=["no-sensor", "sensor"])
@pytest.mark.parametrize("switch", [False, True], ids=["no-switch", "switch"])
@pytest.mark.parametrize("oil", [False, True], ids=["no-oil", "oil"])
def test_the_plan_shows_the_oil_suggestion_only_with_an_oil_price_and_the_switch(
    oil, switch, sensor
):
    shown = seen_for(switch=switch, sensor=sensor, oil=oil)
    assert bool(_oil_cards_in_plan(shown)) == (oil and switch)


def test_the_planned_heating_card_prints_the_water_sensors_plan():
    cards = _plan_cards(_view(seen_for(switch=True, sensor=True), "immersion"))
    water = IDS["immersion_water_temperature"]
    assert [c["content"] for c in cards] == [
        f"{{% set p = state_attr('{water}', 'planned_heating') %}}"
        "{{ p or 'The planned heating shows once the water temperature is read.' }}"
    ]


def test_the_plan_keeps_only_the_planned_heating_without_an_oil_price():
    cards = _plan_section_cards(seen_for(switch=True, sensor=True))
    assert len(cards) == 1
    assert "'planned_heating'" in cards[0]["content"]


def _suggestion_homes(config: dict) -> list[str]:
    """The headings of the sections of the Hot water view that print the oil suggestion."""
    homes = []
    for section in _view(config, "immersion")["sections"]:
        printed = [
            c
            for c in section["cards"]
            if c["type"] == "markdown" and f"state_attr('{OIL_SENTINEL}', 'suggestion')" in c["content"]
        ]
        homes += [next(c["heading"] for c in section["cards"] if c["type"] == "heading")] * len(printed)
    return homes


def _oil_states(devices: set[Device], schedule: str) -> dict[str, str]:
    states = states_with(devices)
    if IDS["immersion_schedule"] in states:
        states[IDS["immersion_schedule"]] = schedule
    return states


ALL_OIL_DEVICES = {
    Device.IMMERSION_SWITCH,
    Device.IMMERSION_SENSOR,
    Device.IMMERSION_THERMOSTAT,
    Device.ALTERNATIVE_HEAT,
}


@pytest.mark.parametrize("schedule", ["on", "off"])
def test_the_oil_suggestion_shows_once_under_plan_whatever_scheduled_heating_does(schedule):
    stored = generated_for(switch=True, sensor=True, oil=True)
    assert _suggestion_homes(seen(stored, _oil_states(ALL_OIL_DEVICES, schedule))) == ["Plan"]


def test_the_oil_suggestion_shows_under_plan_while_scheduled_heating_cannot_exist():
    """With no temperature sensor there is no schedule switch and no planned heating."""
    stored = generated_for(switch=True, oil=True)
    devices = {Device.IMMERSION_SWITCH, Device.ALTERNATIVE_HEAT}
    assert _suggestion_homes(seen(stored, states_with(devices))) == ["Plan"]


def test_the_oil_suggestion_arrives_in_a_file_made_before_the_price_was_set():
    stored = generated_for(switch=True, sensor=True)
    before = states_with({Device.IMMERSION_SWITCH, Device.IMMERSION_SENSOR, Device.IMMERSION_THERMOSTAT})
    assert _oil_cards_in_plan(seen(stored, before)) == []
    after = states_with(
        {
            Device.IMMERSION_SWITCH,
            Device.IMMERSION_SENSOR,
            Device.IMMERSION_THERMOSTAT,
            Device.ALTERNATIVE_HEAT,
        }
    )
    assert _oil_cards_in_plan(seen(stored, after)) != []


def test_the_oil_suggestion_leaves_the_plan_when_the_price_is_cleared():
    stored = generated_for(switch=True, sensor=True, oil=True)
    devices = {Device.IMMERSION_SWITCH, Device.IMMERSION_SENSOR, Device.IMMERSION_THERMOSTAT}
    assert _oil_cards_in_plan(seen(stored, states_with(devices))) == []
