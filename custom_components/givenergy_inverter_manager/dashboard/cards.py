"""
cards.py - the colours, layout and card primitives the dashboard is built from.

A builder returns None, or an empty list, when its entity is unusable, so a view
never holds a card that points at nothing.
"""

from __future__ import annotations

from typing import Any

# ── Colours ──────────────────────────────────────────────────────────────────
# A few, used the same way on every view: amber for solar, green for the battery,
# blue for the grid and money, orange for the immersion, teal for the EV charger and indigo
# for the night.
SOLAR = "amber"
BATTERY = "green"
GRID = "blue"
IMMERSION = "orange"
EV = "teal"
NIGHT = "indigo"

# The flow card takes hex colours, not the names the tiles use. These are the Home Assistant
# values of the names above.
HEX = {IMMERSION: "#FF9800", EV: "#009688"}

BAR = {"type": "bar-gauge", "min": 0, "max": 100}
# A setting is set with − and + buttons. A slider across the whole tile is hard to set to an
# exact value such as 45 °C or 25%.
STEPPER = {"type": "numeric-input", "style": "buttons"}
TOGGLE = {"type": "toggle"}
TREND = {"type": "trend-graph", "hours_to_show": 24}

FULL = "full"
MAX_COLUMNS = 3
# A section this wide holds the power flow, and one as wide as the view holds a chart or a
# banner. Home Assistant narrows a span to the columns the screen has, so a phone still shows
# one column.
WIDE = {"column_span": 2}
WHOLE_WIDTH = {"column_span": MAX_COLUMNS}


# ── Card primitives ──────────────────────────────────────────────────────────


def apex_config(height: int = 180) -> dict:
    """The apexcharts options shared by the charts.

    It sets no stroke. A global stroke curve or width overrides the per-series ones, so each
    series carries its own stroke_width and curve.
    """
    return {
        "chart": {"height": height, "zoom": {"enabled": False}},
        "tooltip": {"shared": True, "followCursor": True},
        "markers": {"size": 0, "hover": {"size": 5}},
        "legend": {"show": False},
    }


def present(items: list) -> list:
    return [item for item in items if item is not None]


def entity_row(entity: str | None, name: str, **extra) -> dict | None:
    """An entities-card row, or None when the entity is unusable."""
    if not entity:
        return None
    return {"entity": entity, "name": name, **extra}


def navigate_action(path: str) -> dict:
    """A tap action that opens another view of the same dashboard.

    The path is relative, so it works whatever URL the dashboard is served from.
    """
    return {"action": "navigate", "navigation_path": path}


def admin_condition(admin_ids: tuple[str, ...]) -> dict[str, Any]:
    """A visibility condition that is met only by these Home Assistant users."""
    return {"condition": "user", "users": list(admin_ids)}


def button_badge(
    icon: str, text: str, nav: dict[str, Any], visibility: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """A small button in a heading. With visibility, only the users it names see it."""
    badge: dict[str, Any] = {"type": "button", "icon": icon, "text": text, "tap_action": nav}
    if visibility:
        badge["visibility"] = visibility
    return badge


def _given(options: dict[str, Any]) -> dict[str, Any]:
    """The options that were given: those with a value."""
    return {key: value for key, value in options.items() if value}


def tile_card(  # noqa: PLR0913
    entity: str | None,
    name: str,
    *,
    columns: int | str = 6,
    color: str | None = None,
    icon: str | None = None,
    features: list | None = None,
    inline: bool = False,
    nav: dict | None = None,
    rows: int | None = None,
    state_content: list[str] | None = None,
) -> dict | None:
    """A tile card, or None when the entity is unusable.

    Every tile is horizontal. Six columns of the 12 column section grid give two to a row.
    """
    if not entity:
        return None
    card: dict = {"type": "tile", "entity": entity, "name": name}
    card.update(_given({"icon": icon, "color": color, "state_content": state_content}))
    if features:
        card["features"] = features
        if inline:
            card["features_position"] = "inline"
    if nav:
        card["tap_action"] = nav
        card["icon_tap_action"] = nav
    grid: dict = {"columns": columns}
    if rows:
        grid["rows"] = rows
    card["grid_options"] = grid
    return card


def toggle_tile(entity: str | None, name: str, color: str) -> dict | None:
    """A tile with an on/off switch beside the name, the full width of its section.

    Home Assistant gives a tile with an inline feature at least 12 columns, so it says so.
    """
    return tile_card(entity, name, columns=FULL, color=color, features=[TOGGLE], inline=True)


def readonly_tile(entity: str | None, name: str, color: str) -> dict[str, Any] | None:
    """A tile that shows a switch or number and does nothing when tapped.

    A tile toggles a switch when its icon is tapped. Tapping this one does nothing, so the
    value can be read but not changed from the tile.
    """
    return tile_card(entity, name, color=color, nav={"action": "none"})


def stepper_tile(entity: str | None, name: str, color: str, columns: int | str = 6) -> dict | None:
    """A tile with − and + buttons under the name, two to a row unless given the full width."""
    return tile_card(entity, name, columns=columns, color=color, features=[STEPPER])


def heading_card(
    text: str,
    icon: str | None = None,
    nav: dict | None = None,
    badges: list | None = None,
) -> dict:
    """A section heading. With nav it shows a chevron and opens the view."""
    card: dict = {"type": "heading", "heading": text, "heading_style": "title"}
    if icon:
        card["icon"] = icon
    if badges:
        card["badges"] = badges
    if nav:
        card["tap_action"] = nav
    return card


def subheading_card(text: str, icon: str | None = None) -> dict:
    """A heading one step down, for a question under a section."""
    return {**heading_card(text, icon), "heading_style": "subtitle"}


def heading_block(heading: dict, cards: list) -> list:
    """A heading and its cards. Empty when there are no cards, so no lone heading is left."""
    cards = present(cards)
    return [heading, *cards] if cards else []


def grid_section(*blocks: list, **extra) -> dict | None:
    """A section of the sections view. None when it would hold no cards."""
    cards = [card for block in blocks for card in block]
    if not cards:
        return None
    return {"type": "grid", **extra, "cards": cards}


def group(heading: dict, cards: list, **extra) -> dict | None:
    """A section that holds one heading and its cards."""
    return grid_section(heading_block(heading, cards), **extra)


def markdown_card(content: str) -> dict:
    return {"type": "markdown", "content": content, "grid_options": {"columns": FULL}}


def state_ref(entity: str, full_text_attribute: str | None = None) -> str:
    """The template that prints an entity's state.

    A sentence sensor cuts its state to Home Assistant's 255 character limit and keeps the whole
    text in an attribute. Naming that attribute prints it, and falls back to the state while it
    is absent, as on an install of an earlier version.
    """
    if full_text_attribute is None:
        return f"{{{{ states('{entity}') }}}}"
    return f"{{{{ state_attr('{entity}', '{full_text_attribute}') or states('{entity}') }}}}"


def state_markdown(entity: str | None, full_text_attribute: str | None = None) -> dict | None:
    """A markdown card that prints an entity's state, for sensors whose state is a sentence."""
    return markdown_card(state_ref(entity, full_text_attribute)) if entity else None


def attribute_markdown(entity: str | None, attribute: str) -> dict | None:
    """A markdown card that prints one attribute of an entity, for a sentence kept there."""
    if not entity:
        return None
    return markdown_card(f"{{{{ state_attr('{entity}', '{attribute}') }}}}")


def view_config(title: str, icon: str, path: str, sections: list, **extra) -> dict:
    return {
        "title": title,
        "icon": icon,
        "path": path,
        "type": "sections",
        "max_columns": MAX_COLUMNS,
        # A section that fits a gap left by a wider one moves up into it, so the power flow
        # sits beside Now even while a view-wide banner follows Now.
        "dense_section_placement": True,
        **extra,
        "sections": present(sections),
    }


def graph_card(card: dict, rows: int = 4) -> dict:
    """Give a built-in graph the full width and a fixed height."""
    return {**card, "grid_options": {"columns": FULL, "rows": rows}}


def statistics_graph(rows: list, period: str, days: int, height: int = 4) -> dict | None:
    """Bars of the change in each period, for sensors that reset every day.

    A history graph of such a sensor draws a sawtooth that falls to zero at midnight.
    The daily sensors keep long-term statistics, so the change per period is exact.
    *height* is the number of grid rows the graph takes.
    """
    card = entity_list_card(
        rows,
        {"type": "statistics-graph"},
        chart_type="bar",
        period=period,
        days_to_show=days,
        stat_types=["change"],
    )
    return graph_card(card, height) if card else None


def stacked_hourly_graph(rows: list, height: int) -> dict | None:
    """Stacked bars of the energy each hour over the last day, one colour per row."""
    card = entity_list_card(
        rows,
        {"type": "statistics-graph"},
        chart_type="bar-stack",
        period="hour",
        days_to_show=1,
        stat_types=["change"],
    )
    return graph_card(card, height) if card else None


def logbook_card(entities: list[str | None], hours: int) -> dict | None:
    """What changed these entities lately, newest first. None when none of them exists."""
    present_ids = [entity for entity in entities if entity]
    if not present_ids:
        return None
    return {
        "type": "logbook",
        "target": {"entity_id": present_ids},
        "hours_to_show": hours,
        "grid_options": {"columns": FULL},
    }


def entity_list_card(rows: list, head: dict, **tail) -> dict | None:
    """A card built from rows. None when no row points at an entity."""
    rows = present(rows)
    if not any("entity" in r for r in rows):
        return None
    return {**head, "entities": rows, **tail}


# ── Story layout cards ───────────────────────────────────────────────────────
# The colours of the power flow card, so a chart says solar, battery and grid in the colours the
# flow uses. Home Assistant draws a series in the colour given only from 2026.6, so the builder
# passes them only on a release that has it (HostFacts.series_colours).
SOLAR_HEX = "#ff9800"
BATTERY_HEX = "#4db6ac"
GRID_HEX = "#9575cd"
HOUSE_HEX = "#29b6f6"
WATER_HEX = "#ff7043"
COST_HEX = "#9575cd"

# The style a table takes when card-mod is installed: no grid, a light line between rows, small
# headings, the total in bold. Without card-mod a table keeps Home Assistant's own style.
TABLE_CSS = (
    "table { width: 100%; border-collapse: collapse; border: none;"
    " font-variant-numeric: tabular-nums; }\n"
    "th, td { border: none !important; padding: 7px 6px; }\n"
    "tr { border-bottom: 1px solid var(--divider-color); }\n"
    "tr:last-child { border-bottom: none; }\n"
    "th { color: var(--secondary-text-color); font-weight: 500; font-size: 12px;"
    " text-transform: uppercase; letter-spacing: 0.04em; vertical-align: bottom; }\n"
    "td:first-child, th:first-child { padding-left: 0; }\n"
    "td:last-child, th:last-child { padding-right: 0; }\n"
    "p { color: var(--secondary-text-color); font-size: 13px; }\n"
)
# A total row: bold, a rule above it, and the saving in green.
TOTAL_CSS = (
    "tr:last-child td { font-weight: 700; border-top: 2px solid var(--primary-text-color); }\n"
    "tr:last-child td:last-child { color: var(--success-color, #43a047); }\n"
)
# A small grey title on a chart that shares a row with another.
CHART_TITLE_CSS = (
    "ha-card .card-header { font-size: 14px; font-weight: 500;"
    " color: var(--secondary-text-color); padding: 12px 16px 0; }"
)


def entity_badge(  # noqa: PLR0913
    entity: str | None,
    icon: str,
    *,
    color: str | None = None,
    nav: dict | None = None,
    state_content: list[str] | None = None,
    visibility: list[dict] | None = None,
) -> dict | None:
    """A small chip in a heading that shows an entity's state. None without the entity."""
    if not entity:
        return None
    badge: dict[str, Any] = {
        "type": "entity",
        "entity": entity,
        "show_state": True,
        "show_icon": True,
        "icon": icon,
    }
    badge.update(_given({"color": color, "state_content": state_content}))
    if nav:
        badge["tap_action"] = nav
    if visibility:
        badge["visibility"] = visibility
    return badge


def glance_card(rows: list) -> dict | None:
    """Up to five figures in one row, a name over each value, with no icons.

    The rows are entity rows. None when no row has an entity.
    """
    rows = present(rows)
    if not rows:
        return None
    return {
        "type": "glance",
        "columns": len(rows),
        "show_icon": False,
        "state_color": False,
        "entities": rows,
        "grid_options": {"columns": FULL},
    }


def distribution_card(rows: list) -> dict | None:
    """One bar split into the share of each row, with its value under it. None without rows."""
    card = entity_list_card(rows, {"type": "distribution"})
    return {**card, "grid_options": {"columns": FULL}} if card else None


def shortcut_card(label: str, icon: str, nav: dict | None, **extra) -> dict | None:
    """A button that opens another view. None when the view it opens is left out."""
    if nav is None:
        return None
    card: dict[str, Any] = {
        "type": "shortcut",
        "label": label,
        "icon": icon,
        "tap_action": nav,
        "grid_options": {"columns": 4},
    }
    card.update(extra)
    return card


def switch_tile(entity: str | None, name: str, color: str) -> dict | None:
    """A switch two to a row, turned on or off by tapping it."""
    card = tile_card(entity, name, color=color)
    if card is None:
        return None
    toggle = {"action": "toggle"}
    return {**card, "tap_action": toggle, "icon_tap_action": toggle}


def stepper_row(entity: str | None, name: str, color: str) -> dict | None:
    """A number with − and + buttons beside its name, the full width of the section."""
    return tile_card(entity, name, columns=FULL, color=color, features=[STEPPER], inline=True)


def bar_tile(entity: str | None, name: str, color: str) -> dict | None:
    """A percentage as a bar beside its name, the full width of the section."""
    return tile_card(entity, name, columns=FULL, color=color, features=[BAR], inline=True)


def day_bars(rows: list, days: int, height: int = 3, title: str | None = None) -> dict | None:
    """Bars of each day for one or two series, with no legend.

    One series needs no legend, and the frontend would name it "Energy (change)". A chart that
    shares a row with another carries a small title instead.
    """
    card = statistics_graph(rows, "day", days, height)
    if card is None:
        return None
    card = {**card, "hide_legend": len(present(rows)) == 1}
    return {**card, "title": title} if title else card


def stacked_daily_graph(rows: list, days: int, height: int) -> dict | None:
    """Stacked bars of each day, one colour per row, for parts that add up to a whole."""
    card = entity_list_card(
        rows,
        {"type": "statistics-graph"},
        chart_type="bar-stack",
        period="day",
        days_to_show=days,
        stat_types=["change"],
    )
    return graph_card(card, height) if card else None


def history_graph(rows: list, hours: int, height: int) -> dict | None:
    """A line of each row over the last hours, for values that do not reset at midnight."""
    card = entity_list_card(rows, {"type": "history-graph"}, hours_to_show=hours)
    return graph_card(card, height) if card else None


def weather_card(entity: str | None) -> dict | None:
    """The daily forecast for the next few days. None without a weather entity."""
    if not entity:
        return None
    return {
        "type": "weather-forecast",
        "entity": entity,
        "forecast_type": "daily",
        "show_current": False,
        "show_forecast": True,
        "grid_options": {"columns": FULL},
    }


def styled(card: dict | None, css: str, *, inner: bool = False) -> dict | None:
    """The card with card-mod styling. inner styles the markdown inside a markdown card."""
    if card is None:
        return None
    style: Any = {"ha-markdown $": css, ".": ""} if inner else css
    return {**card, "card_mod": {"style": style}}
