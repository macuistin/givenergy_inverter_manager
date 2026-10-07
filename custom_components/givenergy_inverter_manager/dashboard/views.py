"""
views.py - the tabs and sub-views of the dashboard, and the Builder that fills them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ..const import CONF_FORECAST_ENTITY, CONF_INVERTER_TEMP_ENTITY
from ..core.devices import Device
from ..core.tariff import build_tariff
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
    admin_condition,
    button_badge,
    entity_list_card,
    entity_row,
    graph_card,
    grid_section,
    group,
    heading_block,
    heading_card,
    markdown_card,
    navigate_action,
    present,
    readonly_tile,
    slider_tile,
    state_markdown,
    state_ref,
    statistics_graph,
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
    EnergySources,
    energy_devices_template,
    energy_sources_template,
    survival_template,
    tariff_table,
)

# ── View paths ───────────────────────────────────────────────────────────────
# A tab is a view with a tab. A sub-view has none: a tile, heading or button on a tab opens it
# and its back arrow returns to that tab. Settings is the one sub-view only administrators see.
TAB_POWER_FLOW = "power-flow"
TAB_TODAY = "today"
TAB_BILL = "bill"
TAB_BATTERY = "battery"
SUB_IMMERSION = "immersion"
SUB_EV = "ev-charger"
SUB_COST = "cost"
SUB_SOLAR = "solar"
SUB_TARIFF = "tariff"
SUB_BATTERY = "battery-detail"
SUB_SETTINGS = "settings"
TABS = frozenset({TAB_POWER_FLOW, TAB_TODAY, TAB_BILL, TAB_BATTERY})


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
    return statistics_graph(
        [
            entity_row(cost.grid_import, "Grid Import"),
            entity_row(cost.house, "Rest of House"),
            entity_row(cost.ev, "EV Charging"),
            entity_row(cost.immersion, "Immersion"),
            entity_row(cost.export_earnings, "Export Earnings"),
        ],
        "day",
        14,
    )


# The immersion temperature settings: unique ID suffix and the name shown.
_THERMOSTAT_SETTINGS = (
    ("immersion_target_temp", "Target temp"),
    ("immersion_min_temp", "Minimum temp"),
    ("immersion_hysteresis", "Restart gap"),
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
        self.admin_ids = facts.admin_ids
        self.reg = Registry(er.async_get(hass) if registry is None else registry, entry.entry_id)
        self.cfg = entry_config(entry)
        self.external_ev = external_ev_power(hass)
        self.devices = Devices(self.reg)
        self.has_inverter_temp = bool(self.cfg.get(CONF_INVERTER_TEMP_ENTITY))
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
                "unit_of_measurement": " ",
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

    def _now(self) -> list:
        """The numbers worth a glance: charge first, then outlook, rate, cost, cheap rate."""
        return heading_block(
            heading_card("Now", "mdi:clock-outline", badges=self._settings_badges()),
            [
                self.tile(
                    "battery_soc",
                    "Battery",
                    color=BATTERY,
                    features=[BAR],
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

    def _flow_card(self, shown: frozenset[Device]) -> dict | None:
        """The power flow card with the devices of *shown* drawn beside the home node."""
        flow = self._flow_entities(shown)
        if not flow:
            return None
        card = flow_card(flow) if self.cards.use(POWER_FLOW_CARD) else flow_fallback(flow)
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
            self.tile("solar_forecast_raw_today", "Forecast", color=SOLAR),
            self.tile("solar_actual_vs_forecast_pct", "% of forecast", color=SOLAR),
        ]

    def _totals(self) -> list:
        return heading_block(
            heading_card("Energy today", "mdi:lightning-bolt", nav=self.go(TAB_TODAY)),
            [
                self.tile("solar_today", "Generated", color=SOLAR),
                *self._forecast_tiles(),
                self.tile("house_kwh_today", "Used", color=GRID),
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

    def power_flow_sections(self) -> list:
        return present(
            [
                grid_section(self._now()),
                self._dry_run_section(),
                grid_section(self._flow()),
                grid_section([*self._totals(), *self._devices()]),
            ]
        )

    # -- Immersion sub-view --

    def _immersion_chart(self, entities: ImmersionEntities, device: Device) -> dict | None:
        """An immersion chart in apexcharts-card, or a built-in card when it is not installed.

        Only a device that exists makes the file ask for apexcharts-card. A chart that waits
        for a device that is not there yet still picks its card, but adds no note about it.
        """
        if device in self.devices.present:
            use_apex = self.cards.use(APEX_CARD)
        else:
            use_apex = self.cards.installed(APEX_CARD)
        build = apex_immersion_chart if use_apex else builtin_immersion_chart
        return build(entities)

    def _temperature_card(self, shown: frozenset[Device]) -> dict | None:
        """The water temperature chart.

        With the thermostat (the switch and the sensor together) it adds the target and minimum
        lines, and the heater shaded while it is on.
        """
        both = Device.IMMERSION_THERMOSTAT in shown
        entities = ImmersionEntities(
            self.water_sensor("immersion_water_temperature"),
            self.thermostat("immersion_target_temp") if both else None,
            self.thermostat("immersion_min_temp") if both else None,
            self.immersion("immersion_power") if both else None,
        )
        return self._immersion_chart(entities, Device.IMMERSION_SENSOR)

    def _water_temperature(self) -> dict | None:
        """The water temperature chart, while there is a sensor. Not drawn without one."""
        cards = self.devices.variants((Device.IMMERSION_THERMOSTAT,), self._temperature_card)
        return group(
            heading_card("Water temperature", "mdi:thermometer-water"),
            [self.devices.show_with(card, Device.IMMERSION_SENSOR) for card in cards],
        )

    def _heater_on_off(self) -> dict | None:
        """The heater on or off, for a switch with no temperature sensor.

        With a sensor the temperature chart shades the heater, so this section hides itself.
        """
        entities = ImmersionEntities(None, None, None, self.immersion("immersion_power"))
        chart = self._immersion_chart(entities, Device.IMMERSION_SWITCH)
        return group(
            heading_card("Heater on or off", "mdi:flash"),
            [chart],
            visibility=[
                *self.devices.visible_with(Device.IMMERSION_SWITCH),
                *self.devices.visible_without(Device.IMMERSION_SENSOR),
            ],
        )

    def immersion_sections(self) -> list:
        """Sub-view: the water temperature, why the heater is on or off, and what it used.

        Each section follows its own device. A sensor with a switch shades the heater on the
        temperature chart. A switch with no sensor gets a small heater chart instead, and a
        sensor with no switch shows no heater or reason.
        """
        switch = Device.IMMERSION_SWITCH
        reason = state_markdown(self.entity("immersion_divert_reason"))
        return [
            self._water_temperature(),
            self._heater_on_off(),
            group(heading_card("Why", "mdi:help-circle-outline"), [reason], **self._when(switch)),
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

    def _when(self, *devices: Device) -> dict[str, list[dict]]:
        """The section option that shows a section while these devices are present."""
        return {"visibility": self.devices.visible_with(*devices)}

    def _immersion_settings_in_force(self) -> dict[str, Any] | None:
        """The immersion settings as they stand, to read. Administrators change them."""
        readings = [
            self.devices.show_with(
                readonly_tile(self.thermostat(suffix), name, IMMERSION), Device.IMMERSION_THERMOSTAT
            )
            for suffix, name in _THERMOSTAT_SETTINGS
        ]
        return group(
            heading_card("Settings in force", "mdi:tune"),
            [
                readonly_tile(self.immersion("auto_immersion"), "Auto divert", IMMERSION),
                readonly_tile(self.immersion("immersion_managed"), "Managed", IMMERSION),
                *readings,
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
                    state_markdown(decision),
                ],
                **shown,
            ),
        ]

    # -- Today --

    def _today_energy(self) -> dict | None:
        return group(
            heading_card("Energy", "mdi:lightning-bolt"),
            [
                self.tile("solar_today", "Generated", color=SOLAR),
                self.tile("house_kwh_today", "Used", color=GRID),
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
        return group(
            heading_card("Cost", "mdi:cash-multiple", nav=self.go(SUB_COST)),
            [
                self.tile("import_cost_today", "Import cost", color=GRID),
                self.tile("export_earnings_today", "Export earnings", color=BATTERY),
                self.tile("current_rate", "Rate now", color=GRID),
                self.tile("current_rate_period", "Rate period", color=GRID),
            ],
        )

    def _today_solar(self) -> dict | None:
        share = {"columns": FULL, "color": SOLAR, "features": [BAR]}
        return group(
            heading_card("Solar", "mdi:weather-sunny", nav=self.go(SUB_SOLAR)),
            [
                self.tile("self_sufficiency", "Self-sufficiency", **share),
                self.tile("solar_share", "Solar share", **share),
                self.tile("self_consumption", "Self-consumption", **share),
            ],
        )

    def today_sections(self) -> list:
        return [
            self._today_energy(),
            self._today_sources(),
            self._today_cost(),
            self._today_solar(),
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

    def cost_sections(self) -> list:
        """Sub-view: every cost line for today and the cost per day for two weeks."""
        cost = self._cost_entities(frozenset({Device.EV_CHARGER, Device.IMMERSION_SWITCH}))
        show = self.devices.show_with
        history = self.devices.variants(
            (Device.EV_CHARGER, Device.IMMERSION_SWITCH), self._cost_history_card
        )
        return [
            group(
                heading_card("Today", "mdi:calendar-today"),
                [
                    tile_card(cost.grid_import, "Grid import", color=GRID),
                    tile_card(cost.export_earnings, "Export earnings", color=BATTERY),
                    tile_card(cost.house, "Rest of house", color=GRID),
                    show(tile_card(cost.ev, "EV charging", color=EV), Device.EV_CHARGER),
                    show(
                        tile_card(cost.immersion, "Immersion", color=IMMERSION),
                        Device.IMMERSION_SWITCH,
                    ),
                    show(self._immersion_savings_tile(), Device.IMMERSION_SWITCH),
                ],
            ),
            group(heading_card("Last 14 days", "mdi:chart-bar"), history),
        ]

    def _immersion_savings_tile(self) -> dict | None:
        """What solar saved on the immersion today."""
        return tile_card(self.immersion("immersion_savings_today"), "Saved by solar", color=BATTERY)

    def solar_sections(self) -> list:
        """Sub-view: how solar compares with the forecast and the generation per hour."""
        solar_today = self.entity("solar_today")
        forecast = (
            [
                tile_card(solar_today, "Generated today", color=SOLAR),
                self.tile("solar_forecast_raw_today", "Forecast", color=SOLAR),
                self.tile("solar_actual_vs_forecast_pct", "% of forecast", color=SOLAR),
                self.tile("solar_forecast_kwh_today", "Plan forecast", color=SOLAR),
                self.tile("yesterday_forecast_accuracy_pct", "Yesterday", color=SOLAR),
            ]
            if self.has_forecast
            else []
        )
        return [
            group(heading_card("Against the forecast", "mdi:chart-line"), forecast),
            group(
                heading_card("Generation per hour", "mdi:chart-bar"),
                [statistics_graph([entity_row(solar_today, "Actual")], "hour", 2)],
            ),
        ]

    # -- Bill --

    def _bill_so_far(self) -> dict | None:
        tariff = self.go(SUB_TARIFF)
        badges = [button_badge("mdi:table", "Tariff", tariff)] if tariff else None
        return group(
            heading_card("Bill so far", "mdi:receipt-text", badges=badges),
            [
                self.tile("accrued_bill", "Accrued bill", color=GRID),
                self.tile("projected_bill", "Projected bill", color=GRID),
                self.tile("import_cost_this_month", "Import cost", color=GRID),
                self.tile("export_earnings_this_month", "Export credit", color=BATTERY),
            ],
        )

    def _bill_period(self) -> dict | None:
        return group(
            heading_card("This bill period", "mdi:calendar-month"),
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
        table = markdown_card(tariff_table(build_tariff(self.cfg), self.cfg))
        return [group(heading_card("Tariff in use", "mdi:table"), [table])]

    # -- Battery --

    def _battery_now(self) -> dict | None:
        battery_soc = self.entity("battery_soc")
        history = entity_list_card(
            [entity_row(battery_soc, "Charge")], {"type": "history-graph"}, hours_to_show=24
        )
        return group(
            heading_card("Battery", "mdi:battery-heart-variant", nav=self.go(SUB_BATTERY)),
            [
                tile_card(battery_soc, "Charge", color=BATTERY, features=[BAR]),
                self.tile("battery_power", "Power", color=BATTERY, features=[TREND]),
                graph_card(history) if history else None,
            ],
        )

    def _charge_plan(self) -> dict | None:
        return group(
            heading_card("Tonight's charge plan", "mdi:weather-night"),
            [
                self.tile("overnight_charge_target", "Target tonight", color=BATTERY),
                self.tile("overnight_charge_cost", "Est. cost", color=GRID),
                self.tile("estimated_soc_at_sunrise", "At sunrise", color=BATTERY),
                self.tile(
                    "cheap_rate_floor_status", "Rate floor", color=GRID, icon="mdi:floor-plan"
                ),
            ],
        )

    def _charge_settings_in_force(self) -> dict[str, Any] | None:
        """The charge settings as they stand, to read. Administrators change them."""
        return group(
            heading_card("Charge settings in force", "mdi:tune"),
            [
                readonly_tile(
                    self.entity("charge_target_override"), "Target override", BATTERY
                ),
                readonly_tile(
                    self.entity("charge_target_override_enabled"), "Override on", BATTERY
                ),
                readonly_tile(self.entity("skip_charge_override"), "Skip tonight", BATTERY),
                self.tile("dry_run_active", "Dry run", color=GRID, icon="mdi:test-tube"),
            ],
        )

    def battery_sections(self) -> list:
        return [self._battery_now(), self._charge_plan(), self._charge_settings_in_force()]

    def _battery_health(self) -> dict | None:
        return group(
            heading_card("Battery health", "mdi:battery-heart-variant"),
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

    def battery_detail_sections(self) -> list:
        """Sub-view: why tonight's plan is what it is, and the battery's health."""
        return [
            grid_section(
                heading_block(
                    heading_card("Night survival", "mdi:weather-night"), self._night_survival()
                ),
                heading_block(
                    subheading_card("Tonight's charge target", "mdi:battery-charging"),
                    [state_markdown(self.entity("overnight_charge_reason"))],
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
            return [markdown_card(survival_template(level, status, sunrise))]
        if status:
            return [markdown_card(f"**Night survival**\n\n{state_ref(status)}")]
        return []

    # -- Settings --

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
            text += f"\n\n**Last skipped action:** {state_ref(skipped)}"
        return group(
            heading_card("Dry run is on", "mdi:test-tube"),
            [markdown_card(text)],
            visibility=[{"condition": "state", "entity": dry_run_active, "state": "True"}],
        )

    def _charging_controls(self) -> dict | None:
        return group(
            heading_card("Overnight charging", "mdi:battery-charging"),
            [
                slider_tile(self.entity("charge_target_override"), "Charge target", BATTERY),
                toggle_tile(self.entity("charge_target_override_enabled"), "Use target", BATTERY),
                toggle_tile(self.entity("skip_charge_override"), "Skip tonight", BATTERY),
            ],
        )

    def _immersion_sliders(self) -> list:
        """The temperature sliders. They act only with a switch and a sensor, so only then show."""
        return [
            self.devices.show_with(
                slider_tile(self.thermostat(suffix), name, IMMERSION), Device.IMMERSION_THERMOSTAT
            )
            for suffix, name in _THERMOSTAT_SETTINGS
        ]

    def _immersion_controls(self) -> dict | None:
        return group(
            heading_card("Immersion heater", "mdi:water-boiler"),
            [
                toggle_tile(self.immersion("auto_immersion"), "Auto divert", IMMERSION),
                toggle_tile(self.immersion("immersion_managed"), "Managed", IMMERSION),
                state_markdown(self.entity("immersion_divert_reason")),
                *self._immersion_sliders(),
            ],
            **self._when(Device.IMMERSION_SWITCH),
        )

    def settings_sections(self) -> list[Any]:
        """Sub-view, for administrators only: every switch and slider that changes behaviour.

        Empty without an administrator ID, so the view is left out and no one sees it.
        """
        if not self.admin_ids:
            return []
        return [self._charging_controls(), self._immersion_controls()]


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
    ViewSpec(
        "Power Flow", "mdi:solar-power-variant", TAB_POWER_FLOW, Builder.power_flow_sections
    ),
    ViewSpec("Today", "mdi:calendar-today", TAB_TODAY, Builder.today_sections),
    ViewSpec("Bill", "mdi:receipt-text", TAB_BILL, Builder.bill_sections),
    ViewSpec("Battery", "mdi:battery-charging", TAB_BATTERY, Builder.battery_sections),
)
SUBVIEWS = (
    ViewSpec(
        "Immersion", "mdi:water-boiler", SUB_IMMERSION, Builder.immersion_sections, TAB_POWER_FLOW
    ),
    ViewSpec("EV charger", "mdi:ev-station", SUB_EV, Builder.ev_sections, TAB_POWER_FLOW),
    ViewSpec("Cost breakdown", "mdi:cash-multiple", SUB_COST, Builder.cost_sections, TAB_TODAY),
    ViewSpec(
        "Solar and forecast", "mdi:weather-sunny", SUB_SOLAR, Builder.solar_sections, TAB_TODAY
    ),
    ViewSpec("Tariff", "mdi:table", SUB_TARIFF, Builder.tariff_sections, TAB_BILL),
    ViewSpec(
        "Battery detail",
        "mdi:battery-heart-variant",
        SUB_BATTERY,
        Builder.battery_detail_sections,
        TAB_BATTERY,
    ),
    ViewSpec(
        "Settings",
        "mdi:tune",
        SUB_SETTINGS,
        Builder.settings_sections,
        TAB_POWER_FLOW,
        admin_only=True,
    ),
)
