"""
dashboard_builder.py - builds the Lovelace dashboard for GivEnergy Inverter Manager.

The dashboard is built as a plain dict, then serialised with PyYAML. The
get_dashboard_yaml service writes the YAML to a file.

The generated dashboard has five views:
  1. Power Flow   - a Now strip and the live energy flow (power-flow-card-plus from HACS)
  2. Today        - daily energy totals, cost breakdown, self-sufficiency
  3. Bill         - the month so far and the tariff behind it
  4. Battery      - battery health, charge decision, night survival
  5. Controls     - charge target slider, switches, EV charger state

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


def _find_ev_charger_power(hass: HomeAssistant, integration_ev_power: str) -> str:
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


def _apex_config() -> dict:
    return {
        "chart": {"height": 150, "zoom": {"enabled": False}},
        "tooltip": {"shared": True, "followCursor": True},
        "stroke": {"curve": "smooth", "width": 2},
        "markers": {"size": 0, "hover": {"size": 5}},
        "legend": {"show": False},
    }


def _present(items: list) -> list:
    return [item for item in items if item is not None]


def _row(entity: str | None, name: str, **extra) -> dict | None:
    """An entities-card or glance row, or None when the entity is unusable."""
    if not entity:
        return None
    return {"entity": entity, "name": name, **extra}


def _tile(entity: str | None, name: str, **extra) -> dict | None:
    if not entity:
        return None
    return {"type": "tile", "entity": entity, "name": name, "vertical": True, **extra}


def _statistics_graph(rows: list, title: str, period: str, days: int) -> dict | None:
    """Bars of the change in each period, for sensors that reset every day.

    A history graph of such a sensor draws a sawtooth that falls to zero at midnight.
    The daily sensors keep long-term statistics, so the change per period is exact.
    """
    return _entity_list_card(
        rows,
        {"type": "statistics-graph", "title": title},
        chart_type="bar",
        period=period,
        days_to_show=days,
        stat_types=["change"],
    )


def _entity_list_card(rows: list, head: dict, **tail) -> dict | None:
    """A card built from rows. None when no row points at an entity."""
    rows = _present(rows)
    if not any("entity" in r for r in rows):
        return None
    return {**head, "entities": rows, **tail}


def _build_immersion_section(
    immersion_temp_sensor: str,
    immersion_reason: str | None,
    num_target: str | None,
    num_min: str | None,
    immersion_today: str | None,
    apex: bool = True,
) -> dict | None:
    """Build the immersion block for the power flow view.

    A vertical-stack of a 12 hour temperature chart (water, target, minimum),
    a tile with the divert reason and a 12 hour chart of immersion energy today.
    Returns None when no immersion temperature sensor is configured.
    Requires apexcharts-card from HACS. With apex=False the charts are built-in
    cards instead: a history graph of the temperatures and a statistics graph of
    immersion energy per hour.
    """
    if not immersion_temp_sensor:
        return None
    if not apex:
        return _immersion_section_built_in(
            immersion_temp_sensor, immersion_reason, num_target, num_min, immersion_today
        )

    def series(entity: str | None, name: str, color: str, width: int) -> dict | None:
        if not entity:
            return None
        return {"entity": entity, "name": name, "color": color, "stroke_width": width}

    cards: list = [
        {
            "type": "custom:apexcharts-card",
            "header": {"show": True, "title": "Immersion Temperature (12h)"},
            "graph_span": "12h",
            "apex_config": _apex_config(),
            "series": _present(
                [
                    series(immersion_temp_sensor, "Water", "#03a9f4", 2),
                    series(num_target, "Target", "#f44336", 1),
                    series(num_min, "Minimum", "#ff9800", 1),
                ]
            ),
        }
    ]
    if immersion_reason:
        cards.append(
            {
                "type": "tile",
                "entity": immersion_reason,
                "name": " ",
                "show_entity_picture": False,
                "hide_state": False,
                "vertical": False,
                "features_position": "bottom",
            }
        )
    if immersion_today:
        cards.append(
            {
                "type": "custom:apexcharts-card",
                "header": {"show": True, "title": "Power"},
                "graph_span": "12h",
                "yaxis": [{"min": 0}],
                "apex_config": _apex_config(),
                "series": [series(immersion_today, "Immersion Power Today", "#03a9f4", 2)],
            }
        )
    return {"type": "vertical-stack", "cards": cards}


def _immersion_section_built_in(
    immersion_temp_sensor: str,
    immersion_reason: str | None,
    num_target: str | None,
    num_min: str | None,
    immersion_today: str | None,
) -> dict:
    cards = _present(
        [
            _entity_list_card(
                [
                    _row(immersion_temp_sensor, "Water"),
                    _row(num_target, "Target"),
                    _row(num_min, "Minimum"),
                ],
                {"type": "history-graph", "title": "Immersion Temperature (12h)"},
                hours_to_show=12,
            ),
            _tile(immersion_reason, " ", vertical=False) if immersion_reason else None,
            _statistics_graph(
                [_row(immersion_today, "Immersion")], "Immersion energy per hour", "hour", 1
            ),
        ]
    )
    return {"type": "vertical-stack", "cards": cards}


_HEADER_TITLE = f"""\
# GivEnergy Inverter Manager — Generated Dashboard
# Generated by: Developer Tools → Actions → {DOMAIN}.{SERVICE_GET_DASHBOARD_YAML}
#
"""
_HEADER_POWER_FLOW = """\
# View 1 (Power Flow) requires power-flow-card-plus from HACS:
#   https://github.com/flixlix/power-flow-card-plus
"""
_HEADER_APEX = """\
# Immersion section requires apexcharts-card from HACS:
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
    UI are respected. A row or card appears only when its entity is registered and
    enabled, and the feature behind it (EV charger, immersion heater, inverter
    temperature, solar forecast) is configured.
    """
    b = _Builder(hass, entry_id, resources)
    views = [
        {
            "title": "Power Flow",
            "icon": "mdi:solar-power-variant",
            "path": "power-flow",
            "cards": b.power_flow_cards(),
        },
        {
            "title": "Today",
            "icon": "mdi:calendar-today",
            "path": "today",
            "cards": b.today_cards(),
        },
        {
            "title": "Bill",
            "icon": "mdi:receipt-text",
            "path": "bill",
            "cards": b.bill_cards(),
        },
        {
            "title": "Battery",
            "icon": "mdi:battery-charging",
            "path": "battery",
            "cards": b.battery_cards(),
        },
        {
            "title": "Controls",
            "icon": "mdi:tune",
            "path": "controls",
            "cards": b.controls_cards(),
        },
    ]
    return _Built(
        {"views": [v for v in views if v["cards"]]},
        sorted(b.reg.disabled.values()),
        b.fallbacks,
    )


class _Builder:
    """Builds the cards of each view from the entities that exist."""

    def __init__(
        self, hass: HomeAssistant, entry_id: str, resources: list[str] | None = None
    ) -> None:
        self.resources = resources
        self.fallbacks: list[str] = []
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

    def when(self, flag: bool, suffix: str) -> str | None:
        return self.e(suffix) if flag else None

    def ev_power(self) -> str | None:
        if not self.has_ev:
            return None
        return self.external_ev or self.e("ev_power")

    def _flow_entities(self) -> dict:
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
            battery: dict = {"entity": battery_power}
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

    def now_strip(self) -> dict | None:
        """The few numbers worth a glance: charge, tonight's outlook, next cheap rate, cost."""
        e = self.e
        soc = e("battery_soc")
        cards = _present(
            [
                {
                    "type": "gauge",
                    "entity": soc,
                    "name": "Battery",
                    "min": 0,
                    "max": 100,
                    "needle": True,
                    "severity": {"green": 50, "yellow": 20, "red": 0},
                }
                if soc
                else None,
                _tile(e("night_survival_confidence"), "Night survival"),
                _tile(e("current_rate"), "Rate now"),
                _tile(e("next_cheap_rate_start"), "Cheap rate starts"),
                _tile(e("hours_to_cheap_rate"), "Hours to cheap rate"),
                _tile(e("import_cost_today"), "Cost today"),
            ]
        )
        if not cards:
            return None
        return {"type": "grid", "title": "Now", "columns": 3, "square": False, "cards": cards}

    def power_flow_cards(self) -> list:
        flow = self._flow_entities()
        immersion_today = self.when(self.has_immersion, "immersion_today")
        flow_card = {
            "type": "custom:power-flow-card-plus",
            "entities": flow,
            "title": "Live Power Flow",
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
        use_flow_card = self.has_card("power-flow-card-plus")
        use_apex = self.has_card("apexcharts-card")
        immersion_section = _build_immersion_section(
            self.cfg.get(CONF_IMMERSION_TEMP_SENSOR, ""),
            self.when(self.has_immersion, "immersion_divert_reason"),
            self.when(self.has_immersion, "immersion_target_temp"),
            self.when(self.has_immersion, "immersion_min_temp"),
            immersion_today,
            apex=use_apex,
        )
        if not use_flow_card:
            self.fallbacks.append(
                "power-flow-card-plus: https://github.com/flixlix/power-flow-card-plus"
            )
            flow_card = _flow_fallback(flow)
        if immersion_section is not None and not use_apex:
            self.fallbacks.append("apexcharts-card: https://github.com/RomRider/apexcharts-card")
        return _present(
            [
                self.now_strip(),
                flow_card if flow else None,
                _entity_list_card(
                    [
                        _row(self.e("solar_today"), "Generated"),
                        _row(self.e("import_today"), "Imported"),
                        _row(self.e("export_today"), "Exported"),
                        _row(self.e("house_kwh_today"), "Used"),
                        _row(immersion_today, "Immersion"),
                    ],
                    {
                        "show_name": True,
                        "show_icon": True,
                        "show_state": True,
                        "type": "glance",
                        "title": "Energy Today",
                        "columns": 5,
                    },
                ),
                immersion_section,
            ]
        )

    def today_cards(self) -> list:
        e, when = self.e, self.when
        solar_today = e("solar_today")
        import_cost_today = e("import_cost_today")
        export_earnings = e("export_earnings_today")
        house_cost_today = e("house_cost_today")
        zappi_cost_today = when(self.has_ev, "zappi_cost_today")
        immersion_cost_today = when(self.has_immersion, "immersion_cost_today")
        return _present(
            [
                _entity_list_card(
                    [
                        _row(solar_today, "Generated"),
                        _row(e("import_today"), "Import"),
                        _row(e("export_today"), "Export"),
                        _row(when(self.has_ev, "zappi_today"), "EV"),
                        _row(when(self.has_immersion, "immersion_today"), "Immersion"),
                    ],
                    {
                        "show_name": True,
                        "show_icon": True,
                        "show_state": True,
                        "type": "glance",
                        "title": "Energy Today",
                    },
                ),
                _entity_list_card(
                    [
                        _row(e("current_rate"), "Current Rate"),
                        _row(e("current_rate_period"), "Rate Period"),
                        {"type": "divider"},
                        _row(import_cost_today, "Import Cost"),
                        _row(export_earnings, "Export Earnings"),
                        _row(zappi_cost_today, "EV Charging Cost"),
                        _row(immersion_cost_today, "Immersion Cost"),
                        _row(
                            when(self.has_immersion, "immersion_savings_today"), "Immersion Savings"
                        ),
                        _row(house_cost_today, "Rest-of-House Cost"),
                    ],
                    {"type": "entities"},
                    title="Cost Breakdown",
                ),
                _statistics_graph(
                    [
                        _row(import_cost_today, "Grid Import"),
                        _row(house_cost_today, "Rest of House"),
                        _row(zappi_cost_today, "EV Charging"),
                        _row(immersion_cost_today, "Immersion"),
                        _row(export_earnings, "Export Earnings"),
                    ],
                    "Cost per day",
                    "day",
                    14,
                ),
                _statistics_graph(
                    [_row(solar_today, "Actual")],
                    "Solar generation per hour",
                    "hour",
                    2,
                ),
                self._forecast_card(solar_today),
                _grid_of_gauges(
                    [
                        (
                            e("self_sufficiency"),
                            "Self-Sufficiency",
                            {"green": 60, "yellow": 30, "red": 0},
                        ),
                        (
                            e("self_consumption"),
                            "Self-Consumption",
                            {"green": 70, "yellow": 40, "red": 0},
                        ),
                    ]
                ),
            ]
        )

    def _forecast_card(self, solar_today: str | None) -> dict | None:
        if not self.has_forecast:
            return None
        return _entity_list_card(
            [
                _row(solar_today, "Generated today"),
                _row(self.e("solar_forecast_kwh_today"), "Today's forecast"),
                _row(self.e("solar_actual_vs_forecast_pct"), "Tracking", icon="mdi:chart-line"),
                _row(self.e("yesterday_forecast_accuracy_pct"), "Yesterday's accuracy"),
            ],
            {"type": "entities", "title": "Solar vs Forecast"},
        )

    def bill_cards(self) -> list:
        """The month so far and the tariff the sums use, to compare with a real bill."""
        e = self.e
        return _present(
            [
                _entity_list_card(
                    [
                        _row(e("import_cost_this_month"), "Import cost this month"),
                        _row(e("export_earnings_this_month"), "Export earnings this month"),
                        _row(e("accrued_bill"), "Accrued bill this period"),
                        _row(e("projected_bill"), "Projected bill this period"),
                    ],
                    {"type": "entities"},
                    title="Bill so far",
                    show_header_toggle=False,
                    state_color=False,
                ),
                _entity_list_card(
                    [
                        _row(e("days_in_period"), "Days elapsed"),
                        _row(e("days_remaining_in_period"), "Days remaining"),
                    ],
                    {"type": "entities"},
                    title="Bill period",
                    show_header_toggle=False,
                    state_color=False,
                ),
                _entity_list_card(
                    [
                        _row(e("avg_import_rate_this_month"), "Average import rate this month"),
                        _row(e("cheap_import_fraction_this_month"), "Cheap rate share of import"),
                    ],
                    {"type": "entities"},
                    title="Import mix this month",
                    show_header_toggle=False,
                    state_color=False,
                ),
                {
                    "type": "markdown",
                    "title": "Tariff in use",
                    "content": _tariff_table(build_tariff(self.cfg), self.cfg),
                },
            ]
        )

    def battery_cards(self) -> list:
        e, when = self.e, self.when
        battery_soc = e("battery_soc")
        battery_power = e("battery_power")
        has_temp = self.has_inverter_temp
        gauge = {
            "type": "gauge",
            "entity": battery_soc,
            "name": "Battery SoC",
            "min": 0,
            "max": 100,
            "needle": True,
            "severity": {"green": 50, "yellow": 20, "red": 0},
        }
        return _present(
            [
                gauge if battery_soc else None,
                _entity_list_card(
                    [_row(battery_soc, "SoC"), _row(battery_power, "Power (W)")],
                    {"type": "history-graph", "title": "Battery SoC — 24h", "hours_to_show": 24},
                ),
                _entity_list_card(
                    [
                        _row(battery_power, "Charge / Discharge Power"),
                        _row(e("overnight_charge_target"), "Recommended Target Tonight"),
                        _row(e("overnight_charge_cost"), "Estimated Charge Cost"),
                        _row(e("estimated_soc_at_sunrise"), "Estimated SoC at Sunrise"),
                        _row(
                            e("cheap_rate_floor_status"), "Cheap Rate Floor", icon="mdi:floor-plan"
                        ),
                    ],
                    {"type": "entities"},
                    title="Tonight's Charge Plan",
                ),
                self._tonight_notes(),
                _entity_list_card(
                    [
                        _row(e("battery_cycles"), "Total Cycles"),
                        _row(e("battery_remaining_life"), "Estimated Life Remaining"),
                        _row(e("days_since_full_charge"), "Days Since Full Charge"),
                        _row(when(has_temp, "inverter_temperature"), "Inverter Temperature"),
                        _row(
                            when(has_temp, "inverter_temperature_status"),
                            "Inverter Status",
                            icon="mdi:thermometer-alert",
                        ),
                    ],
                    {"type": "entities"},
                    title="Battery Health",
                ),
            ]
        )

    def _tonight_notes(self) -> dict | None:
        """The charge reason and night survival status are sentences, so they get a card."""
        sections = [
            (name, entity)
            for name, entity in (
                ("Why this charge target", self.e("overnight_charge_reason")),
                ("Night survival", self.e("night_survival_reason")),
            )
            if entity
        ]
        if not sections:
            return None
        content = "\n\n".join(
            f"**{name}**\n\n{{{{ states('{entity}') }}}}" for name, entity in sections
        )
        return {"type": "markdown", "title": "Tonight in words", "content": content}

    def _dry_run_cards(self) -> list:
        dry_run_active = self.e("dry_run_active")
        if not dry_run_active:
            return []
        condition = [{"condition": "state", "entity": dry_run_active, "state": "True"}]
        banner = {
            "type": "markdown",
            "content": (
                "## ⚠️ Dry Run Mode Active\n"
                "\n"
                "This integration is in **simulation mode**. All sensor values update "
                "normally and charge decisions are calculated, but **no commands are "
                "sent to your inverter or EV charger**.\n"
                "\n"
                "To go live, disable Dry Run in Settings → Integrations → GivEnergy "
                "Inverter Manager → Configure."
            ),
        }
        status = _entity_list_card(
            [
                _row(dry_run_active, "Dry Run Mode", icon="mdi:test-tube"),
                _row(
                    self.e("dry_run_last_skipped"),
                    "Last Skipped Action",
                    icon="mdi:skip-next-circle-outline",
                ),
            ],
            {"type": "entities", "title": "Dry Run Status"},
        )
        return [{"type": "conditional", "conditions": condition, "card": banner}] + (
            [{"type": "conditional", "conditions": condition, "card": status}] if status else []
        )

    def controls_cards(self) -> list:
        e, when = self.e, self.when
        imm = self.has_immersion
        return self._dry_run_cards() + _present(
            [
                _entity_list_card(
                    [
                        _row(e("charge_target_override_enabled"), "Enable Charge Target Override"),
                        _row(e("charge_target_override"), "Overnight Charge Target"),
                        _row(e("skip_charge_override"), "Force Skip Charge Tonight"),
                    ],
                    {"type": "entities"},
                    title="Overnight Charging",
                ),
                _entity_list_card(
                    [
                        _row(when(imm, "auto_immersion"), "Auto Immersion Divert"),
                        _row(when(imm, "immersion_managed"), "Immersion Heater (Managed)"),
                        _row(
                            when(imm, "immersion_divert_reason"),
                            "Divert Reason",
                            icon="mdi:water-boiler",
                        ),
                        {"type": "divider"},
                        _row(when(imm, "immersion_target_temp"), "Target Temperature"),
                        _row(when(imm, "immersion_min_temp"), "Minimum Temperature"),
                        _row(when(imm, "immersion_hysteresis"), "Restart Gap"),
                    ],
                    {"type": "entities"},
                    title="Immersion Heater",
                ),
                self._ev_card(),
            ]
        )

    def _ev_card(self) -> dict | None:
        when, ev = self.when, self.has_ev
        return _entity_list_card(
            [
                _row(when(ev, "ev_charger_state"), "Charger State", icon="mdi:ev-station"),
                _row(self.ev_power(), "Charge Power", icon="mdi:lightning-bolt"),
                _row(when(ev, "ev_session_energy"), "Session Energy"),
                _row(when(ev, "ev_draining_battery"), "Draining Battery"),
                _row(
                    when(ev, "ev_protection_reason"),
                    "Mode Decision",
                    icon="mdi:car-electric",
                ),
                _row(when(ev, "ev_charging_source"), "Charging Source"),
                _row(when(ev, "ev_solar_surplus_available"), "Solar Surplus Available"),
            ],
            {"type": "entities"},
            title="EV Charger",
        )


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
    return _entity_list_card(rows, {"type": "entities"}, title="Live Power")


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


def _grid_of_gauges(gauges: list[tuple[str | None, str, dict]]) -> dict | None:
    cards = [
        {
            "type": "gauge",
            "entity": entity,
            "name": name,
            "min": 0,
            "max": 100,
            "severity": severity,
        }
        for entity, name, severity in gauges
        if entity
    ]
    if not cards:
        return None
    return {
        "square": False,
        "type": "grid",
        "columns": 2,
        "cards": cards,
        "title": "Self Sufficiency",
    }


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
