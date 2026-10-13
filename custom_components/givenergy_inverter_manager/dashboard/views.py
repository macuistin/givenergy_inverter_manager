"""
views.py - the tabs and sub-views of the dashboard, and the Builder that fills them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from ..const import (
    ATTR_FULL_TEXT,
    CONF_FORECAST_ENTITY,
    CONF_INVERTER_TEMP_ENTITY,
)
from ..core.devices import Device
from ..core.tariff import (
    build_tariff,
    last_tariff_review,
    scheduled_tariff_changes,
    tariff_in_force,
)
from ..inverter.givtcp.discovery import device_prefix, temperature_entity_ids_for
from .cards import (
    BAR,
    BATTERY,
    EV,
    FULL,
    GRID,
    HEX,
    IMMERSION,
    NIGHT,
    SOLAR,
    TREND,
    WHOLE_WIDTH,
    WIDE,
    admin_condition,
    attribute_markdown,
    button_badge,
    entity_list_card,
    entity_row,
    graph_card,
    grid_section,
    group,
    heading_block,
    heading_card,
    logbook_card,
    markdown_card,
    navigate_action,
    present,
    readonly_tile,
    stacked_hourly_graph,
    state_markdown,
    state_ref,
    statistics_graph,
    stepper_tile,
    subheading_card,
    tile_card,
    toggle_tile,
    view_config,
)
from .charts import (
    ImmersionEntities,
    apex_immersion_chart,
    builtin_immersion_chart,
    flow_card,
    flow_fallback,
)
from .devices import Devices, with_visibility
from .hacs import APEX_CARD, POWER_FLOW_CARD, HacsCards
from .registry import HostFacts, Registry, entry_config, external_ev_power
from .templates import (
    MANAGED_HELP,
    PLAN_FORECAST_CAPTION,
    RESTART_GAP_HELP,
    EnergySources,
    alt_heat_schedule_template,
    cheapest_source_template,
    currency_symbol,
    energy_devices_template,
    energy_sources_template,
    planned_heating_template,
    ready_by_template,
    setup_checklist_template,
    survival_template,
    tariff_changes_table,
    tariff_table,
)

# ── View paths ───────────────────────────────────────────────────────────────
# A tab is a view with a tab. A sub-view has none: a tile, heading or button on a tab opens it
# and its back arrow returns to that tab. The detail of a tab sits lower on the tab, so only
# the devices and Settings have a sub-view. Settings is the one only administrators see.
# The Now tab keeps the path it had as Power Flow, so a saved link still opens it.
TAB_NOW = "power-flow"
TAB_TODAY = "today"
TAB_PLAN = "plan"
SUB_IMMERSION = "immersion"
SUB_EV = "ev-charger"
SUB_TARIFF = "tariff"
SUB_SETTINGS = "settings"
TABS = frozenset({TAB_NOW, TAB_TODAY, TAB_PLAN})

# How far back the charts reach, and how tall they are in grid rows. A bill period is a
# calendar month, so 31 days always holds the one in progress.
_BILL_COST_DAYS = 31
_SOLAR_DAYS = 7
_CHART_ROWS = 5
_LOGBOOK_HOURS = 24

# The rate sensors report a bare currency amount, and their unit stays that for the long-term
# statistics. So the tile name says what the amount is for.
RATE_NAME = "Rate per kWh"
# What a person calls the house use and the share of the forecast generated so far.
HOME_USED_NAME = "Home used"
FORECAST_REACHED_NAME = "Of forecast"
AVERAGE_RATE_NAME = "Avg import/kWh"
# What the night survival sensors are called to a person: does the battery last the night.
OVERNIGHT_NAME = "Battery overnight"
# The two sunrise figures differ by tonight's planned charge, so each name says which it is.
# Both are full width: a half tile fits 15 characters and these are longer.
SUNRISE_NO_CHARGE_NAME = "Sunrise (no charge)"
SUNRISE_WITH_CHARGE_NAME = "Sunrise (with charge)"


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
    """Bars of the cost per day for two weeks, named as the tiles above it are.

    Grid import is left out: it is the sum of the house, EV and immersion costs, so drawing
    it beside them would count the same cost twice. Its tile above carries the total.
    """
    return statistics_graph(
        [
            entity_row(cost.house, "Rest of house"),
            entity_row(cost.ev, "EV charging"),
            entity_row(cost.immersion, "Immersion"),
            entity_row(cost.export_earnings, "Export earnings"),
        ],
        "day",
        14,
    )


# The immersion temperature settings: unique ID suffix and the name shown.
# A tile two to a row fits 15 characters, so the names are short and the help below says more.
_THERMOSTAT_SETTINGS = (
    ("immersion_target_temp", "Heat to"),
    ("immersion_min_temp", "Never below"),
    ("immersion_hysteresis", "Restart drop"),
)
# Tonight's charge, named the same wherever it is shown or set: a fixed target to charge to.
FIXED_TARGET_NAME = "Fixed target"
CHARGE_TO_NAME = "Charge to"
# The immersion switches, named for what they do.
AUTO_DIVERT_NAME = "Use spare solar"
MANAGED_NAME = "Heat now"
SCHEDULE_NAME = "Scheduled heat"


def _dry_run_exit(dry_run_active: str) -> str:
    """How to leave dry run, as a template: a test instance has its own way out.

    The sensor carries the test_instance attribute only on a test instance.
    """
    return (
        f"{{% if state_attr('{dry_run_active}', 'test_instance') %}}"
        "**Test instance.** A .givenergy_test_instance file in the Home Assistant "
        "configuration folder forces dry run on. Delete the file and restart Home Assistant "
        "to go live."
        "{% else %}"
        "To go live, an administrator turns off the Dry run switch in Settings."
        "{% endif %}"
    )


def _has_inverter_temp(hass: HomeAssistant, cfg: dict) -> bool:
    """True when an inverter temperature entity is chosen or GivTCP publishes one."""
    if cfg.get(CONF_INVERTER_TEMP_ENTITY):
        return True
    prefix = device_prefix(cfg)
    candidates = temperature_entity_ids_for(prefix) if prefix else []
    return any(hass.states.get(entity_id) is not None for entity_id in candidates)


# What each tuning control does, in a line each, under them on the Settings view. The heater
# lines are added only while the heater is there.
_TUNING_LINES = (
    "- **Cheap rate floor**: in the cheapest rate, top the battery up to this. 0 is off.",
    "- **Skip charge above**: skip tonight's charge above this, if tomorrow looks sunny.",
    "- **Forecast caution**: 0 plans on the typical forecast, 1 on the low one.",
    "- **Re-plan charge**: work the target out again in the cheap window, three times at most.",
)
_HEATER_TUNING_LINE = (
    "- **Min battery**, **Min surplus**: spare solar goes to the water only above both."
)
_THERMOSTAT_TUNING_LINE = (
    "- **Restart drop**: how far the water falls below the target before it heats again."
)


class Builder:
    """Builds the sections of each view from the entities that exist.

    Tabs link to sub-views, and a link is left out when its sub-view is empty. So the
    sub-views are built first, with build_subviews, and the tabs after.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        facts: HostFacts,
        registry,
    ) -> None:
        self.cards = HacsCards(facts.resources)
        # Settings is built for an administrator and left out for anyone else.
        self.admin_ids = facts.admin_ids if facts.is_admin else ()
        self.reg = Registry(er.async_get(hass) if registry is None else registry, entry.entry_id)
        self.cfg = entry_config(entry)
        self.external_ev = external_ev_power(hass)
        self.devices = Devices(self.reg)
        self.has_inverter_temp = _has_inverter_temp(hass, self.cfg)
        self.has_forecast = bool(self.cfg.get(CONF_FORECAST_ENTITY))
        self._subview_paths: set[str] | None = None

    # -- entities --

    def entity(self, suffix: str) -> str | None:
        """The entity with this unique ID suffix, or None when it is missing or disabled."""
        return self.reg.get(suffix)

    def ev(self, suffix: str) -> str | None:
        """An EV charger entity. Its expected ID while no charger has been discovered."""
        return self.devices.entity(Device.EV_CHARGER, suffix)

    def immersion(self, suffix: str) -> str | None:
        """An entity of the immersion switch. Its expected ID while none is configured."""
        return self.devices.entity(Device.IMMERSION_SWITCH, suffix)

    def alt_heat_advice(self, suffix: str) -> str | None:
        """An entity of the alternative heating advice. Its expected ID while it is not set."""
        return self.devices.entity(Device.ALTERNATIVE_HEAT, suffix)

    def water_sensor(self, suffix: str) -> str | None:
        """An entity of the immersion temperature sensor, expected while none is configured."""
        return self.devices.entity(Device.IMMERSION_SENSOR, suffix)

    def thermostat(self, suffix: str) -> str | None:
        """An immersion temperature control. Expected while the switch or sensor is missing."""
        return self.devices.entity(Device.IMMERSION_THERMOSTAT, suffix)

    def inverter_temp(self, suffix: str) -> str | None:
        """Like entity, but None unless an inverter temperature entity is configured."""
        return self.entity(suffix) if self.has_inverter_temp else None

    def ev_power(self) -> str | None:
        """The charger's power: a known external charger first, then our own sensor."""
        # Looked up first, so a disabled sensor is still listed as left out.
        integration_power = self.ev("ev_power")
        return self.external_ev or integration_power

    def tile(self, suffix: str, name: str, **style) -> dict | None:
        """A tile for the entity with this unique ID suffix."""
        return tile_card(self.entity(suffix), name, **style)

    # -- navigation --

    def build_subviews(self) -> list[dict]:
        """Build every sub-view and note which of them hold cards. Call before the tabs."""
        views = [spec.build(self) for spec in SUBVIEWS]
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
        if path in TABS or self.has_subview(path):
            return navigate_action(path)
        return None

    def admin_view_users(self) -> list[dict[str, str]]:
        """The `visible` list of a view only administrators see."""
        return [{"user": admin_id} for admin_id in self.admin_ids]

    def _settings_badges(self) -> list[dict[str, Any]] | None:
        """The Settings button of the Now heading, or None when no one may open Settings."""
        nav = self.go(SUB_SETTINGS)
        if not nav:
            return None
        visibility = [admin_condition(self.admin_ids)]
        return [button_badge("mdi:tune", "Settings", nav, visibility)]

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
                "unit_of_measurement": f"{currency_symbol(self.cfg)}/h",
            }
        return node

    def _home_node(self) -> dict | None:
        house_load = self.entity("house_load")
        if not house_load:
            return None
        return {"entity": house_load, "subtract_individual": False, "hide": False}

    def _individual_nodes(self, shown: frozenset[Device]) -> list:
        """The devices drawn beside the home node: those of *shown* that exist."""
        car = entity_row(
            self.ev_power() if Device.EV_CHARGER in shown else None,
            "Car Charger",
            icon="mdi:car-electric",
            display_zero=False,
            color=HEX[EV],
        )
        heater = entity_row(
            self.immersion("immersion_power") if Device.IMMERSION_SWITCH in shown else None,
            "Immersion",
            icon="mdi:water-boiler",
            display_zero=False,
            color=HEX[IMMERSION],
        )
        return present([car, heater])

    def _flow_entities(self, shown: frozenset[Device]) -> dict:
        nodes = {
            "solar": self._solar_node(),
            "battery": self._battery_node(),
            "grid": self._grid_node(),
            "home": self._home_node(),
        }
        out = {name: node for name, node in nodes.items() if node}
        if individual := self._individual_nodes(shown):
            out["individual"] = individual
        return out

    def _repairs_card(self) -> dict | None:
        """Home Assistant's repairs, for an administrator, hidden while there are none.

        A stalled feed or an unconfirmed write is raised as a repair, and this puts it where the
        user looks. It lists every repair, not only ours, because the card has no filter.
        """
        if not self.admin_ids:
            return None
        return {
            "type": "repairs",
            "hide_empty": True,
            "grid_options": {"columns": FULL},
            "visibility": [admin_condition(self.admin_ids)],
        }

    def _now(self) -> list:
        """The numbers worth a glance: charge, rate, cost, whether the night is covered, cheap rate.

        The overnight tile is full width because it says two things: whether the battery lasts
        and the charge expected at sunrise. The battery tile draws its last day as a line, so
        it is two rows tall beside the rate and cost tiles.
        """
        return heading_block(
            heading_card("Now", "mdi:clock-outline", badges=self._settings_badges()),
            [
                self.tile(
                    "battery_soc",
                    "Battery",
                    color=BATTERY,
                    features=[TREND],
                    nav=self.go(TAB_PLAN),
                    rows=2,
                ),
                self.tile("current_rate", RATE_NAME, color=GRID),
                self.tile("import_cost_today", "Cost today", color=GRID, nav=self.go(TAB_TODAY)),
                self.tile(
                    "night_survival_confidence",
                    OVERNIGHT_NAME,
                    columns=FULL,
                    color=NIGHT,
                    nav=self.go(TAB_PLAN),
                    state_content=["summary"],
                ),
                self.tile(
                    "next_cheap_rate_start",
                    "Cheap from",
                    columns=FULL,
                    color=GRID,
                    state_content=["summary"],
                ),
                self._repairs_card(),
            ],
        )

    def _flow_card(self, shown: frozenset[Device]) -> dict | None:
        """The power flow card with the devices of *shown* drawn beside the home node."""
        flow = self._flow_entities(shown)
        if not flow:
            return None
        card = flow_card(flow) if self.cards.installed(POWER_FLOW_CARD) else flow_fallback(flow)
        return {**card, "grid_options": {"columns": FULL}} if card else None

    def _flow(self) -> list:
        """One card for each combination of the car charger and immersion being there.

        The card cannot hide one device, so a stored dashboard shows the card built for the
        devices present, and swaps to another when a device comes or goes.
        """
        devices = (Device.EV_CHARGER, Device.IMMERSION_SWITCH)
        cards = self.devices.variants(devices, self._flow_card)
        return heading_block(heading_card("Live power flow", "mdi:transmission-tower"), cards)

    def _forecast_tiles(self) -> list:
        """Today's forecast and how much of it has been generated, with a forecast configured."""
        if not self.has_forecast:
            return []
        return [
            self.tile("solar_forecast_raw_today", "Solar forecast", color=SOLAR),
            self.tile("solar_actual_vs_forecast_pct", FORECAST_REACHED_NAME, color=SOLAR),
        ]

    def _totals(self) -> list:
        return heading_block(
            heading_card("Today so far", "mdi:lightning-bolt", nav=self.go(TAB_TODAY)),
            [
                self.tile("solar_today", "Solar", color=SOLAR),
                *self._forecast_tiles(),
                self.tile("house_kwh_today", HOME_USED_NAME, color=GRID),
                self.tile("import_today", "Imported", color=GRID),
                self.tile("export_today", "Exported", color=GRID),
                self.tile("self_sufficiency", "Self-sufficient", color=SOLAR),
            ],
        )

    def _immersion_tiles(self) -> list:
        """The Immersion tile: the water temperature, or the heater when there is no sensor."""
        devices = self.devices
        style = {"color": IMMERSION, "icon": "mdi:water-boiler", "nav": self.go(SUB_IMMERSION)}
        temperature = devices.show_with(
            tile_card(self.water_sensor("immersion_water_temperature"), "Immersion", **style),
            Device.IMMERSION_SENSOR,
        )
        heater = with_visibility(
            tile_card(self.immersion("immersion_power"), "Immersion", **style),
            devices.visible_with(Device.IMMERSION_SWITCH)
            + devices.visible_without(Device.IMMERSION_SENSOR),
        )
        return [temperature, heater]

    def _devices(self) -> list:
        """The Devices heading and a tile for each device present. Nothing shows with none."""
        ev_charger = self.devices.show_with(
            tile_card(
                self.ev("ev_charger_state"),
                "EV charger",
                color=EV,
                icon="mdi:ev-station",
                nav=self.go(SUB_EV),
            ),
            Device.EV_CHARGER,
        )
        heading = with_visibility(
            heading_card("Devices", "mdi:power-plug"),
            self.devices.visible_with_any(
                Device.EV_CHARGER, Device.IMMERSION_SWITCH, Device.IMMERSION_SENSOR
            ),
        )
        return heading_block(heading, [*self._immersion_tiles(), ev_charger])

    def now_sections(self) -> list:
        """Now, the banners, then the power flow two columns wide.

        The sections are placed densely, so on a laptop the power flow fills the two columns
        beside Now that a view-wide banner leaves free, and the banners run across the view
        below them. On a phone every section is one column and they stack in this order.
        """
        return present(
            [
                grid_section(self._now()),
                self._dry_run_section(),
                self._charge_conflict_section(),
                self._setup_checklist(),
                grid_section(self._flow(), **WIDE),
                grid_section(self._totals()),
                grid_section(self._devices()),
            ]
        )

    # -- Immersion sub-view --

    def _heater_tile(self) -> dict | None:
        """The heater's power now: its rated watts while it is on, 0 while it is off."""
        return tile_card(
            self.immersion("immersion_power"), "Heater power", color=IMMERSION, icon="mdi:flash"
        )

    def _immersion_chart(self, entities: ImmersionEntities) -> dict | None:
        """The immersion chart. apexcharts-card draws the heater as a band behind the water
        temperature, in one chart, when it is installed. Otherwise a history graph draws the
        temperatures and the heater's power as two charts in one card."""
        if self.cards.installed(APEX_CARD):
            return apex_immersion_chart(entities)
        return builtin_immersion_chart(entities)

    def _temperature_card(self, shown: frozenset[Device]) -> dict | None:
        """The water temperature chart.

        With the thermostat (the switch and the sensor together) it adds the target and minimum
        lines, and the heater's power as a line.
        """
        both = Device.IMMERSION_THERMOSTAT in shown
        entities = ImmersionEntities(
            self.water_sensor("immersion_water_temperature"),
            self.thermostat("immersion_target_temp") if both else None,
            self.thermostat("immersion_min_temp") if both else None,
            self.immersion("immersion_power") if both else None,
        )
        return self._immersion_chart(entities)

    def _water_temperature(self) -> dict | None:
        """The water temperature chart, while there is a sensor. Not drawn without one.

        With the switch as well, a tile above it says whether the heater is on.
        """
        cards = self.devices.variants((Device.IMMERSION_THERMOSTAT,), self._temperature_card)
        return group(
            heading_card("Water temperature", "mdi:thermometer-water"),
            [
                self.devices.show_with(
                    self._heater_tile(), Device.IMMERSION_SWITCH, Device.IMMERSION_SENSOR
                ),
                *[self.devices.show_with(card, Device.IMMERSION_SENSOR) for card in cards],
            ],
        )

    def _heater_on_off(self) -> dict | None:
        """The heater on or off, for a switch with no temperature sensor.

        With a sensor the water temperature section carries the heater, so this one hides itself.
        """
        entities = ImmersionEntities(None, None, None, self.immersion("immersion_power"))
        return group(
            heading_card("Heater on or off", "mdi:flash"),
            [self._heater_tile(), self._immersion_chart(entities)],
            visibility=[
                *self.devices.visible_with(Device.IMMERSION_SWITCH),
                *self.devices.visible_without(Device.IMMERSION_SENSOR),
            ],
        )

    def immersion_sections(self) -> list:
        """Sub-view: the water temperature, why the heater is on or off, and what it used.

        Each section follows its own device. A sensor with a switch adds the heater to the
        temperature section. A switch with no sensor gets a small heater chart instead, and a
        sensor with no switch shows no heater or reason.
        """
        switch = Device.IMMERSION_SWITCH
        reason = state_markdown(self.entity("immersion_divert_reason"), ATTR_FULL_TEXT)
        return [
            self._water_temperature(),
            self._heater_on_off(),
            group(heading_card("Why", "mdi:help-circle-outline"), [reason], **self._when(switch)),
            self._ready_by(),
            self._alt_heat_section(),
            group(
                heading_card("Today", "mdi:calendar-today"),
                [
                    tile_card(self.immersion("immersion_today"), "Energy", color=IMMERSION),
                    tile_card(self.immersion("immersion_cost_today"), "Cost", color=GRID),
                    self._immersion_savings_tile(),
                ],
                **self._when(switch),
            ),
            self._immersion_settings_in_force(),
        ]

    def _ready_by(self) -> dict | None:
        """The next hot water ready time and the planned heating, while scheduled heating is on.

        Needs both devices, because scheduled heating does. The sensor's attributes carry the
        time and the plan, so no helper sensor is needed. With alternative heating it adds the
        advice sentence, which names when to start it for this ready time.
        """
        sensor = self.water_sensor("immersion_water_temperature")
        schedule = self.thermostat("immersion_schedule")
        if not (sensor and schedule):
            return None
        devices = self.devices
        advice = attribute_markdown(
            self.alt_heat_advice("water_heating_cheapest_source"), "suggestion"
        )
        return group(
            heading_card("Ready by", "mdi:clock-check-outline"),
            [
                markdown_card(ready_by_template(sensor)),
                markdown_card(planned_heating_template(sensor)),
                devices.show_with(advice, Device.ALTERNATIVE_HEAT),
            ],
            visibility=[
                *devices.visible_with(Device.IMMERSION_THERMOSTAT, Device.IMMERSION_SENSOR),
                *devices.visible_while_on(schedule),
            ],
        )

    def _alt_heat_section(self) -> dict[str, Any] | None:
        """The cheapest way to heat the water, while alternative heating is set. Advice only.

        The live suggestion shows only while Immersion Scheduled Heating is off. While it is
        on, the Ready by section prints the same sentence, so the page holds one copy.
        """
        source = self.alt_heat_advice("water_heating_cheapest_source")
        scheduled = self.thermostat("immersion_schedule")
        suggestion = attribute_markdown(source, "suggestion")
        return group(
            heading_card("Cheapest way to heat the water", "mdi:fire-circle"),
            [
                markdown_card(cheapest_source_template(source)) if source else None,
                with_visibility(suggestion, self.devices.visible_while_off(scheduled)),
                self._alt_heat_schedule_line(source),
            ],
            **self._when(Device.ALTERNATIVE_HEAT),
        )

    @staticmethod
    def _alt_heat_schedule_line(source: str | None) -> dict | None:
        """The suggested alternative heating schedule, apart from the live suggestion above it."""
        return markdown_card(alt_heat_schedule_template(source)) if source else None

    def _when(self, *devices: Device) -> dict[str, list[dict]]:
        """The section option that shows a section while these devices are present."""
        return {"visibility": self.devices.visible_with(*devices)}

    def _thermostat_help(self) -> list[dict | None]:
        """What Heat now and the restart drop mean. The drop needs the switch and the sensor."""
        return [
            markdown_card(MANAGED_HELP),
            self.devices.show_with(markdown_card(RESTART_GAP_HELP), Device.IMMERSION_THERMOSTAT),
        ]

    def _immersion_settings_in_force(self) -> dict[str, Any] | None:
        """The immersion settings as they stand, to read. Administrators change them."""
        readings = [
            self.devices.show_with(
                readonly_tile(self.thermostat(suffix), name, IMMERSION), Device.IMMERSION_THERMOSTAT
            )
            for suffix, name in _THERMOSTAT_SETTINGS
        ]
        schedule = self.devices.show_with(
            readonly_tile(self.thermostat("immersion_schedule"), SCHEDULE_NAME, IMMERSION),
            Device.IMMERSION_THERMOSTAT,
        )
        return group(
            heading_card("Settings in force", "mdi:tune"),
            [
                readonly_tile(self.immersion("auto_immersion"), AUTO_DIVERT_NAME, IMMERSION),
                readonly_tile(self.immersion("immersion_managed"), MANAGED_NAME, IMMERSION),
                schedule,
                *readings,
                *self._thermostat_help(),
            ],
            **self._when(Device.IMMERSION_SWITCH),
        )

    # -- EV charger sub-view --

    def ev_sections(self) -> list:
        """Sub-view: the EV charger's state and why it is or is not charging."""
        decision = self.ev("ev_protection_reason")
        shown = self._when(Device.EV_CHARGER)
        return [
            group(
                heading_card("Charging now", "mdi:ev-station"),
                [
                    tile_card(self.ev("ev_charger_state"), "Charger state", color=EV),
                    tile_card(self.ev_power(), "Charge power", color=EV),
                    tile_card(self.ev("ev_session_energy"), "Session energy", color=EV),
                    tile_card(self.ev("ev_charging_source"), "Charging source", color=EV),
                ],
                **shown,
            ),
            group(
                heading_card("Why", "mdi:help-circle-outline"),
                [
                    tile_card(self.ev("ev_draining_battery"), "Drains battery", color=BATTERY),
                    tile_card(self.ev("ev_solar_surplus_available"), "Solar surplus", color=SOLAR),
                    state_markdown(decision, ATTR_FULL_TEXT),
                ],
                **shown,
            ),
            group(
                heading_card("Today", "mdi:calendar-today"),
                [
                    tile_card(self.ev("zappi_today"), "Energy", color=EV),
                    tile_card(self.ev("zappi_cost_today"), "Cost", color=GRID),
                ],
                **shown,
            ),
            group(
                heading_card("Charge power, last 24 hours", "mdi:chart-line"),
                [self._ev_power_history()],
                **shown,
            ),
        ]

    def _ev_power_history(self) -> dict | None:
        """A line of the charger's power. Power does not reset, so a history graph is right."""
        power = entity_row(self.ev_power(), "Charge power")
        history = entity_list_card([power], {"type": "history-graph"}, hours_to_show=24)
        return graph_card(history) if history else None

    # -- Today --

    def _today_by_hour(self) -> dict | None:
        """Where each hour's energy came from over the last day, as stacked bars, view wide.

        The three sources stack to what the house and the battery took in that hour.
        """
        graph = stacked_hourly_graph(
            [
                entity_row(self.entity("solar_today"), "Solar"),
                entity_row(self.entity("battery_discharge_kwh_today"), "From battery"),
                entity_row(self.entity("import_today"), "From grid"),
            ],
            _CHART_ROWS,
        )
        return group(
            heading_card("Today hour by hour", "mdi:chart-bar-stacked"), [graph], **WHOLE_WIDTH
        )

    def _today_energy(self) -> dict | None:
        return group(
            heading_card("Energy", "mdi:lightning-bolt"),
            [
                self.tile("solar_today", "Solar", color=SOLAR),
                self.tile("house_kwh_today", HOME_USED_NAME, color=GRID),
                self.tile("import_today", "Imported", color=GRID),
                self.tile("export_today", "Exported", color=GRID),
                self.devices.show_with(
                    tile_card(self.ev("zappi_today"), "EV", color=EV), Device.EV_CHARGER
                ),
                self.devices.show_with(
                    tile_card(self.immersion("immersion_today"), "Immersion", color=IMMERSION),
                    Device.IMMERSION_SWITCH,
                ),
            ],
        )

    def _energy_sources_card(self) -> dict | None:
        """The house and grid sums in words. None unless the sensors it reads exist."""
        sources = EnergySources(
            self.entity("self_sufficiency") or "",
            self.entity("house_kwh_today") or "",
            self.entity("import_today") or "",
            self.entity("battery_discharge_kwh_today"),
        )
        if not (sources.self_sufficiency and sources.house and sources.imported):
            return None
        return markdown_card(energy_sources_template(sources))

    def _energy_devices_card(self, shown: frozenset[Device]) -> dict | None:
        """The EV and immersion energy, for the devices of *shown* that have an entity."""
        ev = self.ev("zappi_today") if Device.EV_CHARGER in shown else None
        immersion = self.immersion("immersion_today") if Device.IMMERSION_SWITCH in shown else None
        text = energy_devices_template(ev, immersion)
        return markdown_card(text) if text else None

    def _today_sources(self) -> dict | None:
        """Where today's energy came from. The EV and immersion lines follow their devices."""
        sources = self._energy_sources_card()
        if sources is None:
            return None
        devices = self.devices.variants(
            (Device.EV_CHARGER, Device.IMMERSION_SWITCH), self._energy_devices_card
        )
        return group(
            heading_card("Where today's energy came from", "mdi:home-lightning-bolt-outline"),
            [sources, *devices],
        )

    def _today_cost(self) -> dict | None:
        """Today's costs: import and export, the import split by load, then the rate.

        The rest of the house, the EV and the immersion add up to the import cost.
        """
        cost = self._cost_entities(frozenset({Device.EV_CHARGER, Device.IMMERSION_SWITCH}))
        show = self.devices.show_with
        return group(
            heading_card("Cost", "mdi:cash-multiple"),
            [
                tile_card(cost.grid_import, "Import cost", color=GRID),
                tile_card(cost.export_earnings, "Export earnings", color=BATTERY),
                tile_card(cost.house, "Rest of house", color=GRID),
                show(tile_card(cost.ev, "EV charging", color=EV), Device.EV_CHARGER),
                show(
                    tile_card(cost.immersion, "Immersion", color=IMMERSION),
                    Device.IMMERSION_SWITCH,
                ),
                self.tile("current_rate", RATE_NAME, color=GRID),
                self.tile("current_rate_period", "Rate period", color=GRID),
                show(
                    self._immersion_savings_tile("Immersion solar saving", FULL),
                    Device.IMMERSION_SWITCH,
                ),
            ],
        )

    def _today_solar(self) -> dict | None:
        """The solar shares as bars.

        Self-sufficiency has no bar of its own while the card on where today's energy came
        from states it, with what it means, in the section beside this one. The Power Flow
        tab keeps its tile for a glance.
        """
        share = {"columns": FULL, "color": SOLAR, "features": [BAR]}
        stated = self._energy_sources_card() is not None
        return group(
            heading_card("Solar", "mdi:weather-sunny"),
            [
                None if stated else self.tile("self_sufficiency", "Self-sufficiency", **share),
                self.tile("solar_share", "Home use from solar", **share),
                self.tile("self_consumption", "Solar kept at home", **share),
            ],
        )

    def today_sections(self) -> list:
        """The day hour by hour, then energy, cost and solar, each with its detail below."""
        cost_history = self.devices.variants(
            (Device.EV_CHARGER, Device.IMMERSION_SWITCH), self._cost_history_card
        )
        return [
            self._today_by_hour(),
            self._today_energy(),
            self._today_sources(),
            self._today_cost(),
            self._today_solar(),
            self._against_forecast(),
            group(heading_card("Cost per day, last 14 days", "mdi:chart-bar"), cost_history),
            self._solar_days(),
        ]

    def _cost_entities(self, shown: frozenset[Device]) -> _CostEntities:
        """The cost sensors, with the EV and immersion lines only for the devices of *shown*."""
        ev = Device.EV_CHARGER in shown
        immersion = Device.IMMERSION_SWITCH in shown
        return _CostEntities(
            self.entity("import_cost_today"),
            self.entity("export_earnings_today"),
            self.entity("house_cost_today"),
            self.ev("zappi_cost_today") if ev else None,
            self.immersion("immersion_cost_today") if immersion else None,
        )

    def _cost_history_card(self, shown: frozenset[Device]) -> dict | None:
        return _cost_history(self._cost_entities(shown))

    def _immersion_savings_tile(
        self, name: str = "Saved by solar", columns: int | str = 6
    ) -> dict | None:
        """What solar saved on the immersion today.

        On the Immersion view the section says whose saving it is. Beside the other costs it
        needs the name, and a name that long takes the full width.
        """
        entity = self.immersion("immersion_savings_today")
        return tile_card(entity, name, columns=columns, color=BATTERY)

    def _against_forecast(self) -> dict | None:
        """How solar compares with the forecast, with a forecast sensor set."""
        if not self.has_forecast:
            return None
        plan_forecast = self.tile("solar_forecast_kwh_today", "Plan forecast", color=SOLAR)
        return group(
            heading_card("Against the forecast", "mdi:chart-line"),
            [
                self.tile("solar_today", "Generated today", color=SOLAR),
                self.tile("solar_forecast_raw_today", "Solar forecast", color=SOLAR),
                self.tile("solar_actual_vs_forecast_pct", FORECAST_REACHED_NAME, color=SOLAR),
                plan_forecast,
                self.tile(
                    "yesterday_forecast_accuracy_pct",
                    "Yesterday's accuracy",
                    columns=FULL,
                    color=SOLAR,
                ),
                markdown_card(PLAN_FORECAST_CAPTION) if plan_forecast else None,
            ],
        )

    def _solar_days(self) -> dict | None:
        """What was generated on each of the last 7 days, with a forecast sensor set.

        The forecast sensor keeps no long-term statistics, so only the generated energy is
        plotted. The Against the forecast section above holds the forecast figures.
        """
        actual = self.entity("solar_today")
        if not (self.has_forecast and actual and self.entity("solar_forecast_raw_today")):
            return None
        card = statistics_graph([entity_row(actual, "Generated")], "day", _SOLAR_DAYS, _CHART_ROWS)
        return group(heading_card(f"Last {_SOLAR_DAYS} days", "mdi:calendar-week"), [card])

    # -- Bill --

    def _bill(self) -> dict | None:
        """The bill period in one section. A Tariff button opens the rates the sums use."""
        tariff = self.go(SUB_TARIFF)
        badges = [button_badge("mdi:table", "Tariff", tariff)] if tariff else None
        return group(
            heading_card("Bill", "mdi:receipt-text", badges=badges),
            [
                self.tile("accrued_bill", "Accrued bill", color=GRID),
                self.tile("projected_bill", "Projected bill", color=GRID),
                self.tile("import_cost_this_month", "Import cost", color=GRID),
                self.tile("export_earnings_this_month", "Export credit", color=BATTERY),
                self.tile("days_remaining_in_period", "Days left"),
                self.tile("avg_import_rate_this_month", AVERAGE_RATE_NAME, color=GRID),
            ],
        )

    def _bill_cost_per_day(self) -> dict | None:
        """The import cost and the export earnings of each day, which add up to the bill."""
        history = statistics_graph(
            [
                entity_row(self.entity("import_cost_today"), "Import cost"),
                entity_row(self.entity("export_earnings_today"), "Export credit"),
            ],
            "day",
            _BILL_COST_DAYS,
            _CHART_ROWS,
        )
        heading = heading_card(f"Cost per day, last {_BILL_COST_DAYS} days", "mdi:chart-bar")
        return group(heading, [history], **WHOLE_WIDTH)

    def _scheduled_changes(self, today: date) -> list:
        """The rate changes that have not started, under the tariff in use. Empty when none."""
        changes = scheduled_tariff_changes(self.cfg, today)
        text = tariff_changes_table(changes, self.cfg, last_tariff_review(self.cfg))
        heading = subheading_card("Scheduled rate changes", "mdi:calendar-clock")
        return heading_block(heading, [markdown_card(text) if text else None])

    def tariff_sections(self) -> list:
        """Sub-view: the rates and charges the bill sums use, and the rate changes to come.

        Both are read from the options each time the strategy dashboard opens.
        """
        today = dt_util.now().date()
        in_force = tariff_in_force(self.cfg, today)
        table = markdown_card(tariff_table(build_tariff(in_force), self.cfg))
        return [
            grid_section(
                heading_block(heading_card("Tariff in use", "mdi:table"), [table]),
                self._scheduled_changes(today),
            )
        ]

    # -- Battery --

    def _battery_now(self) -> dict | None:
        """The charge and the power, each with its last 24 hours drawn as a line."""
        return group(
            heading_card("Battery", "mdi:battery-heart-variant"),
            [
                self.tile("battery_soc", "Charge", color=BATTERY, features=[TREND]),
                self.tile("battery_power", "Power", color=BATTERY, features=[TREND]),
            ],
        )

    def _while_on(self, switch_suffix: str, tile: dict | None) -> dict | None:
        """A tile shown only while this switch is on, so a setting shows only while in force."""
        switch = self.entity(switch_suffix)
        if switch is None:
            return None
        return with_visibility(tile, self.devices.visible_while_on(switch))

    def _in_force(self) -> list:
        """The settings that change tonight, each shown only while it does.

        Everyone can read them here. Administrators change them in Settings.
        """
        dry_run = self.entity("dry_run_active")
        floor = self.entity("cheap_rate_floor_status")
        return [
            self._while_on(
                "charge_target_override_enabled",
                readonly_tile(
                    self.entity("charge_target_override_enabled"), FIXED_TARGET_NAME, BATTERY
                ),
            ),
            self._while_on(
                "charge_target_override_enabled",
                readonly_tile(self.entity("charge_target_override"), CHARGE_TO_NAME, BATTERY),
            ),
            self._while_on(
                "skip_charge_override",
                readonly_tile(self.entity("skip_charge_override"), "Skip tonight", BATTERY),
            ),
            with_visibility(
                tile_card(
                    dry_run, "Dry run", color=GRID, icon="mdi:test-tube", state_content=["summary"]
                ),
                [{"condition": "state", "entity": dry_run, "state": "True"}],
            )
            if dry_run
            else None,
            with_visibility(
                tile_card(floor, "Rate floor", color=GRID, icon="mdi:floor-plan"),
                [{"condition": "state", "entity": floor, "state_not": "Inactive"}],
            )
            if floor
            else None,
        ]

    def _charge_plan(self) -> dict | None:
        """The plan's sentence first: it says whether tonight charges or is skipped.

        What changes tonight's charge shows under it only while it is in force.
        """
        return group(
            heading_card("Tonight's charge", "mdi:weather-night"),
            [
                state_markdown(self.entity("charge_plan")),
                self.tile("overnight_charge_target", "Target", color=BATTERY),
                self.tile("overnight_charge_cost", "Est. cost", color=GRID),
                self.tile(
                    "estimated_soc_at_sunrise", SUNRISE_NO_CHARGE_NAME, color=BATTERY, columns=FULL
                ),
                self.tile(
                    "estimated_soc_at_sunrise_with_charge",
                    SUNRISE_WITH_CHARGE_NAME,
                    color=BATTERY,
                    columns=FULL,
                ),
                *self._in_force(),
            ],
        )

    def _health(self) -> dict | None:
        """The battery's wear and the inverter's temperature, in one section."""
        return group(
            heading_card("Health", "mdi:battery-heart-variant"),
            [
                self.tile("battery_cycles", "Total cycles", color=BATTERY),
                self.tile("battery_remaining_life", "Life remaining", color=BATTERY),
                self.tile(
                    "days_since_full_charge", "Since full", color=BATTERY, icon="mdi:battery-check"
                ),
                tile_card(self.inverter_temp("inverter_temperature"), "Inverter temp", color=GRID),
                tile_card(
                    self.inverter_temp("inverter_temperature_status"),
                    "Inverter status",
                    color=GRID,
                    icon="mdi:thermometer-alert",
                ),
            ],
        )

    def _overnight(self) -> dict | None:
        """Whether the battery lasts the night, and why tonight's target is what it is."""
        return grid_section(
            heading_block(
                heading_card(OVERNIGHT_NAME, "mdi:weather-night"),
                self._night_survival(),
            ),
            heading_block(
                subheading_card("Why this target", "mdi:battery-charging"),
                [state_markdown(self.entity("overnight_charge_reason"), ATTR_FULL_TEXT)],
            ),
        )

    def plan_sections(self) -> list:
        """Six sections: tonight, why, the battery, the bill, the cost per day, health.

        The tariff table is one tap away, on its own view.
        """
        return [
            self._charge_plan(),
            self._overnight(),
            self._battery_now(),
            self._bill(),
            self._bill_cost_per_day(),
            self._health(),
        ]

    def _night_survival(self) -> list:
        """The overnight outlook in bold, then why, in words.

        The confidence sensor carries the level. Its explanation attribute is used when
        it has one. Without it a sentence is chosen by level: Warning is explained from
        the estimated state of charge at sunrise, and Safe and Critical show the status
        sensor's text, which carries any kWh shortfall.
        """
        level = self.entity("night_survival_confidence")
        status = self.entity("night_survival_reason")
        sunrise = self.entity("estimated_soc_at_sunrise")
        with_charge = self.entity("estimated_soc_at_sunrise_with_charge")
        if level:
            return [markdown_card(survival_template(level, status, sunrise, with_charge))]
        if status:
            return [markdown_card(state_ref(status, ATTR_FULL_TEXT))]
        return []

    # -- Settings --

    def _dry_run_section(self) -> dict | None:
        """A banner, shown only while Dry Run Mode Active is true."""
        dry_run_active = self.entity("dry_run_active")
        if not dry_run_active:
            return None
        text = (
            "No commands are sent to your inverter or EV charger. Sensors and charge "
            "decisions still update.\n\n" + _dry_run_exit(dry_run_active)
        )
        if skipped := self.entity("dry_run_last_skipped"):
            text += f"\n\n**Last skipped action:** {state_ref(skipped, ATTR_FULL_TEXT)}"
        if plan := self.entity("charge_plan"):
            text += f"\n\n**Tonight's charge plan:** {state_ref(plan)}"
        return group(
            heading_card("Dry run is on", "mdi:test-tube"),
            [markdown_card(text)],
            visibility=[{"condition": "state", "entity": dry_run_active, "state": "True"}],
            **WHOLE_WIDTH,
        )

    def _charge_conflict_section(self) -> dict | None:
        """A banner, shown only while Charge Target Conflict says suspected.

        It names no product, because a change made in the GivEnergy app looks the same as
        SmartTarget or Predbat. The state condition is a classic one, so it works on the
        Home Assistant floor.
        """
        conflict = self.entity("charge_target_conflict")
        if not conflict:
            return None
        text = (
            "This integration saw the charge target change without a write from it. Common "
            "causes are GivTCP's SmartTarget, Predbat or the app. Turn that off so only this "
            "integration sets the target. This message clears after three days without a change."
        )
        return group(
            heading_card(
                "Something else is setting your charge target", "mdi:swap-horizontal-bold"
            ),
            [markdown_card(text)],
            visibility=[{"condition": "state", "entity": conflict, "state": "suspected"}],
            **WHOLE_WIDTH,
        )

    def _setup_checklist(self) -> dict | None:
        """What is left to set up, shown while Setup Progress says incomplete.

        The state condition is a classic one, so it works on the Home Assistant floor. There is
        no dismiss button. The card goes when the required items are done.
        """
        progress = self.entity("setup_progress")
        if not progress:
            return None
        return group(
            heading_card("Finish setting up", "mdi:clipboard-check-outline"),
            [markdown_card(setup_checklist_template(progress))],
            visibility=[{"condition": "state", "entity": progress, "state": "incomplete"}],
            **WHOLE_WIDTH,
        )

    def _dry_run_controls(self) -> list:
        """The Dry run switch, first. Administrators turn it off to go live."""
        return heading_block(
            heading_card("Dry run", "mdi:test-tube"),
            [toggle_tile(self.entity("dry_run"), "Dry run", GRID)],
        )

    def _tuning_controls(self) -> dict | None:
        """The numbers set once and left: the charge plan's and the heater's.

        The numbers take the width of the section, because their names do not fit half of it.
        A line each under them says what they do.
        """
        heater, thermostat = Device.IMMERSION_SWITCH, Device.IMMERSION_THERMOSTAT
        show = self.devices.show_with
        return group(
            heading_card("Fine-tuning", "mdi:tune-variant"),
            [
                stepper_tile(
                    self.entity("cheap_rate_floor_soc"), "Cheap rate floor", BATTERY, FULL
                ),
                stepper_tile(
                    self.entity("skip_charge_soc_threshold_pct"),
                    "Skip charge above",
                    BATTERY,
                    FULL,
                ),
                stepper_tile(self.entity("forecast_conservatism"), "Forecast caution", SOLAR, FULL),
                show(
                    stepper_tile(
                        self.immersion("surplus_divert_soc_pct"), "Min battery", IMMERSION
                    ),
                    heater,
                ),
                show(
                    stepper_tile(
                        self.immersion("surplus_divert_min_power_w"), "Min surplus", IMMERSION
                    ),
                    heater,
                ),
                show(
                    stepper_tile(
                        self.thermostat("immersion_hysteresis"), "Restart drop", IMMERSION, FULL
                    ),
                    thermostat,
                ),
                toggle_tile(self.entity("charge_replan"), "Re-plan charge", BATTERY),
                toggle_tile(self.entity("verbose_logging"), "Verbose logging", GRID),
                *self.devices.variants((heater, thermostat), self._tuning_note),
            ],
        )

    @staticmethod
    def _tuning_note(shown: frozenset[Device]) -> dict:
        """A line for each control above, the heater's only for the devices of *shown*."""
        lines = [*_TUNING_LINES]
        if Device.IMMERSION_SWITCH in shown:
            lines.append(_HEATER_TUNING_LINE)
        if Device.IMMERSION_THERMOSTAT in shown:
            lines.append(_THERMOSTAT_TUNING_LINE)
        return markdown_card("\n".join(lines))

    def _charging_controls(self) -> list:
        return heading_block(
            heading_card("Tonight's charge", "mdi:battery-charging"),
            [
                toggle_tile(
                    self.entity("charge_target_override_enabled"), FIXED_TARGET_NAME, BATTERY
                ),
                # The target to charge to is used only with a fixed target, so it shows only then.
                self._while_on(
                    "charge_target_override_enabled",
                    stepper_tile(
                        self.entity("charge_target_override"), CHARGE_TO_NAME, BATTERY, FULL
                    ),
                ),
                toggle_tile(self.entity("skip_charge_override"), "Skip tonight", BATTERY),
            ],
        )

    def _settings_entities(self, shown: frozenset[Device]) -> list[str | None]:
        """Every switch and number on this view, with the heater's for the devices of *shown*."""
        own = [
            self.entity(suffix)
            for suffix in (
                "dry_run",
                "charge_target_override_enabled",
                "charge_target_override",
                "skip_charge_override",
                "cheap_rate_floor_soc",
                "skip_charge_soc_threshold_pct",
                "forecast_conservatism",
                "charge_replan",
                "verbose_logging",
            )
        ]
        heater = (
            [
                self.immersion(suffix)
                for suffix in (
                    "auto_immersion",
                    "immersion_managed",
                    "surplus_divert_soc_pct",
                    "surplus_divert_min_power_w",
                )
            ]
            if Device.IMMERSION_SWITCH in shown
            else []
        )
        thermostat = (
            [
                self.thermostat(suffix)
                for suffix in ("immersion_schedule", *(key for key, _ in _THERMOSTAT_SETTINGS))
            ]
            if Device.IMMERSION_THERMOSTAT in shown
            else []
        )
        return [*own, *heater, *thermostat]

    def _recent_changes_card(self, shown: frozenset[Device]) -> dict | None:
        return logbook_card(self._settings_entities(shown), _LOGBOOK_HOURS)

    def _recent_changes(self) -> list:
        """What changed a setting in the last day, under Tonight's charge.

        The list names the heater's settings only while the heater is there, so it is built
        once for each combination of the switch and the thermostat.
        """
        cards = self.devices.variants(
            (Device.IMMERSION_SWITCH, Device.IMMERSION_THERMOSTAT), self._recent_changes_card
        )
        return heading_block(subheading_card("Recent changes", "mdi:history"), cards)

    def _immersion_thermostat_controls(self) -> list:
        """Scheduled heating and the two temperatures. They need a switch and a sensor."""
        thermostat = Device.IMMERSION_THERMOSTAT
        show = self.devices.show_with
        return [
            show(
                toggle_tile(self.thermostat("immersion_schedule"), SCHEDULE_NAME, IMMERSION),
                thermostat,
            ),
            show(
                stepper_tile(self.thermostat("immersion_target_temp"), "Heat to", IMMERSION),
                thermostat,
            ),
            show(
                stepper_tile(self.thermostat("immersion_min_temp"), "Never below", IMMERSION),
                thermostat,
            ),
        ]

    def _divert_decision(self) -> list:
        """What the heater is doing now, first, so the controls below read against it."""
        return [state_markdown(self.entity("immersion_divert_reason"), ATTR_FULL_TEXT)]

    def _immersion_controls(self) -> dict | None:
        """What is changed day to day. The divert numbers and restart drop are in Fine-tuning."""
        return group(
            heading_card("Hot water", "mdi:water-boiler"),
            [
                *self._divert_decision(),
                toggle_tile(self.immersion("auto_immersion"), AUTO_DIVERT_NAME, IMMERSION),
                toggle_tile(self.immersion("immersion_managed"), MANAGED_NAME, IMMERSION),
                *self._immersion_thermostat_controls(),
                markdown_card(MANAGED_HELP),
            ],
            **self._when(Device.IMMERSION_SWITCH),
        )

    def settings_sections(self) -> list[Any]:
        """Sub-view, for administrators only: every switch and number that changes behaviour.

        Three sections of one column, so a laptop shows them side by side with no column left
        empty: Dry run, Tonight's charge and the recent changes, then Hot water, then
        Fine-tuning. The first is two rows tall, so on a tablet Fine-tuning sits under Hot water.
        Empty without an administrator ID, so the view is left out and no one sees it.
        """
        if not self.admin_ids:
            return []
        return [
            # Two rows tall, so on a tablet Fine-tuning sits under Hot water beside it.
            grid_section(
                self._dry_run_controls(),
                self._charging_controls(),
                self._recent_changes(),
                row_span=2,
            ),
            self._immersion_controls(),
            self._tuning_controls(),
        ]


@dataclass(frozen=True)
class ViewSpec:
    """A view of the dashboard: its title and icon, and the builder method for its sections.

    A sub-view names the tab its back arrow returns to. A tab has no back. An admin_only view
    is visible to the administrators the builder was given, and to no one else.
    """

    title: str
    icon: str
    path: str
    sections: Callable[[Builder], list]
    back: str | None = None
    admin_only: bool = False

    def build(self, builder: Builder) -> dict:
        extra = {} if self.back is None else {"subview": True, "back_path": self.back}
        if self.admin_only:
            extra["visible"] = builder.admin_view_users()
        return view_config(self.title, self.icon, self.path, self.sections(builder), **extra)


TAB_VIEWS = (
    ViewSpec("Now", "mdi:solar-power-variant", TAB_NOW, Builder.now_sections),
    ViewSpec("Today", "mdi:calendar-today", TAB_TODAY, Builder.today_sections),
    ViewSpec("Plan & bill", "mdi:battery-clock", TAB_PLAN, Builder.plan_sections),
)
SUBVIEWS = (
    ViewSpec("Immersion", "mdi:water-boiler", SUB_IMMERSION, Builder.immersion_sections, TAB_NOW),
    ViewSpec("EV charger", "mdi:ev-station", SUB_EV, Builder.ev_sections, TAB_NOW),
    ViewSpec("Tariff", "mdi:table", SUB_TARIFF, Builder.tariff_sections, TAB_PLAN),
    ViewSpec(
        "Settings",
        "mdi:tune",
        SUB_SETTINGS,
        Builder.settings_sections,
        TAB_NOW,
        admin_only=True,
    ),
)
