"""
cards.py - the colours, layout and card primitives the dashboard is built from.

A builder returns None, or an empty list, when its entity is unusable, so a view
never holds a card that points at nothing.
"""

from __future__ import annotations

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

# The flow card and the charts take hex colours, not the names the tiles use. These are the
# Home Assistant values of the names above.
HEX = {IMMERSION: "#FF9800", EV: "#009688"}

BAR = {"type": "bar-gauge", "min": 0, "max": 100}
SLIDER = {"type": "numeric-input", "style": "slider"}
TOGGLE = {"type": "toggle"}
TREND = {"type": "trend-graph", "hours_to_show": 24}

FULL = "full"
MAX_COLUMNS = 3


# ── Card primitives ──────────────────────────────────────────────────────────


def apex_config(height: int = 180) -> dict:
    return {
        "chart": {"height": height, "zoom": {"enabled": False}},
        "tooltip": {"shared": True, "followCursor": True},
        "stroke": {"curve": "smooth", "width": 2},
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
) -> dict | None:
    """A tile card, or None when the entity is unusable.

    Every tile is horizontal. Six columns of the 12 column section grid give two to a row.
    """
    if not entity:
        return None
    card: dict = {"type": "tile", "entity": entity, "name": name}
    if icon:
        card["icon"] = icon
    if color:
        card["color"] = color
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
    """A tile with an on/off switch beside the name."""
    return tile_card(entity, name, color=color, features=[TOGGLE], inline=True)


def slider_tile(entity: str | None, name: str, color: str) -> dict | None:
    """A full-width tile with a slider under the name."""
    return tile_card(entity, name, columns=FULL, color=color, features=[SLIDER])


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


def state_ref(entity: str) -> str:
    """The template that prints an entity's state."""
    return f"{{{{ states('{entity}') }}}}"


def state_markdown(entity: str | None) -> dict | None:
    """A markdown card that prints an entity's state, for sensors whose state is a sentence."""
    return markdown_card(state_ref(entity)) if entity else None


def view_config(title: str, icon: str, path: str, sections: list, **extra) -> dict:
    return {
        "title": title,
        "icon": icon,
        "path": path,
        "type": "sections",
        "max_columns": MAX_COLUMNS,
        **extra,
        "sections": present(sections),
    }


def graph_card(card: dict, rows: int = 4) -> dict:
    """Give a built-in graph the full width and a fixed height."""
    return {**card, "grid_options": {"columns": FULL, "rows": rows}}


def statistics_graph(rows: list, period: str, days: int) -> dict | None:
    """Bars of the change in each period, for sensors that reset every day.

    A history graph of such a sensor draws a sawtooth that falls to zero at midnight.
    The daily sensors keep long-term statistics, so the change per period is exact.
    """
    card = entity_list_card(
        rows,
        {"type": "statistics-graph"},
        chart_type="bar",
        period=period,
        days_to_show=days,
        stat_types=["change"],
    )
    return graph_card(card) if card else None


def entity_list_card(rows: list, head: dict, **tail) -> dict | None:
    """A card built from rows. None when no row points at an entity."""
    rows = present(rows)
    if not any("entity" in r for r in rows):
        return None
    return {**head, "entities": rows, **tail}
