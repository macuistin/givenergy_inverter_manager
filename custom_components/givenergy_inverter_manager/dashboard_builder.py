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

from dataclasses import dataclass, field

import yaml
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
)
from .core.tariff import TariffConfig, build_tariff
from .logging import get_logger

_LOG = get_logger(__name__)

SERVICE_GET_DASHBOARD_YAML = "get_dashboard_yaml"


class _Registry:
    """Looks up our entities and skips those that are missing or disabled.

    A card that points at a disabled entity shows "Entity not available", so the
    generator leaves such rows out and remembers what it dropped.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._reg = er.async_get(hass)
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
    """Return the first known external EV charger power entity that exists."""
    for candidate in _EV_CHARGER_CANDIDATES:
        if hass.states.get(candidate) is not None:
            return candidate
    return None


def _find_ev_charger_power(hass: HomeAssistant, integration_ev_power: str | None) -> str | None:
    """Return the best available EV charger power entity.

    Checks known external EV charger integrations first since these report power
    directly. Falls back to the integration's own sensor if none are found.
    """
    return _external_ev_power(hass) or integration_ev_power


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


# Colours. A few, used the same way on every view: amber for solar, green for the battery,
# blue for the grid and money, orange for the immersion, teal for the EV charger and indigo
# for the night.
SOLAR = "amber"
BATTERY = "green"
GRID = "blue"
IMMERSION = "orange"
EV = "teal"
NIGHT = "indigo"

_BAR = {"type": "bar-gauge", "min": 0, "max": 100}
_SLIDER = {"type": "numeric-input", "style": "slider"}
_TOGGLE = {"type": "toggle"}
_TREND = {"type": "trend-graph", "hours_to_show": 24}

FULL = "full"
MAX_COLUMNS = 3


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


def _heading(  # noqa: PLR0913
    text: str,
    icon: str | None = None,
    *,
    nav: dict | None = None,
    badges: list | None = None,
    subtitle: bool = False,
) -> dict:
    """A section heading. With nav it shows a chevron and opens the view."""
    card: dict = {
        "type": "heading",
        "heading": text,
        "heading_style": "subtitle" if subtitle else "title",
    }
    if icon:
        card["icon"] = icon
    if badges:
        card["badges"] = badges
    if nav:
        card["tap_action"] = nav
    return card


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


def _markdown(content: str) -> dict:
    return {"type": "markdown", "content": content, "grid_options": {"columns": FULL}}


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


def _subview(title: str, icon: str, path: str, back: str, sections: list) -> dict:  # noqa: PLR0913
    """A view with no tab. Its back arrow returns to the view that opened it."""
    return _view(title, icon, path, sections, subview=True, back_path=back)


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


def _immersion_charts(  # noqa: PLR0913
    immersion_temp_sensor: str,
    num_target: str | None,
    num_min: str | None,
    immersion_today: str | None,
    apex: bool = True,  # noqa: FBT001, FBT002
    immersion_power: str | None = None,
) -> tuple[list, list]:
    """Build the temperature cards and the power cards for the Immersion sub-view.

    Returns two lists of cards, both empty when no immersion temperature sensor is
    configured. Requires apexcharts-card from HACS: a 12 hour chart of the water
    temperature with the target and minimum, and a 12 hour step chart of the immersion's
    power. With apex=False the charts are built-in cards instead: a history graph of the
    temperatures and a statistics graph of immersion energy per hour.
    """
    if not immersion_temp_sensor:
        return [], []
    if not apex:
        temps = _entity_list_card(
            [
                _row(immersion_temp_sensor, "Water"),
                _row(num_target, "Target"),
                _row(num_min, "Minimum"),
            ],
            {"type": "history-graph"},
            hours_to_show=12,
        )
        energy = _statistics_graph([_row(immersion_today, "Immersion")], "hour", 1)
        return ([_graph(temps)] if temps else []), _present([energy])

    def series(entity: str | None, name: str, color: str, width: int) -> dict | None:
        if not entity:
            return None
        return {"entity": entity, "name": name, "color": color, "stroke_width": width}

    temperature = {
        "type": "custom:apexcharts-card",
        "header": {"show": False},
        "graph_span": "12h",
        "apex_config": {
            **_apex_config(),
            "legend": {"show": True, "position": "bottom"},
        },
        "series": _present(
            [
                series(immersion_temp_sensor, "Water", "#03a9f4", 2),
                series(num_target, "Target", "#f44336", 1),
                series(num_min, "Minimum", "#ff9800", 1),
            ]
        ),
        "grid_options": {"columns": FULL},
    }
    power = []
    if immersion_power:
        power.append(
            {
                "type": "custom:apexcharts-card",
                "header": {"show": False},
                "graph_span": "12h",
                "yaxis": [{"min": 0}],
                "apex_config": {**_apex_config(), "stroke": {"curve": "stepline", "width": 2}},
                "series": [series(immersion_power, "Power", "#ff9800", 2)],
                "grid_options": {"columns": FULL},
            }
        )
    return [temperature], power


_HEADER_TITLE = f"""\
# GivEnergy Inverter Manager — Generated Dashboard
# Generated by: Developer Tools → Actions → {DOMAIN}.{SERVICE_GET_DASHBOARD_YAML}
#
"""
_HEADER_POWER_FLOW = """\
# The live power flow requires power-flow-card-plus from HACS:
#   https://github.com/flixlix/power-flow-card-plus
"""
_HEADER_APEX = """\
# The immersion charts require apexcharts-card from HACS:
#   https://github.com/RomRider/apexcharts-card
"""
_HEADER_USE = """\
# All other views use only built-in HA cards.
#
# To use: Settings → Dashboards → new blank dashboard
#         Three-dot menu → Edit dashboard → Raw configuration editor → paste

"""


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


@dataclass
class _Built:
    config: dict
    skipped: list[str] = field(default_factory=list)
    fallbacks: list[str] = field(default_factory=list)


def render_dashboard(
    hass: HomeAssistant, entry_id: str, resources: list[str] | None = None
) -> tuple[str, list[str]]:
    """Return the dashboard YAML text and the names of disabled sensors it left out."""
    built = _generate(hass, entry_id, resources)
    body = _dump_yaml(built.config)
    return _header(built, body) + body, built.skipped


def build_dashboard_yaml(
    hass: HomeAssistant, entry_id: str, resources: list[str] | None = None
) -> str:
    """Return the dashboard as YAML text, with a short header comment."""
    return render_dashboard(hass, entry_id, resources)[0]


def _header(built: _Built, body: str) -> str:
    skipped = built.skipped
    parts = [_HEADER_TITLE]
    if "custom:power-flow-card-plus" in body:
        parts.append(_HEADER_POWER_FLOW)
    if "custom:apexcharts-card" in body:
        parts.append(_HEADER_APEX)
    parts.append(_HEADER_USE)
    if built.fallbacks:
        parts[-1] = parts[-1].rstrip("\n") + "\n"
        parts.append(
            "# Built-in cards are used in place of these HACS cards, which are not installed.\n"
        )
        parts.append("# Install them from HACS, then generate this file again:\n")
        parts.extend(f"#   {name}\n" for name in built.fallbacks)
        parts.append("\n")
    if skipped:
        parts[-1] = parts[-1].rstrip("\n") + "\n"
        parts.append("# Left out because these sensors are disabled. Enable them in\n")
        parts.append("# Settings → Devices & services → Entities, then generate this file again:\n")
        parts.extend(f"#   {name}\n" for name in skipped)
        parts.append("\n")
    return "".join(parts)


def build_dashboard(hass: HomeAssistant, entry_id: str, resources: list[str] | None = None) -> dict:
    return _generate(hass, entry_id, resources).config


def _generate(hass: HomeAssistant, entry_id: str, resources: list[str] | None = None) -> _Built:
    """Build the Lovelace configuration as a dict.

    Uses actual entity IDs from the entity registry so names customised in the HA
    UI are respected. A tile or card appears only when its entity is registered and
    enabled, and the feature behind it (EV charger, immersion heater, inverter
    temperature, solar forecast) is configured.
    """
    b = _Builder(hass, entry_id, resources)
    subviews = [
        _subview(
            "Immersion", "mdi:water-boiler", "immersion", "power-flow", b.immersion_sections()
        ),
        _subview("EV charger", "mdi:ev-station", "ev-charger", "power-flow", b.ev_sections()),
        _subview("Cost breakdown", "mdi:cash-multiple", "cost", "today", b.cost_sections()),
        _subview("Solar and forecast", "mdi:weather-sunny", "solar", "today", b.solar_sections()),
        _subview("Tariff", "mdi:table", "tariff", "bill", b.tariff_sections()),
        _subview(
            "Battery detail",
            "mdi:battery-heart-variant",
            "battery-detail",
            "battery",
            b.battery_detail_sections(),
        ),
    ]
    b.subviews = {v["path"] for v in subviews if v["sections"]}
    views = [
        _view("Power Flow", "mdi:solar-power-variant", "power-flow", b.power_flow_sections()),
        _view("Today", "mdi:calendar-today", "today", b.today_sections()),
        _view("Bill", "mdi:receipt-text", "bill", b.bill_sections()),
        _view("Battery", "mdi:battery-charging", "battery", b.battery_sections()),
        _view("Controls", "mdi:tune", "controls", b.controls_sections()),
    ]
    return _Built(
        {"views": [v for v in views + subviews if v["sections"]]},
        sorted(b.reg.disabled.values()),
        b.fallbacks,
    )


class _Builder:
    """Builds the sections of each view from the entities that exist."""

    def __init__(
        self, hass: HomeAssistant, entry_id: str, resources: list[str] | None = None
    ) -> None:
        self.hass = hass
        self.resources = resources
        self.fallbacks: list[str] = []
        self.subviews: set[str] = set()
        self.reg = _Registry(hass, entry_id)
        self.e = self.reg.get
        cfg = _entry_config(hass, entry_id)
        self.cfg = cfg
        self.external_ev = _external_ev_power(hass)
        self.has_ev = bool(_ev_charger_brand(hass, entry_id) or self.external_ev)
        self.has_immersion = bool(
            cfg.get(CONF_IMMERSION_SWITCH) or cfg.get(CONF_IMMERSION_TEMP_SENSOR)
        )
        self.has_inverter_temp = bool(cfg.get(CONF_INVERTER_TEMP_ENTITY))
        self.has_forecast = bool(cfg.get(CONF_FORECAST_ENTITY))

    def has_card(self, card: str) -> bool:
        """True unless the Lovelace resources are known and do not include this card.

        Unknown resources (None) mean the generator could not read them, in which
        case the custom card is assumed to be there, as it always was.
        """
        if self.resources is None:
            return True
        return any(card in url.lower() for url in self.resources)

    def when(self, flag: bool, suffix: str) -> str | None:  # noqa: FBT001
        return self.e(suffix) if flag else None

    def go(self, path: str) -> dict | None:
        """A tap action to the view at path, or None when that sub-view is empty.

        The tabs always exist. A sub-view is left out when it would be empty.
        """
        if path in _TABS or path in self.subviews:
            return _nav(path)
        return None

    def ev_power(self) -> str | None:
        if not self.has_ev:
            return None
        return _find_ev_charger_power(self.hass, self.e("ev_power"))

    def _flow_entities(self) -> dict:  # noqa: C901
        e = self.e
        out: dict = {}
        if solar_power := e("solar_power"):
            solar: dict = {
                "entity": solar_power,
                "color_icon": False,
                "color_value": False,
                "invert_state": False,
            }
            if is_clipping := e("is_clipping"):
                solar["secondary_info_entity"] = is_clipping
                solar["secondary_info"] = {
                    "template": (
                        f'{{{{- "·⚡Clip" if states("{is_clipping}") == "clipping" else "" }}}}'
                    )
                }
            out["solar"] = solar
        if battery_power := e("battery_power"):
            # The manager's Battery Power is positive while charging. The card reads a
            # positive value as discharging unless it is told to invert it.
            battery: dict = {"entity": battery_power, "invert_state": True}
            if battery_soc := e("battery_soc"):
                battery["state_of_charge"] = battery_soc
                battery["show_state_of_charge"] = True
            out["battery"] = battery
        if grid_power := e("grid_power"):
            grid: dict = {
                "entity": grid_power,
                "use_metadata": False,
                "invert_state": False,
                "display_state": "one_way",
            }
            if live_grid_cost_rate := e("live_grid_cost_rate"):
                grid["secondary_info"] = {
                    "entity": live_grid_cost_rate,
                    "icon": "mdi:cash-clock",
                    "decimals": 4,
                    "display_zero": True,
                    "color_value": False,
                    "unit_of_measurement": " ",
                }
            out["grid"] = grid
        if house_load := e("house_load"):
            out["home"] = {"entity": house_load, "subtract_individual": False, "hide": False}
        individual = _present(
            [
                _row(
                    self.ev_power(),
                    "Car Charger",
                    icon="mdi:car-electric",
                    display_zero=False,
                    color="#4CAF50",
                ),
                _row(
                    self.when(self.has_immersion, "immersion_power"),
                    "Immersion",
                    icon="mdi:water-boiler",
                    display_zero=False,
                    color="#FF9800",
                ),
            ]
        )
        if individual:
            out["individual"] = individual
        return out

    def _now(self) -> list:
        """The numbers worth a glance: charge first, then outlook, rate, cost, cheap rate."""
        e = self.e
        return _block(
            _heading("Now", "mdi:clock-outline"),
            [
                _tile(
                    e("battery_soc"),
                    "Battery",
                    color=BATTERY,
                    features=[_BAR],
                    nav=self.go("battery"),
                    rows=3,
                ),
                _tile(
                    e("night_survival_confidence"),
                    "Night survival",
                    color=NIGHT,
                    nav=self.go("battery-detail"),
                ),
                _tile(e("current_rate"), "Rate now", color=GRID),
                _tile(e("import_cost_today"), "Cost today", color=GRID, nav=self.go("today")),
                _tile(e("next_cheap_rate_start"), "Cheap from", color=GRID),
                _tile(e("hours_to_cheap_rate"), "Cheap in", color=GRID, icon="mdi:timer-outline"),
            ],
        )

    def _flow(self) -> list:
        flow = self._flow_entities()
        if not flow:
            return []
        flow_card = {
            "type": "custom:power-flow-card-plus",
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
        if not self.has_card("power-flow-card-plus"):
            self.fallbacks.append(
                "power-flow-card-plus: https://github.com/flixlix/power-flow-card-plus"
            )
            flow_card = _flow_fallback(flow)
        return _block(
            _heading("Live power flow", "mdi:transmission-tower"),
            [{**flow_card, "grid_options": {"columns": FULL}} if flow_card else None],
        )

    def _totals_and_devices(self) -> list:
        e = self.e
        totals = _block(
            _heading("Energy today", "mdi:lightning-bolt", nav=self.go("today")),
            [
                _tile(e("solar_today"), "Generated", color=SOLAR),
                _tile(e("house_kwh_today"), "Used", color=GRID),
                _tile(e("import_today"), "Imported", color=GRID),
                _tile(e("export_today"), "Exported", color=GRID),
            ],
        )
        devices = _block(
            _heading("Devices", "mdi:power-plug"),
            [
                _tile(
                    self.cfg.get(CONF_IMMERSION_TEMP_SENSOR) or None,
                    "Immersion",
                    color=IMMERSION,
                    icon="mdi:water-boiler",
                    nav=self.go("immersion"),
                )
                if "immersion" in self.subviews
                else None,
                _tile(
                    self.when(self.has_ev, "ev_charger_state"),
                    "EV charger",
                    color=EV,
                    icon="mdi:ev-station",
                    nav=self.go("ev-charger"),
                )
                if "ev-charger" in self.subviews
                else None,
            ],
        )
        return [*totals, *devices]

    def power_flow_sections(self) -> list:
        return _present(
            [_section(self._now()), _section(self._flow()), _section(self._totals_and_devices())]
        )

    def immersion_sections(self) -> list:
        """Sub-view: the water temperature and power charts and why the heater is on or off."""
        if not self.has_immersion:
            return []
        temps, power = _immersion_charts(
            self.cfg.get(CONF_IMMERSION_TEMP_SENSOR, ""),
            self.e("immersion_target_temp"),
            self.e("immersion_min_temp"),
            self.e("immersion_today"),
            apex=self.has_card("apexcharts-card"),
            immersion_power=self.e("immersion_power"),
        )
        if (temps or power) and not self.has_card("apexcharts-card"):
            self.fallbacks.append("apexcharts-card: https://github.com/RomRider/apexcharts-card")
        reason = self.e("immersion_divert_reason")
        e = self.e
        return [
            _section(
                _block(_heading("Water temperature", "mdi:thermometer-water"), temps),
                _block(
                    _heading("Why", "mdi:help-circle-outline", subtitle=True),
                    [_markdown(f"{{{{ states('{reason}') }}}}") if reason else None],
                ),
            ),
            _section(_block(_heading("Heater power", "mdi:flash"), power)),
            _section(
                _block(
                    _heading("Today", "mdi:calendar-today"),
                    [
                        _tile(e("immersion_today"), "Energy", color=IMMERSION),
                        _tile(e("immersion_cost_today"), "Cost", color=GRID),
                        _tile(e("immersion_savings_today"), "Saved by solar", color=BATTERY),
                    ],
                )
            ),
        ]

    def ev_sections(self) -> list:
        """Sub-view: the EV charger's state and why it is or is not charging."""
        when, ev = self.when, self.has_ev
        decision = when(ev, "ev_protection_reason")
        return [
            _section(
                _block(
                    _heading("Charging now", "mdi:ev-station"),
                    [
                        _tile(when(ev, "ev_charger_state"), "Charger state", color=EV),
                        _tile(self.ev_power(), "Charge power", color=EV),
                        _tile(when(ev, "ev_session_energy"), "Session energy", color=EV),
                        _tile(when(ev, "ev_charging_source"), "Charging source", color=EV),
                    ],
                )
            ),
            _section(
                _block(
                    _heading("Why", "mdi:help-circle-outline"),
                    [
                        _tile(when(ev, "ev_draining_battery"), "Drains battery", color=BATTERY),
                        _tile(when(ev, "ev_solar_surplus_available"), "Solar surplus", color=SOLAR),
                        _markdown(f"{{{{ states('{decision}') }}}}") if decision else None,
                    ],
                )
            ),
        ]

    def today_sections(self) -> list:
        e, when = self.e, self.when
        return [
            _section(
                _block(
                    _heading("Energy", "mdi:lightning-bolt"),
                    [
                        _tile(e("solar_today"), "Generated", color=SOLAR),
                        _tile(e("house_kwh_today"), "Used", color=GRID),
                        _tile(e("import_today"), "Imported", color=GRID),
                        _tile(e("export_today"), "Exported", color=GRID),
                        _tile(when(self.has_ev, "zappi_today"), "EV", color=EV),
                        _tile(
                            when(self.has_immersion, "immersion_today"),
                            "Immersion",
                            color=IMMERSION,
                        ),
                    ],
                )
            ),
            _section(
                _block(
                    _heading("Cost", "mdi:cash-multiple", nav=self.go("cost")),
                    [
                        _tile(e("import_cost_today"), "Import cost", color=GRID),
                        _tile(e("export_earnings_today"), "Export earnings", color=BATTERY),
                        _tile(e("current_rate"), "Rate now", color=GRID),
                        _tile(e("current_rate_period"), "Rate period", color=GRID),
                    ],
                )
            ),
            _section(
                _block(
                    _heading("Solar", "mdi:weather-sunny", nav=self.go("solar")),
                    [
                        _tile(
                            e("self_sufficiency"),
                            "Self-sufficiency",
                            columns=FULL,
                            color=SOLAR,
                            features=[_BAR],
                        ),
                        _tile(
                            e("self_consumption"),
                            "Self-consumption",
                            columns=FULL,
                            color=SOLAR,
                            features=[_BAR],
                        ),
                    ],
                )
            ),
        ]

    def cost_sections(self) -> list:
        """Sub-view: every cost line for today and the cost per day for two weeks."""
        e, when = self.e, self.when
        import_cost_today = e("import_cost_today")
        export_earnings = e("export_earnings_today")
        house_cost_today = e("house_cost_today")
        zappi_cost_today = when(self.has_ev, "zappi_cost_today")
        immersion_cost_today = when(self.has_immersion, "immersion_cost_today")
        return [
            _section(
                _block(
                    _heading("Today", "mdi:calendar-today"),
                    [
                        _tile(import_cost_today, "Grid import", color=GRID),
                        _tile(export_earnings, "Export earnings", color=BATTERY),
                        _tile(house_cost_today, "Rest of house", color=GRID),
                        _tile(zappi_cost_today, "EV charging", color=EV),
                        _tile(immersion_cost_today, "Immersion", color=IMMERSION),
                        _tile(
                            when(self.has_immersion, "immersion_savings_today"),
                            "Saved by solar",
                            color=BATTERY,
                        ),
                    ],
                )
            ),
            _section(
                _block(
                    _heading("Last 14 days", "mdi:chart-bar"),
                    [
                        _statistics_graph(
                            [
                                _row(import_cost_today, "Grid Import"),
                                _row(house_cost_today, "Rest of House"),
                                _row(zappi_cost_today, "EV Charging"),
                                _row(immersion_cost_today, "Immersion"),
                                _row(export_earnings, "Export Earnings"),
                            ],
                            "day",
                            14,
                        )
                    ],
                )
            ),
        ]

    def solar_sections(self) -> list:
        """Sub-view: how solar compares with the forecast and the generation per hour."""
        solar_today = self.e("solar_today")
        forecast = (
            [
                _tile(solar_today, "Generated today", color=SOLAR),
                _tile(self.e("solar_forecast_kwh_today"), "Forecast today", color=SOLAR),
                _tile(self.e("solar_actual_vs_forecast_pct"), "Tracking", color=SOLAR),
                _tile(self.e("yesterday_forecast_accuracy_pct"), "Yesterday", color=SOLAR),
            ]
            if self.has_forecast
            else []
        )
        return [
            _section(_block(_heading("Against the forecast", "mdi:chart-line"), forecast)),
            _section(
                _block(
                    _heading("Generation per hour", "mdi:chart-bar"),
                    [_statistics_graph([_row(solar_today, "Actual")], "hour", 2)],
                )
            ),
        ]

    def bill_sections(self) -> list:
        """The month so far and the tariff the sums use, to compare with a real bill."""
        e = self.e
        tariff = self.go("tariff")
        badges = (
            [{"type": "button", "icon": "mdi:table", "text": "Tariff", "tap_action": tariff}]
            if tariff
            else None
        )
        return [
            _section(
                _block(
                    _heading("Bill so far", "mdi:receipt-text", badges=badges),
                    [
                        _tile(e("accrued_bill"), "Accrued bill", color=GRID),
                        _tile(e("projected_bill"), "Projected bill", color=GRID),
                        _tile(e("import_cost_this_month"), "Import cost", color=GRID),
                        _tile(e("export_earnings_this_month"), "Export credit", color=BATTERY),
                    ],
                )
            ),
            _section(
                _block(
                    _heading("This bill period", "mdi:calendar-month"),
                    [
                        _tile(e("days_in_period"), "Days elapsed"),
                        _tile(e("days_remaining_in_period"), "Days left"),
                        _tile(e("avg_import_rate_this_month"), "Avg import rate", color=GRID),
                        _tile(e("cheap_import_fraction_this_month"), "Cheap share", color=GRID),
                    ],
                )
            ),
        ]

    def tariff_sections(self) -> list:
        """Sub-view: the rates and charges the bill sums use."""
        return [
            _section(
                _block(
                    _heading("Tariff in use", "mdi:table"),
                    [_markdown(_tariff_table(build_tariff(self.cfg), self.cfg))],
                )
            )
        ]

    def battery_sections(self) -> list:
        e = self.e
        battery_soc = e("battery_soc")
        history = _entity_list_card(
            [_row(battery_soc, "Charge")],
            {"type": "history-graph"},
            hours_to_show=24,
        )
        return [
            _section(
                _block(
                    _heading(
                        "Battery", "mdi:battery-heart-variant", nav=self.go("battery-detail")
                    ),
                    [
                        _tile(battery_soc, "Charge", color=BATTERY, features=[_BAR]),
                        _tile(e("battery_power"), "Power", color=BATTERY, features=[_TREND]),
                        _graph(history) if history else None,
                    ],
                )
            ),
            _section(
                _block(
                    _heading("Tonight's charge plan", "mdi:weather-night"),
                    [
                        _tile(e("overnight_charge_target"), "Target tonight", color=BATTERY),
                        _tile(e("overnight_charge_cost"), "Est. cost", color=GRID),
                        _tile(e("estimated_soc_at_sunrise"), "At sunrise", color=BATTERY),
                        _tile(
                            e("cheap_rate_floor_status"),
                            "Rate floor",
                            color=GRID,
                            icon="mdi:floor-plan",
                        ),
                    ],
                )
            ),
        ]

    def battery_detail_sections(self) -> list:
        """Sub-view: why tonight's plan is what it is, and the battery's health."""
        e, when = self.e, self.when
        has_temp = self.has_inverter_temp
        return [
            _section(
                _block(_heading("Night survival", "mdi:weather-night"), self._night_survival()),
                _block(
                    _heading("Tonight's charge target", "mdi:battery-charging", subtitle=True),
                    self._charge_reason(),
                ),
            ),
            _section(
                _block(
                    _heading("Battery health", "mdi:battery-heart-variant"),
                    [
                        _tile(e("battery_cycles"), "Total cycles", color=BATTERY),
                        _tile(e("battery_remaining_life"), "Life remaining", color=BATTERY),
                        _tile(
                            e("days_since_full_charge"),
                            "Since full",
                            color=BATTERY,
                            icon="mdi:battery-check",
                        ),
                        _tile(when(has_temp, "inverter_temperature"), "Inverter temp", color=GRID),
                        _tile(
                            when(has_temp, "inverter_temperature_status"),
                            "Inverter status",
                            color=GRID,
                            icon="mdi:thermometer-alert",
                        ),
                    ],
                )
            ),
        ]

    def _night_survival(self) -> list:
        """The night survival level in bold, then why, in words.

        The confidence sensor carries the level. Its explanation attribute is used when
        it has one. Without it a sentence is chosen by level: Warning is explained from
        the estimated state of charge at sunrise, and Safe and Critical show the status
        sensor's text, which carries any kWh shortfall.
        """
        level = self.e("night_survival_confidence")
        status = self.e("night_survival_reason")
        sunrise = self.e("estimated_soc_at_sunrise")
        if not level:
            if not status:
                return []
            return [_markdown(f"**Night survival**\n\n{{{{ states('{status}') }}}}")]
        status_text = f"{{{{ states('{status}') }}}}" if status else ""
        if sunrise:
            reached = (
                f"{{% if has_value('{sunrise}') %}}about "
                f"{{{{ states('{sunrise}') | float(0) | round(0) | int }}}}% at sunrise"
                "{% else %}the minimum at sunrise{% endif %}"
            )
        else:
            reached = "the minimum at sunrise"
        warning = (
            "The battery should last until solar starts, but only just. "
            f"It is expected to reach {reached}, close to your minimum charge. "
            "A warning shows when the estimate is within 5 points of the minimum."
        )
        content = (
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
        return [_markdown(content)]

    def _charge_reason(self) -> list:
        """The reason for tonight's charge target is a sentence, so it gets a markdown card."""
        reason = self.e("overnight_charge_reason")
        return [_markdown(f"{{{{ states('{reason}') }}}}")] if reason else []

    def _dry_run_section(self) -> dict | None:
        """A banner, shown only while Dry Run Mode Active is true."""
        dry_run_active = self.e("dry_run_active")
        if not dry_run_active:
            return None
        text = (
            "No commands are sent to your inverter or EV charger. Sensors and charge "
            "decisions still update. To go live, turn off Dry Run in Settings, Devices & "
            "services, GivEnergy Inverter Manager, Configure."
        )
        if skipped := self.e("dry_run_last_skipped"):
            text += f"\n\n**Last skipped action:** {{{{ states('{skipped}') }}}}"
        return _section(
            _block(_heading("Dry run is on", "mdi:test-tube"), [_markdown(text)]),
            visibility=[{"condition": "state", "entity": dry_run_active, "state": "True"}],
        )

    def controls_sections(self) -> list:
        e, when = self.e, self.when
        imm = self.has_immersion
        reason = when(imm, "immersion_divert_reason")
        return [
            self._dry_run_section(),
            _section(
                _block(
                    _heading("Overnight charging", "mdi:battery-charging"),
                    [
                        _tile(
                            e("charge_target_override"),
                            "Charge target",
                            columns=FULL,
                            color=BATTERY,
                            features=[_SLIDER],
                        ),
                        _tile(
                            e("charge_target_override_enabled"),
                            "Use target",
                            color=BATTERY,
                            features=[_TOGGLE],
                            inline=True,
                        ),
                        _tile(
                            e("skip_charge_override"),
                            "Skip tonight",
                            color=BATTERY,
                            features=[_TOGGLE],
                            inline=True,
                        ),
                    ],
                )
            ),
            _section(
                _block(
                    _heading("Immersion heater", "mdi:water-boiler"),
                    [
                        _tile(
                            when(imm, "auto_immersion"),
                            "Auto divert",
                            color=IMMERSION,
                            features=[_TOGGLE],
                            inline=True,
                        ),
                        _tile(
                            when(imm, "immersion_managed"),
                            "Managed",
                            color=IMMERSION,
                            features=[_TOGGLE],
                            inline=True,
                        ),
                        _markdown(f"{{{{ states('{reason}') }}}}") if reason else None,
                        _tile(
                            when(imm, "immersion_target_temp"),
                            "Target temp",
                            columns=FULL,
                            color=IMMERSION,
                            features=[_SLIDER],
                        ),
                        _tile(
                            when(imm, "immersion_min_temp"),
                            "Minimum temp",
                            columns=FULL,
                            color=IMMERSION,
                            features=[_SLIDER],
                        ),
                        _tile(
                            when(imm, "immersion_hysteresis"),
                            "Restart gap",
                            columns=FULL,
                            color=IMMERSION,
                            features=[_SLIDER],
                        ),
                    ],
                )
            ),
        ]


_TABS = {"power-flow", "today", "bill", "battery", "controls"}


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


def _find_entry(hass: HomeAssistant, entry_id: str):
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == entry_id:
            return entry
    return None


def _entry_config(hass: HomeAssistant, entry_id: str) -> dict:
    """Return the config entry's data with options layered over it."""
    entry = _find_entry(hass, entry_id)
    return {**entry.data, **entry.options} if entry else {}


def _ev_charger_brand(hass: HomeAssistant, entry_id: str) -> str | None:
    """Brand of the EV charger the coordinator discovered, if any."""
    entry = _find_entry(hass, entry_id)
    return getattr(getattr(entry, "runtime_data", None), "ev_charger_brand", None)
