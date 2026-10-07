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
)
from .hacs import APEX_CARD, POWER_FLOW_CARD

# ── Immersion charts ─────────────────────────────────────────────────────────

_TEMP_AXIS = "temp"
_HEATER_AXIS = "heater"


@dataclass(frozen=True)
class ImmersionEntities:
    """The entities one immersion chart draws. A None entity leaves its series out.

    The heater is the power sensor of the immersion switch. Its power is a fixed number, so
    the chart shows only whether it is on.
    """

    temp_sensor: str | None
    target: str | None
    minimum: str | None
    heater: str | None


def builtin_immersion_chart(ent: ImmersionEntities) -> dict | None:
    """A built-in history graph of the temperatures, and the heater's power when it is known.

    It draws the heater as a line of watts, not as a shaded band.
    """
    card = entity_list_card(
        [
            entity_row(ent.temp_sensor, "Water"),
            entity_row(ent.target, "Target"),
            entity_row(ent.minimum, "Minimum"),
            entity_row(ent.heater, "Heater power"),
        ],
        {"type": "history-graph"},
        hours_to_show=12,
    )
    return graph_card(card) if card else None


def _apex_series(entity: str | None, name: str, color: str, width: int) -> dict | None:
    if not entity:
        return None
    return {
        "entity": entity,
        "name": name,
        "color": color,
        "stroke_width": width,
        "curve": "smooth",
        "yaxis_id": _TEMP_AXIS,
    }


def _apex_heater_series(entity: str | None) -> dict | None:
    """The heater as a pale band that is there while it is on and gone while it is off."""
    if not entity:
        return None
    return {
        "entity": entity,
        "name": "Heater on",
        "type": "area",
        "curve": "stepline",
        "color": "#ff8a80",
        "opacity": 0.15,
        "stroke_width": 0,
        "yaxis_id": _HEATER_AXIS,
        "transform": "return x > 0 ? 1 : 0;",
        "show": {"in_header": False, "legend_value": False},
    }


def _apex_axes(ent: ImmersionEntities) -> list[dict]:
    """One axis for each kind of series drawn. The heater's is fixed and hidden."""
    temperature = {"id": _TEMP_AXIS, "decimals": 0}
    heater = {"id": _HEATER_AXIS, "min": 0, "max": 1, "decimals": 0, "show": False}
    return [*([temperature] if ent.temp_sensor else []), *([heater] if ent.heater else [])]


def apex_immersion_chart(ent: ImmersionEntities) -> dict | None:
    """12 hours of the water temperature with the heater shaded while it is on.

    Without a temperature sensor it holds the heater band only.
    """
    # Same orange as the immersion tiles. Lower case keeps the generated file unchanged.
    orange = HEX[IMMERSION].lower()
    series = present(
        [
            _apex_series(ent.temp_sensor, "Water", "#03a9f4", 2),
            _apex_series(ent.target, "Target", "#f44336", 1),
            _apex_series(ent.minimum, "Minimum", orange, 1),
            _apex_heater_series(ent.heater),
        ]
    )
    if not series:
        return None
    return {
        "type": APEX_CARD.card_type,
        "header": {"show": False},
        "graph_span": "12h",
        "yaxis": _apex_axes(ent),
        "apex_config": {**apex_config(), "legend": {"show": True, "position": "bottom"}},
        "series": series,
        "grid_options": {"columns": FULL},
    }


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
