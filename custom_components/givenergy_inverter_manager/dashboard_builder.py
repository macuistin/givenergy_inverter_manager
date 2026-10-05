"""
dashboard_builder.py - builds the Lovelace dashboard for GivEnergy Inverter Manager.

The dashboard is built as a plain dict, then serialised with PyYAML. The
get_dashboard_yaml service writes the YAML to a file.

The generated dashboard has five tabs, all of the "sections" view type. Each section starts
with a heading card and holds native tile cards:
  1. Power Flow   - a Now section (charge, night survival, rate, cost, cheap rate), the live
                    energy flow (power-flow-card-plus from HACS), today's totals and devices
  2. Today        - energy, cost and self-sufficiency
  3. Bill         - the month so far and the bill period
  4. Battery      - charge, power, charge history and tonight's plan
  5. Controls     - charge target and immersion sliders and switches

Detail lives in sub-views, which have no tab. A tile or heading on the tab opens each one and
the sub-view's back arrow returns to it: Immersion and EV charger (from Power Flow), Cost
breakdown and Solar and forecast (from Today), Tariff (from Bill), Battery detail (from Battery).

Power flow view requires power-flow-card-plus from HACS:
  https://github.com/flixlix/power-flow-card-plus

The immersion charts need apexcharts-card from HACS:
  https://github.com/RomRider/apexcharts-card

All other views use only built-in HA Lovelace cards.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import yaml
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_CURRENCY,
    CONF_FORECAST_ENTITY,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
    CONF_INVERTER_TEMP_ENTITY,
    CURRENCIES,
    DEFAULT_CURRENCY,
    DOMAIN,
    SERVICE_GET_DASHBOARD_YAML,
)
from .core.tariff import TariffConfig, build_tariff
from .logging import get_logger

_LOG = get_logger(__name__)

# ── View paths ───────────────────────────────────────────────────────────────
# A tab is a view with a tab. A sub-view has none: a tile or heading on a tab opens it and
# its back arrow returns to that tab.
TAB_POWER_FLOW = "power-flow"
TAB_TODAY = "today"
TAB_BILL = "bill"
TAB_BATTERY = "battery"
TAB_CONTROLS = "controls"
SUB_IMMERSION = "immersion"
SUB_EV = "ev-charger"
SUB_COST = "cost"
SUB_SOLAR = "solar"
SUB_TARIFF = "tariff"
SUB_BATTERY = "battery-detail"
_TABS = frozenset({TAB_POWER_FLOW, TAB_TODAY, TAB_BILL, TAB_BATTERY, TAB_CONTROLS})

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
_HEX = {IMMERSION: "#FF9800", EV: "#009688"}

_BAR = {"type": "bar-gauge", "min": 0, "max": 100}
_SLIDER = {"type": "numeric-input", "style": "slider"}
_TOGGLE = {"type": "toggle"}
_TREND = {"type": "trend-graph", "hours_to_show": 24}

FULL = "full"
MAX_COLUMNS = 3


# ── Entity lookup ────────────────────────────────────────────────────────────


class _Registry:
    """Looks up our entities and skips those that are missing or disabled.

    A card that points at a disabled entity shows "Entity not available", so the
    generator leaves such rows out and remembers what it dropped.
    """

    def __init__(self, registry, entry_id: str) -> None:
        self._reg = registry
        self._entry_id = entry_id
        self.disabled: dict[str, str] = {}

    def get(self, unique_id_suffix: str) -> str | None:
        """Return the entity_id for one of our entities, or None if unusable."""
        uid = f"{self._entry_id}_{unique_id_suffix}"
        entity_id = None
        for domain in ("sensor", "switch", "number"):
            entity_id = self._reg.async_get_entity_id(domain, DOMAIN, uid)
            if entity_id:
                break
        if not entity_id:
            return None
        registered = self._reg.async_get(entity_id)
        if registered is not None and registered.disabled_by is not None:
            label = registered.name or registered.original_name or entity_id
            self.disabled.setdefault(entity_id, label)
            return None
        return entity_id


_EV_CHARGER_CANDIDATES = [
    "sensor.myenergi_zappi_power_ct_internal_load",
    "sensor.myenergi_zappi_power_ct_internal_load_2",
    "sensor.myenergi_zappi2_power_ct_internal_load",
    "sensor.wallbox_charging_power",
    "sensor.ohme_current_power",
]


def _external_ev_power(hass: HomeAssistant) -> str | None:
    """Return the first known external EV charger power entity that exists.

    These integrations report the charger's power directly. The integration's own
    sensor reads from GivTCP and may show 0W.
    """
    for candidate in _EV_CHARGER_CANDIDATES:
        if hass.states.get(candidate) is not None:
            return candidate
    return None


def _entry_config(entry: ConfigEntry) -> dict:
    """Return the config entry's data with options layered over it."""
    return {**entry.data, **entry.options}


def _ev_charger_brand(entry: ConfigEntry) -> str | None:
    """Brand of the EV charger the coordinator discovered, if any."""
    return getattr(getattr(entry, "runtime_data", None), "ev_charger_brand", None)


# ── YAML ─────────────────────────────────────────────────────────────────────


class _DashboardDumper(yaml.SafeDumper):
    """SafeDumper that writes multi-line strings as literal blocks and never folds."""

    def ignore_aliases(self, data):
        return True


def _represent_str(dumper: yaml.SafeDumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_DashboardDumper.add_representer(str, _represent_str)


def _dump_yaml(data: dict) -> str:
    """Serialise with the options Home Assistant uses for its own YAML output."""
    return yaml.dump(
        data,
        Dumper=_DashboardDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=10_000,
    )


# ── Card primitives ──────────────────────────────────────────────────────────


def _apex_config(height: int = 180) -> dict:
    return {
        "chart": {"height": height, "zoom": {"enabled": False}},
        "tooltip": {"shared": True, "followCursor": True},
        "stroke": {"curve": "smooth", "width": 2},
        "markers": {"size": 0, "hover": {"size": 5}},
        "legend": {"show": False},
    }


def _present(items: list) -> list:
    return [item for item in items if item is not None]


def _row(entity: str | None, name: str, **extra) -> dict | None:
    """An entities-card row, or None when the entity is unusable."""
    if not entity:
        return None
    return {"entity": entity, "name": name, **extra}


def _nav(path: str) -> dict:
    """A tap action that opens another view of the same dashboard.

    The path is relative, so it works whatever URL the dashboard is served from.
    """
    return {"action": "navigate", "navigation_path": path}


def _tile(  # noqa: PLR0913
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


def _toggle_tile(entity: str | None, name: str, color: str) -> dict | None:
    """A tile with an on/off switch beside the name."""
    return _tile(entity, name, color=color, features=[_TOGGLE], inline=True)


def _slider_tile(entity: str | None, name: str, color: str) -> dict | None:
    """A full-width tile with a slider under the name."""
    return _tile(entity, name, columns=FULL, color=color, features=[_SLIDER])


def _heading(
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


def _subheading(text: str, icon: str | None = None) -> dict:
    """A heading one step down, for a question under a section."""
    return {**_heading(text, icon), "heading_style": "subtitle"}


def _block(heading: dict, cards: list) -> list:
    """A heading and its cards. Empty when there are no cards, so no lone heading is left."""
    cards = _present(cards)
    return [heading, *cards] if cards else []


def _section(*blocks: list, **extra) -> dict | None:
    """A section of the sections view. None when it would hold no cards."""
    cards = [card for block in blocks for card in block]
    if not cards:
        return None
    return {"type": "grid", **extra, "cards": cards}


def _group(heading: dict, cards: list, **extra) -> dict | None:
    """A section that holds one heading and its cards."""
    return _section(_block(heading, cards), **extra)


def _markdown(content: str) -> dict:
    return {"type": "markdown", "content": content, "grid_options": {"columns": FULL}}


def _state_ref(entity: str) -> str:
    """The template that prints an entity's state."""
    return f"{{{{ states('{entity}') }}}}"


def _state_markdown(entity: str | None) -> dict | None:
    """A markdown card that prints an entity's state, for sensors whose state is a sentence."""
    return _markdown(_state_ref(entity)) if entity else None


def _view(title: str, icon: str, path: str, sections: list, **extra) -> dict:
    return {
        "title": title,
        "icon": icon,
        "path": path,
        "type": "sections",
        "max_columns": MAX_COLUMNS,
        **extra,
        "sections": _present(sections),
    }


def _graph(card: dict, rows: int = 4) -> dict:
    """Give a built-in graph the full width and a fixed height."""
    return {**card, "grid_options": {"columns": FULL, "rows": rows}}


def _statistics_graph(rows: list, period: str, days: int) -> dict | None:
    """Bars of the change in each period, for sensors that reset every day.

    A history graph of such a sensor draws a sawtooth that falls to zero at midnight.
    The daily sensors keep long-term statistics, so the change per period is exact.
    """
    card = _entity_list_card(
        rows,
        {"type": "statistics-graph"},
        chart_type="bar",
        period=period,
        days_to_show=days,
        stat_types=["change"],
    )
    return _graph(card) if card else None


def _entity_list_card(rows: list, head: dict, **tail) -> dict | None:
    """A card built from rows. None when no row points at an entity."""
    rows = _present(rows)
    if not any("entity" in r for r in rows):
        return None
    return {**head, "entities": rows, **tail}


# ── HACS cards ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _HacsCard:
    """A custom card from HACS, with the note the generated file carries about it."""

    name: str
    url: str
    header: str

    @property
    def card_type(self) -> str:
        return f"custom:{self.name}"

    @property
    def note(self) -> str:
        return f"{self.name}: {self.url}"


POWER_FLOW_CARD = _HacsCard(
    "power-flow-card-plus",
    "https://github.com/flixlix/power-flow-card-plus",
    "# The live power flow requires power-flow-card-plus from HACS:\n"
    "#   https://github.com/flixlix/power-flow-card-plus\n",
)
APEX_CARD = _HacsCard(
    "apexcharts-card",
    "https://github.com/RomRider/apexcharts-card",
    "# The immersion charts require apexcharts-card from HACS:\n"
    "#   https://github.com/RomRider/apexcharts-card\n",
)
_HACS_CARDS = (POWER_FLOW_CARD, APEX_CARD)


class _HacsCards:
    """Decides between each HACS card and its built-in fallback, once, and remembers why.

    The header comment of the generated file reads the outcome: which custom cards the
    dashboard uses and which fallbacks stand in for cards that are not installed.
    """

    def __init__(self, resources: list[str] | None) -> None:
        self._resources = resources
        self.used: set[_HacsCard] = set()
        self.fallbacks: list[_HacsCard] = []

    def use(self, card: _HacsCard) -> bool:
        """True to build the HACS card. False means build the built-in fallback instead."""
        if self._installed(card):
            self.used.add(card)
            return True
        if card not in self.fallbacks:
            self.fallbacks.append(card)
        return False

    def _installed(self, card: _HacsCard) -> bool:
        """True unless the Lovelace resources are known and do not include this card.

        Unknown resources (None) mean the generator could not read them, in which
        case the custom card is assumed to be there, as it always was.
        """
        if self._resources is None:
            return True
        return any(card.name in url.lower() for url in self._resources)


async def async_lovelace_resource_urls(hass: HomeAssistant) -> list[str] | None:
    """Return the URLs of the Lovelace resources, or None when they cannot be read.

    HACS cards register here (storage mode) or in configuration.yaml (YAML mode).
    A card loaded some other way, for example by another integration, is not listed.
    """
    data = hass.data.get("lovelace")
    resources = (
        data.get("resources") if isinstance(data, dict) else getattr(data, "resources", None)
    )
    if resources is None:
        return None
    try:
        await resources.async_get_info()
        return [str(item.get("url", "")) for item in resources.async_items() or []]
    except Exception as err:  # noqa: BLE001
        _LOG.debug("Could not read Lovelace resources: %s", err)
        return None


# ── Immersion charts ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _ImmersionEntities:
    """The entities the immersion charts draw."""

    temp_sensor: str
    target: str | None
    minimum: str | None
    energy_today: str | None
    power: str | None


def _builtin_immersion_charts(ent: _ImmersionEntities) -> tuple[list, list]:
    """Built-in cards: a history graph of the temperatures and energy per hour."""
    temps = _entity_list_card(
        [_row(ent.temp_sensor, "Water"), _row(ent.target, "Target"), _row(ent.minimum, "Minimum")],
        {"type": "history-graph"},
        hours_to_show=12,
    )
    energy = _statistics_graph([_row(ent.energy_today, "Immersion")], "hour", 1)
    return ([_graph(temps)] if temps else []), _present([energy])


def _apex_series(entity: str | None, name: str, color: str, width: int) -> dict | None:
    if not entity:
        return None
    return {"entity": entity, "name": name, "color": color, "stroke_width": width}


def _apex_temperature_chart(ent: _ImmersionEntities, orange: str) -> dict:
    """12 hours of the water temperature, with the target and minimum."""
    return {
        "type": APEX_CARD.card_type,
        "header": {"show": False},
        "graph_span": "12h",
        "apex_config": {**_apex_config(), "legend": {"show": True, "position": "bottom"}},
        "series": _present(
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
        "apex_config": {**_apex_config(), "stroke": {"curve": "stepline", "width": 2}},
        "series": [_apex_series(power, "Power", orange, 2)],
        "grid_options": {"columns": FULL},
    }


def _apex_immersion_charts(ent: _ImmersionEntities) -> tuple[list, list]:
    """apexcharts cards: the temperature chart, and the power chart when there is a sensor."""
    # Same orange as the immersion tiles. Lower case keeps the generated file unchanged.
    orange = _HEX[IMMERSION].lower()
    power = [_apex_power_chart(ent.power, orange)] if ent.power else []
    return [_apex_temperature_chart(ent, orange)], power


# ── Rendering ────────────────────────────────────────────────────────────────

_HEADER_TITLE = f"""\
# GivEnergy Inverter Manager — Generated Dashboard
# Generated by: Developer Tools → Actions → {DOMAIN}.{SERVICE_GET_DASHBOARD_YAML}
#
"""
_HEADER_USE = """\
# All other views use only built-in HA cards.
#
# To use: Settings → Dashboards → new blank dashboard
#         Three-dot menu → Edit dashboard → Raw configuration editor → paste
"""


@dataclass
class _Built:
    config: dict
    skipped: list[str] = field(default_factory=list)
    cards: _HacsCards = field(default_factory=lambda: _HacsCards(None))


def render_dashboard(
    hass: HomeAssistant,
    entry: ConfigEntry,
    resources: list[str] | None = None,
    registry=None,
) -> tuple[str, list[str]]:
    """Return the dashboard YAML text and the names of disabled sensors it left out.

    *registry* answers the two entity registry calls the builder makes. It defaults to the
    registry of *hass*.
    """
    built = _generate(hass, entry, resources, registry)
    return _header(built) + _dump_yaml(built.config), built.skipped


def build_dashboard(
    hass: HomeAssistant,
    entry: ConfigEntry,
    resources: list[str] | None = None,
    registry=None,
) -> dict:
    """Return the dashboard as a dict, for the Lovelace strategy."""
    return _generate(hass, entry, resources, registry).config


def _fallback_note(cards: list[_HacsCard]) -> str:
    """The header lines that name the HACS cards the dashboard does without."""
    if not cards:
        return ""
    return (
        "# Built-in cards are used in place of these HACS cards, which are not installed.\n"
        "# Install them from HACS, then generate this file again:\n"
        + "".join(f"#   {card.note}\n" for card in cards)
    )


def _skipped_note(names: list[str]) -> str:
    """The header lines that name the disabled sensors the dashboard leaves out."""
    if not names:
        return ""
    return (
        "# Left out because these sensors are disabled. Enable them in\n"
        "# Settings → Devices & services → Entities, then generate this file again:\n"
        + "".join(f"#   {name}\n" for name in names)
    )


def _header(built: _Built) -> str:
    """The comment at the top of the generated file."""
    used = [card.header for card in _HACS_CARDS if card in built.cards.used]
    head = _HEADER_TITLE + "".join(used) + _HEADER_USE
    notes = [_fallback_note(built.cards.fallbacks), _skipped_note(built.skipped)]
    if not any(notes):
        return head + "\n"
    return head + "".join(f"{note}\n" for note in notes if note)


def _generate(
    hass: HomeAssistant,
    entry: ConfigEntry,
    resources: list[str] | None = None,
    registry=None,
) -> _Built:
    """Build the Lovelace configuration as a dict.

    Uses actual entity IDs from the entity registry so names customised in the HA
    UI are respected. A tile or card appears only when its entity is registered and
    enabled, and the feature behind it (EV charger, immersion heater, inverter
    temperature, solar forecast) is configured.
    """
    builder = _Builder(hass, entry, resources, registry)
    subviews = builder.build_subviews()
    tabs = [spec.build(builder) for spec in _TAB_VIEWS]
    views = [view for view in tabs + subviews if view["sections"]]
    return _Built({"views": views}, sorted(builder.reg.disabled.values()), builder.cards)


# ── Views ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _CostEntities:
    """The cost sensors of the Cost breakdown sub-view."""

    grid_import: str | None
    export_earnings: str | None
    house: str | None
    ev: str | None
    immersion: str | None


def _cost_history(cost: _CostEntities) -> dict | None:
    """Bars of the cost per day for two weeks."""
    return _statistics_graph(
        [
            _row(cost.grid_import, "Grid Import"),
            _row(cost.house, "Rest of House"),
            _row(cost.ev, "EV Charging"),
            _row(cost.immersion, "Immersion"),
            _row(cost.export_earnings, "Export Earnings"),
        ],
        "day",
        14,
    )


class _Builder:
    """Builds the sections of each view from the entities that exist.

    Tabs link to sub-views, and a link is left out when its sub-view is empty. So the
    sub-views are built first, with build_subviews, and the tabs after.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        resources: list[str] | None,
        registry,
    ) -> None:
        self.cards = _HacsCards(resources)
        self.reg = _Registry(er.async_get(hass) if registry is None else registry, entry.entry_id)
        self.cfg = _entry_config(entry)
        self.external_ev = _external_ev_power(hass)
        self.has_ev = bool(_ev_charger_brand(entry) or self.external_ev)
        self.has_immersion = bool(
            self.cfg.get(CONF_IMMERSION_SWITCH) or self.cfg.get(CONF_IMMERSION_TEMP_SENSOR)
        )
        self.has_inverter_temp = bool(self.cfg.get(CONF_INVERTER_TEMP_ENTITY))
        self.has_forecast = bool(self.cfg.get(CONF_FORECAST_ENTITY))
        self._subview_paths: set[str] | None = None

    # -- entities --

    def entity(self, suffix: str) -> str | None:
        """The entity with this unique ID suffix, or None when it is missing or disabled."""
        return self.reg.get(suffix)

    def ev(self, suffix: str) -> str | None:
        """Like entity, but None unless an EV charger is configured."""
        return self.entity(suffix) if self.has_ev else None

    def immersion(self, suffix: str) -> str | None:
        """Like entity, but None unless an immersion heater is configured."""
        return self.entity(suffix) if self.has_immersion else None

    def inverter_temp(self, suffix: str) -> str | None:
        """Like entity, but None unless an inverter temperature entity is configured."""
        return self.entity(suffix) if self.has_inverter_temp else None

    def ev_power(self) -> str | None:
        """The charger's power: a known external charger first, then our own sensor."""
        if not self.has_ev:
            return None
        # Looked up first, so a disabled sensor is still listed as left out.
        integration_power = self.entity("ev_power")
        return self.external_ev or integration_power

    def tile(self, suffix: str, name: str, **style) -> dict | None:
        """A tile for the entity with this unique ID suffix."""
        return _tile(self.entity(suffix), name, **style)

    # -- navigation --

    def build_subviews(self) -> list[dict]:
        """Build every sub-view and note which of them hold cards. Call before the tabs."""
        views = [spec.build(self) for spec in _SUBVIEWS]
        self._subview_paths = {view["path"] for view in views if view["sections"]}
        return views

    def has_subview(self, path: str) -> bool:
        """True when the sub-view at path was built and holds cards."""
        if self._subview_paths is None:
            raise RuntimeError("build the sub-views before the tabs that link to them")
        return path in self._subview_paths

    def go(self, path: str) -> dict | None:
        """A tap action to the view at path, or None when that sub-view is empty.

        The tabs always exist. A sub-view is left out when it would be empty.
        """
        if path in _TABS or self.has_subview(path):
            return _nav(path)
        return None

    # -- Power Flow --

    def _solar_node(self) -> dict | None:
        solar_power = self.entity("solar_power")
        if not solar_power:
            return None
        node: dict = {
            "entity": solar_power,
            "color_icon": False,
            "color_value": False,
            "invert_state": False,
        }
        if is_clipping := self.entity("is_clipping"):
            node["secondary_info_entity"] = is_clipping
            node["secondary_info"] = {
                "template": f'{{{{- "·⚡Clip" if states("{is_clipping}") == "clipping" else "" }}}}'
            }
        return node

    def _battery_node(self) -> dict | None:
        battery_power = self.entity("battery_power")
        if not battery_power:
            return None
        # The manager's Battery Power is positive while charging. The card reads a
        # positive value as discharging unless it is told to invert it.
        node: dict = {"entity": battery_power, "invert_state": True}
        if battery_soc := self.entity("battery_soc"):
            node["state_of_charge"] = battery_soc
            node["show_state_of_charge"] = True
        return node

    def _grid_node(self) -> dict | None:
        grid_power = self.entity("grid_power")
        if not grid_power:
            return None
        node: dict = {
            "entity": grid_power,
            "use_metadata": False,
            "invert_state": False,
            "display_state": "one_way",
        }
        if live_grid_cost_rate := self.entity("live_grid_cost_rate"):
            node["secondary_info"] = {
                "entity": live_grid_cost_rate,
                "icon": "mdi:cash-clock",
                "decimals": 4,
                "display_zero": True,
                "color_value": False,
                "unit_of_measurement": " ",
            }
        return node

    def _home_node(self) -> dict | None:
        house_load = self.entity("house_load")
        if not house_load:
            return None
        return {"entity": house_load, "subtract_individual": False, "hide": False}

    def _individual_nodes(self) -> list:
        """The devices drawn beside the home node."""
        return _present(
            [
                _row(
                    self.ev_power(),
                    "Car Charger",
                    icon="mdi:car-electric",
                    display_zero=False,
                    color=_HEX[EV],
                ),
                _row(
                    self.immersion("immersion_power"),
                    "Immersion",
                    icon="mdi:water-boiler",
                    display_zero=False,
                    color=_HEX[IMMERSION],
                ),
            ]
        )

    def _flow_entities(self) -> dict:
        nodes = {
            "solar": self._solar_node(),
            "battery": self._battery_node(),
            "grid": self._grid_node(),
            "home": self._home_node(),
        }
        out = {name: node for name, node in nodes.items() if node}
        if individual := self._individual_nodes():
            out["individual"] = individual
        return out

    def _now(self) -> list:
        """The numbers worth a glance: charge first, then outlook, rate, cost, cheap rate."""
        return _block(
            _heading("Now", "mdi:clock-outline"),
            [
                self.tile(
                    "battery_soc",
                    "Battery",
                    color=BATTERY,
                    features=[_BAR],
                    nav=self.go(TAB_BATTERY),
                    rows=3,
                ),
                self.tile(
                    "night_survival_confidence",
                    "Night survival",
                    color=NIGHT,
                    nav=self.go(SUB_BATTERY),
                ),
                self.tile("current_rate", "Rate now", color=GRID),
                self.tile("import_cost_today", "Cost today", color=GRID, nav=self.go(TAB_TODAY)),
                self.tile("next_cheap_rate_start", "Cheap from", color=GRID),
                self.tile("hours_to_cheap_rate", "Cheap in", color=GRID, icon="mdi:timer-outline"),
            ],
        )

    def _flow(self) -> list:
        flow = self._flow_entities()
        if not flow:
            return []
        card = _flow_card(flow) if self.cards.use(POWER_FLOW_CARD) else _flow_fallback(flow)
        return _block(
            _heading("Live power flow", "mdi:transmission-tower"),
            [{**card, "grid_options": {"columns": FULL}} if card else None],
        )

    def _totals(self) -> list:
        return _block(
            _heading("Energy today", "mdi:lightning-bolt", nav=self.go(TAB_TODAY)),
            [
                self.tile("solar_today", "Generated", color=SOLAR),
                self.tile("house_kwh_today", "Used", color=GRID),
                self.tile("import_today", "Imported", color=GRID),
                self.tile("export_today", "Exported", color=GRID),
            ],
        )

    def _devices(self) -> list:
        immersion = _tile(
            self.cfg.get(CONF_IMMERSION_TEMP_SENSOR) or None,
            "Immersion",
            color=IMMERSION,
            icon="mdi:water-boiler",
            nav=self.go(SUB_IMMERSION),
        )
        ev_charger = _tile(
            self.ev("ev_charger_state") if self.has_subview(SUB_EV) else None,
            "EV charger",
            color=EV,
            icon="mdi:ev-station",
            nav=self.go(SUB_EV),
        )
        return _block(
            _heading("Devices", "mdi:power-plug"),
            [immersion if self.has_subview(SUB_IMMERSION) else None, ev_charger],
        )

    def power_flow_sections(self) -> list:
        return _present(
            [
                _section(self._now()),
                _section(self._flow()),
                _section([*self._totals(), *self._devices()]),
            ]
        )

    # -- Immersion sub-view --

    def _immersion_charts(self) -> tuple[list, list]:
        """The temperature cards and the power cards. Both empty without a temperature sensor."""
        temp_sensor = self.cfg.get(CONF_IMMERSION_TEMP_SENSOR, "")
        entities = _ImmersionEntities(
            temp_sensor,
            self.entity("immersion_target_temp"),
            self.entity("immersion_min_temp"),
            self.entity("immersion_today"),
            self.entity("immersion_power"),
        )
        if not temp_sensor:
            return [], []
        if self.cards.use(APEX_CARD):
            return _apex_immersion_charts(entities)
        return _builtin_immersion_charts(entities)

    def immersion_sections(self) -> list:
        """Sub-view: the water temperature and power charts and why the heater is on or off."""
        if not self.has_immersion:
            return []
        temps, power = self._immersion_charts()
        reason = self.entity("immersion_divert_reason")
        return [
            _section(
                _block(_heading("Water temperature", "mdi:thermometer-water"), temps),
                _block(_subheading("Why", "mdi:help-circle-outline"), [_state_markdown(reason)]),
            ),
            _group(_heading("Heater power", "mdi:flash"), power),
            _group(
                _heading("Today", "mdi:calendar-today"),
                [
                    self.tile("immersion_today", "Energy", color=IMMERSION),
                    self.tile("immersion_cost_today", "Cost", color=GRID),
                    self.tile("immersion_savings_today", "Saved by solar", color=BATTERY),
                ],
            ),
        ]

    # -- EV charger sub-view --

    def ev_sections(self) -> list:
        """Sub-view: the EV charger's state and why it is or is not charging."""
        decision = self.ev("ev_protection_reason")
        return [
            _group(
                _heading("Charging now", "mdi:ev-station"),
                [
                    _tile(self.ev("ev_charger_state"), "Charger state", color=EV),
                    _tile(self.ev_power(), "Charge power", color=EV),
                    _tile(self.ev("ev_session_energy"), "Session energy", color=EV),
                    _tile(self.ev("ev_charging_source"), "Charging source", color=EV),
                ],
            ),
            _group(
                _heading("Why", "mdi:help-circle-outline"),
                [
                    _tile(self.ev("ev_draining_battery"), "Drains battery", color=BATTERY),
                    _tile(self.ev("ev_solar_surplus_available"), "Solar surplus", color=SOLAR),
                    _state_markdown(decision),
                ],
            ),
        ]

    # -- Today --

    def _today_energy(self) -> dict | None:
        return _group(
            _heading("Energy", "mdi:lightning-bolt"),
            [
                self.tile("solar_today", "Generated", color=SOLAR),
                self.tile("house_kwh_today", "Used", color=GRID),
                self.tile("import_today", "Imported", color=GRID),
                self.tile("export_today", "Exported", color=GRID),
                _tile(self.ev("zappi_today"), "EV", color=EV),
                _tile(self.immersion("immersion_today"), "Immersion", color=IMMERSION),
            ],
        )

    def _today_cost(self) -> dict | None:
        return _group(
            _heading("Cost", "mdi:cash-multiple", nav=self.go(SUB_COST)),
            [
                self.tile("import_cost_today", "Import cost", color=GRID),
                self.tile("export_earnings_today", "Export earnings", color=BATTERY),
                self.tile("current_rate", "Rate now", color=GRID),
                self.tile("current_rate_period", "Rate period", color=GRID),
            ],
        )

    def _today_solar(self) -> dict | None:
        share = {"columns": FULL, "color": SOLAR, "features": [_BAR]}
        return _group(
            _heading("Solar", "mdi:weather-sunny", nav=self.go(SUB_SOLAR)),
            [
                self.tile("self_sufficiency", "Self-sufficiency", **share),
                self.tile("self_consumption", "Self-consumption", **share),
            ],
        )

    def today_sections(self) -> list:
        return [self._today_energy(), self._today_cost(), self._today_solar()]

    def _cost_entities(self) -> _CostEntities:
        return _CostEntities(
            self.entity("import_cost_today"),
            self.entity("export_earnings_today"),
            self.entity("house_cost_today"),
            self.ev("zappi_cost_today"),
            self.immersion("immersion_cost_today"),
        )

    def cost_sections(self) -> list:
        """Sub-view: every cost line for today and the cost per day for two weeks."""
        cost = self._cost_entities()
        return [
            _group(
                _heading("Today", "mdi:calendar-today"),
                [
                    _tile(cost.grid_import, "Grid import", color=GRID),
                    _tile(cost.export_earnings, "Export earnings", color=BATTERY),
                    _tile(cost.house, "Rest of house", color=GRID),
                    _tile(cost.ev, "EV charging", color=EV),
                    _tile(cost.immersion, "Immersion", color=IMMERSION),
                    self._immersion_savings_tile(),
                ],
            ),
            _group(_heading("Last 14 days", "mdi:chart-bar"), [_cost_history(cost)]),
        ]

    def _immersion_savings_tile(self) -> dict | None:
        """What solar saved on the immersion today."""
        return _tile(self.immersion("immersion_savings_today"), "Saved by solar", color=BATTERY)

    def solar_sections(self) -> list:
        """Sub-view: how solar compares with the forecast and the generation per hour."""
        solar_today = self.entity("solar_today")
        forecast = (
            [
                _tile(solar_today, "Generated today", color=SOLAR),
                self.tile("solar_forecast_kwh_today", "Forecast today", color=SOLAR),
                self.tile("solar_actual_vs_forecast_pct", "Tracking", color=SOLAR),
                self.tile("yesterday_forecast_accuracy_pct", "Yesterday", color=SOLAR),
            ]
            if self.has_forecast
            else []
        )
        return [
            _group(_heading("Against the forecast", "mdi:chart-line"), forecast),
            _group(
                _heading("Generation per hour", "mdi:chart-bar"),
                [_statistics_graph([_row(solar_today, "Actual")], "hour", 2)],
            ),
        ]

    # -- Bill --

    def _bill_so_far(self) -> dict | None:
        tariff = self.go(SUB_TARIFF)
        badges = (
            [{"type": "button", "icon": "mdi:table", "text": "Tariff", "tap_action": tariff}]
            if tariff
            else None
        )
        return _group(
            _heading("Bill so far", "mdi:receipt-text", badges=badges),
            [
                self.tile("accrued_bill", "Accrued bill", color=GRID),
                self.tile("projected_bill", "Projected bill", color=GRID),
                self.tile("import_cost_this_month", "Import cost", color=GRID),
                self.tile("export_earnings_this_month", "Export credit", color=BATTERY),
            ],
        )

    def _bill_period(self) -> dict | None:
        return _group(
            _heading("This bill period", "mdi:calendar-month"),
            [
                self.tile("days_in_period", "Days elapsed"),
                self.tile("days_remaining_in_period", "Days left"),
                self.tile("avg_import_rate_this_month", "Avg import rate", color=GRID),
                self.tile("cheap_import_fraction_this_month", "Cheap share", color=GRID),
            ],
        )

    def bill_sections(self) -> list:
        """The month so far and the tariff the sums use, to compare with a real bill."""
        return [self._bill_so_far(), self._bill_period()]

    def tariff_sections(self) -> list:
        """Sub-view: the rates and charges the bill sums use."""
        table = _markdown(_tariff_table(build_tariff(self.cfg), self.cfg))
        return [_group(_heading("Tariff in use", "mdi:table"), [table])]

    # -- Battery --

    def _battery_now(self) -> dict | None:
        battery_soc = self.entity("battery_soc")
        history = _entity_list_card(
            [_row(battery_soc, "Charge")], {"type": "history-graph"}, hours_to_show=24
        )
        return _group(
            _heading("Battery", "mdi:battery-heart-variant", nav=self.go(SUB_BATTERY)),
            [
                _tile(battery_soc, "Charge", color=BATTERY, features=[_BAR]),
                self.tile("battery_power", "Power", color=BATTERY, features=[_TREND]),
                _graph(history) if history else None,
            ],
        )

    def _charge_plan(self) -> dict | None:
        return _group(
            _heading("Tonight's charge plan", "mdi:weather-night"),
            [
                self.tile("overnight_charge_target", "Target tonight", color=BATTERY),
                self.tile("overnight_charge_cost", "Est. cost", color=GRID),
                self.tile("estimated_soc_at_sunrise", "At sunrise", color=BATTERY),
                self.tile(
                    "cheap_rate_floor_status", "Rate floor", color=GRID, icon="mdi:floor-plan"
                ),
            ],
        )

    def battery_sections(self) -> list:
        return [self._battery_now(), self._charge_plan()]

    def _battery_health(self) -> dict | None:
        return _group(
            _heading("Battery health", "mdi:battery-heart-variant"),
            [
                self.tile("battery_cycles", "Total cycles", color=BATTERY),
                self.tile("battery_remaining_life", "Life remaining", color=BATTERY),
                self.tile(
                    "days_since_full_charge", "Since full", color=BATTERY, icon="mdi:battery-check"
                ),
                _tile(self.inverter_temp("inverter_temperature"), "Inverter temp", color=GRID),
                _tile(
                    self.inverter_temp("inverter_temperature_status"),
                    "Inverter status",
                    color=GRID,
                    icon="mdi:thermometer-alert",
                ),
            ],
        )

    def battery_detail_sections(self) -> list:
        """Sub-view: why tonight's plan is what it is, and the battery's health."""
        return [
            _section(
                _block(_heading("Night survival", "mdi:weather-night"), self._night_survival()),
                _block(
                    _subheading("Tonight's charge target", "mdi:battery-charging"),
                    [_state_markdown(self.entity("overnight_charge_reason"))],
                ),
            ),
            self._battery_health(),
        ]

    def _night_survival(self) -> list:
        """The night survival level in bold, then why, in words.

        The confidence sensor carries the level. Its explanation attribute is used when
        it has one. Without it a sentence is chosen by level: Warning is explained from
        the estimated state of charge at sunrise, and Safe and Critical show the status
        sensor's text, which carries any kWh shortfall.
        """
        level = self.entity("night_survival_confidence")
        status = self.entity("night_survival_reason")
        sunrise = self.entity("estimated_soc_at_sunrise")
        if level:
            return [_markdown(_survival_template(level, status, sunrise))]
        if status:
            return [_markdown(f"**Night survival**\n\n{_state_ref(status)}")]
        return []

    # -- Controls --

    def _dry_run_section(self) -> dict | None:
        """A banner, shown only while Dry Run Mode Active is true."""
        dry_run_active = self.entity("dry_run_active")
        if not dry_run_active:
            return None
        text = (
            "No commands are sent to your inverter or EV charger. Sensors and charge "
            "decisions still update. To go live, turn off Dry Run in Settings, Devices & "
            "services, GivEnergy Inverter Manager, Configure."
        )
        if skipped := self.entity("dry_run_last_skipped"):
            text += f"\n\n**Last skipped action:** {_state_ref(skipped)}"
        return _group(
            _heading("Dry run is on", "mdi:test-tube"),
            [_markdown(text)],
            visibility=[{"condition": "state", "entity": dry_run_active, "state": "True"}],
        )

    def _charging_controls(self) -> dict | None:
        return _group(
            _heading("Overnight charging", "mdi:battery-charging"),
            [
                _slider_tile(self.entity("charge_target_override"), "Charge target", BATTERY),
                _toggle_tile(self.entity("charge_target_override_enabled"), "Use target", BATTERY),
                _toggle_tile(self.entity("skip_charge_override"), "Skip tonight", BATTERY),
            ],
        )

    def _immersion_controls(self) -> dict | None:
        return _group(
            _heading("Immersion heater", "mdi:water-boiler"),
            [
                _toggle_tile(self.immersion("auto_immersion"), "Auto divert", IMMERSION),
                _toggle_tile(self.immersion("immersion_managed"), "Managed", IMMERSION),
                _state_markdown(self.immersion("immersion_divert_reason")),
                _slider_tile(self.immersion("immersion_target_temp"), "Target temp", IMMERSION),
                _slider_tile(self.immersion("immersion_min_temp"), "Minimum temp", IMMERSION),
                _slider_tile(self.immersion("immersion_hysteresis"), "Restart gap", IMMERSION),
            ],
        )

    def controls_sections(self) -> list:
        return [self._dry_run_section(), self._charging_controls(), self._immersion_controls()]


@dataclass(frozen=True)
class _ViewSpec:
    """A view of the dashboard: its title and icon, and the builder method for its sections.

    A sub-view names the tab its back arrow returns to. A tab has no back.
    """

    title: str
    icon: str
    path: str
    sections: Callable[[_Builder], list]
    back: str | None = None

    def build(self, builder: _Builder) -> dict:
        extra = {} if self.back is None else {"subview": True, "back_path": self.back}
        return _view(self.title, self.icon, self.path, self.sections(builder), **extra)


_TAB_VIEWS = (
    _ViewSpec(
        "Power Flow", "mdi:solar-power-variant", TAB_POWER_FLOW, _Builder.power_flow_sections
    ),
    _ViewSpec("Today", "mdi:calendar-today", TAB_TODAY, _Builder.today_sections),
    _ViewSpec("Bill", "mdi:receipt-text", TAB_BILL, _Builder.bill_sections),
    _ViewSpec("Battery", "mdi:battery-charging", TAB_BATTERY, _Builder.battery_sections),
    _ViewSpec("Controls", "mdi:tune", TAB_CONTROLS, _Builder.controls_sections),
)
_SUBVIEWS = (
    _ViewSpec(
        "Immersion", "mdi:water-boiler", SUB_IMMERSION, _Builder.immersion_sections, TAB_POWER_FLOW
    ),
    _ViewSpec("EV charger", "mdi:ev-station", SUB_EV, _Builder.ev_sections, TAB_POWER_FLOW),
    _ViewSpec("Cost breakdown", "mdi:cash-multiple", SUB_COST, _Builder.cost_sections, TAB_TODAY),
    _ViewSpec(
        "Solar and forecast", "mdi:weather-sunny", SUB_SOLAR, _Builder.solar_sections, TAB_TODAY
    ),
    _ViewSpec("Tariff", "mdi:table", SUB_TARIFF, _Builder.tariff_sections, TAB_BILL),
    _ViewSpec(
        "Battery detail",
        "mdi:battery-heart-variant",
        SUB_BATTERY,
        _Builder.battery_detail_sections,
        TAB_BATTERY,
    ),
)


# ── Content helpers ──────────────────────────────────────────────────────────


def _flow_card(flow: dict) -> dict:
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


def _flow_fallback(flow: dict) -> dict | None:
    """An entities card with the power flow values, for when power-flow-card-plus is missing."""
    battery = flow.get("battery", {})
    rows = [
        _row(flow.get("solar", {}).get("entity"), "Solar", icon="mdi:solar-power"),
        _row(battery.get("entity"), "Battery power", icon="mdi:home-battery"),
        _row(battery.get("state_of_charge"), "Battery charge"),
        _row(flow.get("grid", {}).get("entity"), "Grid", icon="mdi:transmission-tower"),
        _row(flow.get("home", {}).get("entity"), "Home", icon="mdi:home"),
        *(_row(i["entity"], i["name"], icon=i["icon"]) for i in flow.get("individual", [])),
    ]
    return _entity_list_card(rows, {"type": "entities"})


def _sunrise_phrase(sunrise: str | None) -> str:
    """Where the battery is expected to be at sunrise, as a template fragment."""
    if not sunrise:
        return "the minimum at sunrise"
    return (
        f"{{% if has_value('{sunrise}') %}}about "
        f"{{{{ states('{sunrise}') | float(0) | round(0) | int }}}}% at sunrise"
        "{% else %}the minimum at sunrise{% endif %}"
    )


def _survival_template(level: str, status: str | None, sunrise: str | None) -> str:
    """The night survival card: the level, then the explanation attribute or a sentence."""
    status_text = _state_ref(status) if status else ""
    warning = (
        "The battery should last until solar starts, but only just. "
        f"It is expected to reach {_sunrise_phrase(sunrise)}, close to your minimum charge. "
        "A warning shows when the estimate is within 5 points of the minimum."
    )
    return (
        f"{{% set level = states('{level}') %}}"
        "**Night survival: {{ level }}**\n\n"
        f"{{% if state_attr('{level}', 'explanation') -%}}\n"
        f"{{{{ state_attr('{level}', 'explanation') }}}}\n"
        "{%- elif level | lower == 'warning' -%}\n"
        f"{warning}\n"
        "{%- else -%}\n"
        f"{status_text}\n"
        "{%- endif %}"
    )


def _tariff_table(tariff: TariffConfig, cfg: dict) -> str:
    """Markdown table of the rates the integration prices energy with."""
    symbol = CURRENCIES.get(cfg.get(CONF_CURRENCY, DEFAULT_CURRENCY), "€")
    billed = (1 - tariff.discount_rate / 100) * (1 + tariff.vat_rate / 100)
    rows = [(tariff.base_rate_name, "all other times", tariff.base_rate)]
    rows += [(p.name, f"{p.start:%H:%M} to {p.end:%H:%M}", p.rate) for p in tariff.rate_periods]
    lines = [
        "| Period | Window | Rate per kWh | Billed per kWh |",
        "|---|---|---:|---:|",
        *(f"| {n} | {w} | {symbol}{r:.4f} | {symbol}{r * billed:.4f} |" for n, w, r in rows),
        "",
        f"Billed per kWh is the rate less the {tariff.discount_rate:g}% discount, "
        f"plus {tariff.vat_rate:g}% VAT. Where periods overlap, the cheapest applies.",
        "",
        "| Other charge | Value |",
        "|---|---:|",
        f"| Export rate | {symbol}{tariff.export_rate:.4f} per kWh |",
        f"| Standing charge | {symbol}{tariff.standing_charge:.4f} per day |",
        f"| PSO levy | {symbol}{tariff.pso_levy:.2f} per bill period |",
        f"| Bill starts on day | {tariff.bill_start_day} |",
    ]
    return "\n".join(lines)
