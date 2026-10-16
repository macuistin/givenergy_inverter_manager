"""
dashboard_visibility.py - what a person sees on a generated dashboard.

The generator hides the cards of a missing device with Lovelace visibility conditions, so the
generated config holds cards that are not on screen. This module plays the part of the
Lovelace frontend: it evaluates the conditions against a map of entity states and drops
what they hide. A test that asks "does the dashboard show X" asserts on that result.

It follows the frontend's rule for a state condition: an entity with no state counts as
"unavailable".
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

import yaml

from custom_components.givenergy_inverter_manager.const import (
    CONF_ALT_HEAT_COST,
    CONF_ALT_HEAT_ENABLED,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
)
from custom_components.givenergy_inverter_manager.core.devices import Device
from tests.dashboard_support import (
    ADMIN_ID,
    FULL_CONFIG,
    dashboard_dict,
    default_entity_ids,
    devices_of,
    keys_without_devices,
)

UNAVAILABLE = "unavailable"
_ALL_IDS = default_entity_ids()


def states_with(devices: Iterable[Device], extra: dict[str, str] | None = None) -> dict[str, str]:
    """The entity states of an install that has exactly these devices.

    Every entity of ours that Home Assistant would create has a state. The ones that need
    a device not in *devices* do not exist, so they have none.
    """
    missing = keys_without_devices(frozenset(devices))
    states = {entity_id: "on" for key, entity_id in _ALL_IDS.items() if key not in missing}
    states[_ALL_IDS["dry_run_active"]] = "False"
    return {**states, **(extra or {})}


def condition_holds(condition: dict[str, Any], states: dict[str, str], user: str = ADMIN_ID) -> bool:
    """Evaluate one Lovelace visibility condition the way the frontend does."""
    kind = condition["condition"]
    if kind == "user":
        return user in condition["users"]
    if kind == "or":
        return any(condition_holds(c, states, user) for c in condition["conditions"])
    if kind == "and":
        return all(condition_holds(c, states, user) for c in condition["conditions"])
    state = states.get(condition["entity"], UNAVAILABLE)
    if kind == "numeric_state":
        return _numeric_holds(condition, state)
    assert kind == "state", f"the test double does not know the {kind} condition"
    if "state" in condition:
        return state in _as_list(condition["state"])
    return state not in _as_list(condition["state_not"])


def _numeric_holds(condition: dict[str, Any], state: str) -> bool:
    """The frontend's numeric_state: false for a state that is not a number."""
    try:
        value = float(state)
    except ValueError:
        return False
    if "above" in condition and not value > float(condition["above"]):
        return False
    return not ("below" in condition and not value < float(condition["below"]))


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else [value]


def _shown(node: dict[str, Any], states: dict[str, str]) -> bool:
    return all(condition_holds(c, states) for c in node.get("visibility", []))


def _prune_badges(badges: list[dict], states: dict[str, str]) -> list[dict]:
    """The badges of a heading that show, as the frontend draws them."""
    kept = []
    for badge in badges:
        if _shown(badge, states):
            kept.append({k: v for k, v in badge.items() if k != "visibility"})
    return kept


def _prune_cards(cards: list[dict], states: dict[str, str]) -> list[dict]:
    kept = []
    for card in cards:
        if not _shown(card, states):
            continue
        card = copy.deepcopy(card)
        card.pop("visibility", None)
        if "cards" in card:
            card["cards"] = _prune_cards(card["cards"], states)
        if "badges" in card:
            card["badges"] = _prune_badges(card["badges"], states)
        kept.append(card)
    return kept


def _prune_section(section: dict, states: dict[str, str]) -> dict | None:
    if not _shown(section, states):
        return None
    cards = _prune_cards(section["cards"], states)
    # A heading with nothing under it is the "no lone heading" rule the generator keeps. A
    # heading that shows chips is not alone.
    if not [c for c in cards if c.get("type") != "heading" or c.get("badges")]:
        return None
    return {k: v for k, v in section.items() if k != "visibility"} | {"cards": cards}


def seen(config: dict, states: dict[str, str]) -> dict:
    """The dashboard with every hidden section and card removed, and the empty views too."""
    pruned = copy.deepcopy(config)
    views = []
    for view in pruned["views"]:
        sections = [_prune_section(s, states) for s in view["sections"]]
        view["sections"] = [s for s in sections if s]
        views.append(view)
    return {"views": views}


def seen_text(config: dict, states: dict[str, str]) -> str:
    """The seen dashboard as YAML, for assertions on which entity IDs and names show."""
    return yaml.safe_dump(seen(config, states), sort_keys=False)


def install(
    *, ev: bool = False, switch: bool = False, sensor: bool = False, oil: bool = False
) -> tuple[dict, str | None]:
    """The config and discovered charger of an install with some of the optional devices.

    oil turns alternative heating on with a cost, which makes its advice a device only together
    with the switch.
    """
    config = {
        k: v
        for k, v in FULL_CONFIG.items()
        if k not in (CONF_IMMERSION_SWITCH, CONF_IMMERSION_TEMP_SENSOR)
    }
    if switch:
        config[CONF_IMMERSION_SWITCH] = FULL_CONFIG[CONF_IMMERSION_SWITCH]
    if sensor:
        config[CONF_IMMERSION_TEMP_SENSOR] = FULL_CONFIG[CONF_IMMERSION_TEMP_SENSOR]
    if oil:
        config[CONF_ALT_HEAT_ENABLED] = True
        config[CONF_ALT_HEAT_COST] = 0.95
    return config, ("myenergi" if ev else None)


def generated_for(
    *, ev: bool = False, switch: bool = False, sensor: bool = False, oil: bool = False, **kw
) -> dict:
    """The generated dashboard for an install with some of the optional devices."""
    config, brand = install(ev=ev, switch=switch, sensor=sensor, oil=oil)
    return dashboard_dict(config, ev_brand=brand, **kw)


def seen_for(
    *, ev: bool = False, switch: bool = False, sensor: bool = False, oil: bool = False, **kw
) -> dict:
    """What that install's dashboard shows, with every hidden section and card removed."""
    config, brand = install(ev=ev, switch=switch, sensor=sensor, oil=oil)
    generated = dashboard_dict(config, ev_brand=brand, **kw)
    return seen(generated, states_with(devices_of(config, brand)))


def shown_text(config: dict | None = None, registry=None, *, ev_brand: str | None = "myenergi", **kw) -> str:
    """The YAML of what an install with this config and discovered charger shows."""
    config = FULL_CONFIG if config is None else config
    generated = dashboard_dict(config, registry, ev_brand=ev_brand, **kw)
    return seen_text(generated, states_with(devices_of(config, ev_brand)))
