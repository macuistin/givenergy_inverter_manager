"""
charts.py - the immersion charts and the power flow card.

The immersion charts use apexcharts-card when it is installed and built-in cards when not.
The power flow card needs power-flow-card-plus and has an entities card as its fallback.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cards import (
    FULL,
    HEX,
    IMMERSION,
    apex_config,
    entity_list_card,
    entity_row,
    graph_card,
    present,
    statistics_graph,
)
from .hacs import APEX_CARD, POWER_FLOW_CARD

# ── Immersion charts ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImmersionEntities:
    """The entities the immersion charts draw."""

    temp_sensor: str
    target: str | None
    minimum: str | None
    energy_today: str | None
    power: str | None


def builtin_immersion_charts(ent: ImmersionEntities) -> tuple[list, list]:
    """Built-in cards: a history graph of the temperatures and energy per hour."""
    temps = entity_list_card(
        [
            entity_row(ent.temp_sensor, "Water"),
            entity_row(ent.target, "Target"),
            entity_row(ent.minimum, "Minimum"),
        ],
        {"type": "history-graph"},
        hours_to_show=12,
    )
    energy = statistics_graph([entity_row(ent.energy_today, "Immersion")], "hour", 1)
    return ([graph_card(temps)] if temps else []), present([energy])


def _apex_series(entity: str | None, name: str, color: str, width: int) -> dict | None:
    if not entity:
        return None
    return {"entity": entity, "name": name, "color": color, "stroke_width": width}


def _apex_temperature_chart(ent: ImmersionEntities, orange: str) -> dict:
    """12 hours of the water temperature, with the target and minimum."""
    return {
        "type": APEX_CARD.card_type,
        "header": {"show": False},
        "graph_span": "12h",
        "apex_config": {**apex_config(), "legend": {"show": True, "position": "bottom"}},
        "series": present(
            [
                _apex_series(ent.temp_sensor, "Water", "#03a9f4", 2),
                _apex_series(ent.target, "Target", "#f44336", 1),
                _apex_series(ent.minimum, "Minimum", orange, 1),
            ]
        ),
        "grid_options": {"columns": FULL},
    }


def _apex_power_chart(power: str, orange: str) -> dict:
    """12 hours of the immersion's power, as a step chart."""
    return {
        "type": APEX_CARD.card_type,
        "header": {"show": False},
        "graph_span": "12h",
        "yaxis": [{"min": 0}],
        "apex_config": {**apex_config(), "stroke": {"curve": "stepline", "width": 2}},
        "series": [_apex_series(power, "Power", orange, 2)],
        "grid_options": {"columns": FULL},
    }


def apex_immersion_charts(ent: ImmersionEntities) -> tuple[list, list]:
    """apexcharts cards: the temperature chart, and the power chart when there is a sensor."""
    # Same orange as the immersion tiles. Lower case keeps the generated file unchanged.
    orange = HEX[IMMERSION].lower()
    power = [_apex_power_chart(ent.power, orange)] if ent.power else []
    return [_apex_temperature_chart(ent, orange)], power


# ── Content helpers ──────────────────────────────────────────────────────────


def flow_card(flow: dict) -> dict:
    """The power-flow-card-plus card for these flow entities."""
    return {
        "type": POWER_FLOW_CARD.card_type,
        "entities": flow,
        "min_flow_rate": 0.75,
        "max_flow_rate": 6,
        "display_zero_lines": {
            "mode": "transparency",
            "transparency": 75,
            "grey_color": [189, 189, 189],
        },
        "allow_layout_break": False,
        "kilo_threshold": 1000,
        "base_decimals": 0,
        "kilo_decimals": 1,
        "disable_dots": False,
        "clickable_entities": True,
        "no_labels": False,
    }


def flow_fallback(flow: dict) -> dict | None:
    """An entities card with the power flow values, for when power-flow-card-plus is missing."""
    battery = flow.get("battery", {})
    rows = [
        entity_row(flow.get("solar", {}).get("entity"), "Solar", icon="mdi:solar-power"),
        entity_row(battery.get("entity"), "Battery power", icon="mdi:home-battery"),
        entity_row(battery.get("state_of_charge"), "Battery charge"),
        entity_row(flow.get("grid", {}).get("entity"), "Grid", icon="mdi:transmission-tower"),
        entity_row(flow.get("home", {}).get("entity"), "Home", icon="mdi:home"),
        *(entity_row(i["entity"], i["name"], icon=i["icon"]) for i in flow.get("individual", [])),
    ]
    return entity_list_card(rows, {"type": "entities"})
