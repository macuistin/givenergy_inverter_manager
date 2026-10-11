"""
charts.py - the immersion chart and the power flow card.

The immersion chart is a built-in history graph.
The power flow card needs power-flow-card-plus and has an entities card as its fallback.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cards import entity_list_card, entity_row, graph_card
from .hacs import POWER_FLOW_CARD

# ── Immersion chart ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImmersionEntities:
    """The entities the immersion chart draws. A None entity leaves its series out.

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
