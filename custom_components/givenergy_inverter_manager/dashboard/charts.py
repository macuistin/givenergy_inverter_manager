"""
charts.py - the immersion chart and the power flow card.

The immersion chart is a built-in history graph.
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

# ── Immersion chart ──────────────────────────────────────────────────────────

_ROWS_TEMPERATURE = 5
_ROWS_WITH_HEATER = 9


_TEMP_AXIS = "temp"
_HEATER_AXIS = "heater"


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
    # The graph draws the temperatures in degrees and the heater in watts as two charts, one
    # above the other. Each needs about four grid rows, or the axis labels run into each other.
    if not card:
        return None
    return graph_card(card, _ROWS_WITH_HEATER if ent.heater else _ROWS_TEMPERATURE)


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


# Solcast publishes tomorrow's forecast as one entry per half hour, with a typical and a low
# (10th percentile) estimate in kW. apexcharts-card draws them from the attribute itself.
_FORECAST_POINTS = (
    "return (entity.attributes.detailedForecast || []).map("
    "p => [new Date(p.period_start).getTime(), p.{key}]);"
)


def apex_solar_forecast_chart(forecast: str) -> dict:
    """Tomorrow's solar through the day: the typical forecast as an area, a dull day as a line."""

    def series(name: str, key: str, color: str, kind: str) -> dict:
        return {
            "entity": forecast,
            "name": name,
            "type": kind,
            "color": color,
            "stroke_width": 2,
            "curve": "smooth",
            "show": {"legend_value": False},
            "data_generator": _FORECAST_POINTS.format(key=key),
        }

    typical = {**series("Forecast", "pv_estimate", "#ff9800", "area"), "opacity": 0.35}
    return {
        "type": "custom:apexcharts-card",
        "graph_span": "24h",
        "span": {"start": "day", "offset": "+1d"},
        "header": {"show": False},
        "apex_config": {"chart": {"height": 220}, "legend": {"show": True}},
        "yaxis": [{"min": 0, "decimals": 1, "apex_config": {"title": {"text": "kW"}}}],
        "series": [typical, series("Dull day", "pv_estimate10", "#ffcc80", "line")],
        "grid_options": {"columns": "full"},
    }


@dataclass(frozen=True)
class TodayChartEntities:
    """What the Today chart draws: today's half-hourly forecast, the live solar power, the hours.

    *hours* is the first and last hour on the clock to show, the producing hours with a buffer.
    """

    forecast: str
    solar_power: str
    hours: tuple[int, int]


def _forecast_line(entity: TodayChartEntities, name: str, key: str, **style) -> dict:
    return {
        "entity": entity.forecast,
        "name": name,
        "type": "line",
        "curve": "smooth",
        "show": {"legend_value": False},
        "data_generator": _FORECAST_POINTS.format(key=key),
        **style,
    }


def apex_solar_today_chart(ent: TodayChartEntities) -> dict:
    """Today's solar as predicted and as produced, over the producing hours.

    The forecast is a dashed line with the low and high estimates either side. The solar power
    sensor is drawn as an area, in kW, averaged over each half hour like the forecast.
    """
    first, last = ent.hours
    produced = {
        "entity": ent.solar_power,
        "name": "Produced",
        "type": "area",
        "color": "#ff9800",
        "opacity": 0.45,
        "stroke_width": 2,
        "curve": "smooth",
        "extend_to": "now",
        "transform": "return x / 1000;",
        "group_by": {"func": "avg", "duration": "30min"},
        "show": {"legend_value": False},
    }
    span = {"start": "day", **({"offset": f"+{first}h"} if first else {})}
    return {
        "type": APEX_CARD.card_type,
        "graph_span": f"{last - first}h",
        "span": span,
        "header": {"show": False},
        "now": {"show": True, "label": "Now"},
        "apex_config": {"chart": {"height": 240}, "legend": {"show": True}},
        "yaxis": [{"min": 0, "decimals": 1, "apex_config": {"title": {"text": "kW"}}}],
        "series": [
            _forecast_line(ent, "High", "pv_estimate90", color="#90caf9", stroke_width=1),
            _forecast_line(
                ent, "Predicted", "pv_estimate", color="#42a5f5", stroke_width=2, stroke_dash=4
            ),
            _forecast_line(ent, "Low", "pv_estimate10", color="#90caf9", stroke_width=1),
            produced,
        ],
        "grid_options": {"columns": FULL},
    }
