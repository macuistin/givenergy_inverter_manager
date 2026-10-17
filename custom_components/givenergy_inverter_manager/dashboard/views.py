"""
views.py - the views of the dashboard, and the Builder that fills them.

The dashboard tells a story. Home energy says what is happening now and what needs attention: the
live power flow under a heading that carries the day's figures, a sentence on what the house runs
on and what tonight holds, one button each for the hot water and the EV charger with their
figures, and a banner only while something needs the user. Today, Tonight, Tomorrow and Bill &
tariff are tabs with an icon each. Hot water, EV charger and Settings are one tap away on
sub-views. Each view opens with a sentence, then one picture that tells its story, then a few
figures in a row, then the detail.
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
    IMMERSION_SWITCH_COOLDOWN_MINUTES,
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
    BATTERY,
    BATTERY_HEX,
    CHART_TITLE_CSS,
    COST_HEX,
    EV,
    FULL,
    GRID,
    GRID_HEX,
    HEX,
    HOUSE_HEX,
    IMMERSION,
    SOLAR,
    SOLAR_HEX,
    TABLE_CSS,
    TOTAL_CSS,
    WATER_HEX,
    WHOLE_WIDTH,
    WIDE,
    admin_condition,
    bar_tile,
    button_badge,
    day_bars,
    distribution_card,
    entity_badge,
    entity_row,
    glance_card,
    grid_section,
    group,
    heading_block,
    heading_card,
    history_graph,
    logbook_card,
    markdown_card,
    navigate_action,
    present,
    readonly_tile,
    stacked_daily_graph,
    stacked_hourly_graph,
    state_markdown,
    state_ref,
    stepper_row,
    styled,
    subheading_card,
    switch_tile,
    tile_card,
    view_config,
    weather_card,
)
from .charts import (
    ImmersionEntities,
    apex_immersion_chart,
    apex_solar_forecast_chart,
    builtin_immersion_chart,
    flow_card,
    flow_fallback,
)
from .devices import Devices, with_visibility
from .hacs import APEX_CARD, CARD_MOD, POWER_FLOW_CARD, HacsCards
from .registry import HostFacts, Registry, entry_config, external_ev_power
from .templates import (
    ChargerNow,
    DayTotals,
    PowerNow,
    WaterNow,
    alt_heat_schedule_template,
    currency_symbol,
    ev_story_template,
    now_story_template,
    plan_text_template,
    saved_template,
    setup_checklist_template,
    survival_template,
    tariff_changes_table,
    tariff_table,
    today_story_template,
    tomorrow_story_template,
    tonight_headline_template,
    water_story_template,
)

# ── View paths ───────────────────────────────────────────────────────────────
# Home energy and the four days and bills views are tabs, shown as icons in the bar. The devices
# and Settings are sub-views whose back arrow returns to Home energy. Every view keeps the path it
# had, so a saved link still opens the same page.
TAB_NOW = "power-flow"
TAB_TODAY = "today"
TAB_PLAN = "plan"
TAB_TOMORROW = "tomorrow"
TAB_BILL = "bill"
SUB_IMMERSION = "immersion"
SUB_EV = "ev-charger"
SUB_SETTINGS = "settings"
TABS = frozenset({TAB_NOW, TAB_TODAY, TAB_PLAN, TAB_TOMORROW, TAB_BILL})

# How far back the charts reach, and how tall they are in grid rows. A bill period is a
# calendar month, so 31 days always holds the one in progress.
_BILL_COST_DAYS = 31
_WEEK = 7
_CHART_ROWS = 5
_SMALL_CHART_ROWS = 3
_LOGBOOK_HOURS = 24
_BATTERY_HOURS = 36

# Tonight's charge, named the same wherever it is shown or set.
FIXED_TARGET_NAME = "Fixed target"
CHARGE_TO_NAME = "Charge to"
# The immersion switches, named for what they do.
AUTO_DIVERT_NAME = "Use spare solar"
MANAGED_NAME = "Heat now"
SCHEDULE_NAME = "Scheduled heat"
# The immersion temperature settings: unique ID suffix and the name shown.
_THERMOSTAT_SETTINGS = (
    ("immersion_target_temp", "Heat to"),
    ("immersion_min_temp", "Never below"),
    ("immersion_hysteresis", "Restart drop"),
)
# The weather entity named first when several exist: the one the Met.no integration makes.
_PREFERRED_WEATHER = ("weather.forecast_home", "weather.home")

# What each setting does, in a line each, folded under its group on the Settings view.
_CHARGE_HELP = (
    ("Fixed target", "charge to the number below tonight, instead of the plan."),
    ("Skip tonight", "no grid charge tonight."),
)
_PLANNING_HELP = (
    ("Cheap rate floor", "in the cheapest rate, top the battery up to this. 0 is off."),
    ("Skip charge above", "skip tonight's charge above this, if tomorrow looks sunny."),
    ("Forecast caution", "0 plans on the typical forecast, 1 on the low one."),
    ("Re-plan overnight", "work the target out again in the cheap window, three times at most."),
)
_HEAT_NOW_HELP = (
    "Heat now",
    "heat to the target now. Turning it off holds the heater off for "
    f"{IMMERSION_SWITCH_COOLDOWN_MINUTES} minutes.",
)
_RESTART_DROP_HELP = (
    "Restart drop",
    "how far the water falls below the target before it heats again.",
)
_DIVERT_HELP = ("Min battery, Min spare solar", "spare solar goes to the water only above both.")
_SYSTEM_HELP = (
    ("Dry run", "plan as normal but send nothing to the inverter, the immersion or the car."),
    ("Verbose logging", "write the integration's decisions to the Home Assistant log."),
)


def _help(lines: tuple[tuple[str, str], ...]) -> dict:
    """What a group of settings does, folded away until tapped."""
    body = "\n".join(f"- **{name}**: {text}" for name, text in lines)
    return markdown_card(f"<details><summary>What these do</summary>\n\n{body}\n</details>")


def _grey(text: str) -> str:
    """Text in the grey of secondary text. The markdown card keeps a font colour."""
    return f"<font color='#9e9e9e'>{text}</font>"


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


def _weather_entity(hass: HomeAssistant) -> str | None:
    """The weather entity for the forecast cards, or None when there is none.

    The Met.no default comes first when it exists. Otherwise the first in name order, so the
    choice does not change from one build to the next.
    """
    found = sorted(state.entity_id for state in hass.states.async_all("weather"))
    for preferred in _PREFERRED_WEATHER:
        if preferred in found:
            return preferred
    return found[0] if found else None


def _half_hour_forecast(hass: HomeAssistant, entity: str | None) -> str | None:
    """The forecast entity, when it carries the half-hourly forecast Solcast publishes."""
    if not entity:
        return None
    state = hass.states.get(entity)
    attributes = getattr(state, "attributes", None)
    return entity if isinstance(attributes, dict) and "detailedForecast" in attributes else None


@dataclass(frozen=True)
class _CostEntities:
    """Today's cost sensors, and the parts of the import cost by what used it."""

    grid_import: str | None
    export_earnings: str | None
    house: str | None
    ev: str | None
    immersion: str | None


class Builder:
    """Builds the sections of each view from the entities that exist.

    Views link to sub-views, and a link is left out when its sub-view is empty. So the
    sub-views are built first, with build_subviews, and Home energy after.
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
        self.series_colours = facts.series_colours
        self.reg = Registry(er.async_get(hass) if registry is None else registry, entry.entry_id)
        self.cfg = entry_config(entry)
        self.symbol = currency_symbol(self.cfg)
        self.external_ev = external_ev_power(hass)
        self.devices = Devices(self.reg)
        self.has_inverter_temp = _has_inverter_temp(hass, self.cfg)
        self.forecast = self.cfg.get(CONF_FORECAST_ENTITY) or None
        self.half_hour_forecast = _half_hour_forecast(hass, self.forecast)
        self.weather = _weather_entity(hass)
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

    def row(self, entity: str | None, name: str, colour: str | None = None) -> dict | None:
        """An entity row, in its colour on a release whose charts draw one."""
        if colour and self.series_colours:
            return entity_row(entity, name, color=colour)
        return entity_row(entity, name)

    def nav_row(self, entity: str | None, name: str, path: str) -> dict | None:
        """A figure in a row of figures that opens a view when tapped."""
        nav = self.go(path)
        return entity_row(entity, name, tap_action=nav) if nav else entity_row(entity, name)

    def table(self, card: dict | None, *, total: bool = False) -> dict | None:
        """A markdown card holding a table, styled by card-mod when it is installed."""
        if card is None or not self.cards.installed(CARD_MOD):
            return card
        return styled(card, TABLE_CSS + (TOTAL_CSS if total else ""), inner=True)

    def chart_title(self, card: dict | None) -> dict | None:
        """A chart's own title in small grey type, when card-mod is installed."""
        if card is None or not card.get("title") or not self.cards.installed(CARD_MOD):
            return card
        return styled(card, CHART_TITLE_CSS)

    def attribute_card(self, entity: str | None, attribute: str) -> dict | None:
        """A markdown card that prints one attribute. None while the entity is missing."""
        if not entity:
            return None
        return markdown_card(f"{{{{ state_attr('{entity}', '{attribute}') }}}}")

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
        """The Settings icon of the power flow heading, or None when no one may open it."""
        nav = self.go(SUB_SETTINGS)
        if not nav:
            return None
        visibility = [admin_condition(self.admin_ids)]
        return [button_badge("mdi:tune", None, nav, visibility)]

    # -- Home energy: the power flow --

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

    def _flow_card(self, shown: frozenset[Device]) -> dict | None:
        """The power flow card with the devices of *shown* drawn beside the home node."""
        flow = self._flow_entities(shown)
        if not flow:
            return None
        card = flow_card(flow) if self.cards.installed(POWER_FLOW_CARD) else flow_fallback(flow)
        return {**card, "grid_options": {"columns": FULL}} if card else None

    def _flow(self) -> dict | None:
        """The power flow, two columns wide, under a heading that carries the day's figures.

        The heading holds the Settings icon and the day's solar, import cost and self-sufficiency.
        A sentence on what the house runs on and what tonight holds sits between it and the flow.

        One card for each combination of the car charger and immersion being there. The card
        cannot hide one device, so a stored dashboard shows the card built for the devices
        present, and swaps to another when a device comes or goes.
        """
        devices = (Device.EV_CHARGER, Device.IMMERSION_SWITCH)
        cards = self.devices.variants(devices, self._flow_card)
        heading = heading_card(
            "Power flow",
            "mdi:transmission-tower",
            badges=[*(self._settings_badges() or []), *self._today_badges()],
        )
        return group(heading, [self._now_story(), *cards], **WIDE)

    # -- Home energy: right now --

    def _now_story(self) -> dict | None:
        """What the house runs on now and what tonight holds. None without the power sensors."""
        power = [self.entity(key) for key in ("solar_power", "house_load", "battery_power")]
        grid = self.entity("grid_power")
        if not all(power) or not grid:
            return None
        story = now_story_template(
            PowerNow(*power, grid),
            self.entity("overnight_charge_target"),
            self.entity("night_survival_confidence"),
        )
        return markdown_card(story)

    def _today_badges(self) -> list[dict]:
        return present(
            [
                entity_badge(self.entity("solar_today"), "mdi:solar-power", color="orange"),
                entity_badge(self.entity("import_cost_today"), "mdi:cash", color="purple"),
                entity_badge(
                    self.entity("self_sufficiency"), "mdi:home-lightning-bolt", color="teal"
                ),
            ]
        )

    @staticmethod
    def _two_up(card: dict | None) -> dict | None:
        """The figures two to a row, so a long value such as "disconnected" is not cut short."""
        if card is None:
            return None
        return {**card, "columns": min(card["columns"], 2)}

    def _water_button_card(self, shown: frozenset[Device]) -> dict | None:
        """The hot water figures for the devices of *shown*, each opening the Hot water view."""
        sensor = Device.IMMERSION_SENSOR in shown
        heater = Device.IMMERSION_SWITCH in shown
        temperature = self.water_sensor("immersion_water_temperature") if sensor else None
        power = self.immersion("immersion_power") if heater else None
        today = self.immersion("immersion_today") if heater else None
        cost = self.immersion("immersion_cost_today") if heater else None
        return self._two_up(
            glance_card(
                [
                    self.nav_row(temperature, "Water", SUB_IMMERSION),
                    self.nav_row(power, "Heater", SUB_IMMERSION),
                    self.nav_row(today, "Heated", SUB_IMMERSION),
                    self.nav_row(cost, "Cost", SUB_IMMERSION),
                ]
            )
        )

    def _charger_button_card(self) -> dict | None:
        """The EV charger figures, each opening the EV charger view."""
        return self._two_up(
            glance_card(
                [
                    self.nav_row(self.ev("ev_charger_state"), "State", SUB_EV),
                    self.nav_row(self.ev("ev_session_energy"), "This charge", SUB_EV),
                    self.nav_row(self.ev("zappi_today"), "Today", SUB_EV),
                    self.nav_row(self.ev("zappi_cost_today"), "Cost", SUB_EV),
                ]
            )
        )

    def _device_buttons(self) -> dict | None:
        """A button for the hot water and one for the EV charger, each with its figures.

        The heading opens the device's view, and so does each figure. A device that is not
        there leaves nothing: its heading and its figures carry a visibility condition, so
        one that arrives later shows with no regeneration.
        """
        devices = self.devices
        water_cards = devices.variants(
            (Device.IMMERSION_SWITCH, Device.IMMERSION_SENSOR), self._water_button_card
        )
        water = with_visibility(
            heading_card("Hot water", "mdi:water-boiler", nav=self.go(SUB_IMMERSION)),
            devices.visible_with_any(Device.IMMERSION_SWITCH, Device.IMMERSION_SENSOR),
        )
        ev = with_visibility(
            heading_card("EV charger", "mdi:ev-station", nav=self.go(SUB_EV)),
            devices.visible_with(Device.EV_CHARGER),
        )
        return grid_section(
            heading_block(water, water_cards),
            heading_block(ev, [devices.show_with(self._charger_button_card(), Device.EV_CHARGER)]),
        )

    def _repairs_section(self) -> dict | None:
        """This integration's open repairs, shown only while there is one, to administrators.

        Home Assistant's own repairs card lists every repair in Home Assistant and has no
        filter, so this reads the integration's own count and list. Only an administrator can
        act on a repair, so no one else sees it.
        """
        repairs = self.entity("active_repairs")
        if not repairs or not self.admin_ids:
            return None
        return group(
            heading_card("Needs your attention", "mdi:alert-circle-outline"),
            [self.attribute_card(repairs, "summary")],
            visibility=[
                {"condition": "numeric_state", "entity": repairs, "above": 0},
                admin_condition(self.admin_ids),
            ],
            **WHOLE_WIDTH,
        )

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

    def now_sections(self) -> list:
        """The banners while they apply, the power flow, and the device buttons.

        On a laptop the buttons sit beside the power flow. On a phone every section is one
        column and they stack in this order.
        """
        return present(
            [
                self._dry_run_section(),
                self._charge_conflict_section(),
                self._setup_checklist(),
                self._repairs_section(),
                self._flow(),
                self._device_buttons(),
            ]
        )

    # -- Today --

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

    def _today_story(self) -> dict | None:
        solar = self.entity("solar_today")
        if not solar:
            return None
        totals = DayTotals(
            solar,
            self.entity("solar_forecast_raw_today") if self.forecast else None,
            self.entity("house_kwh_today"),
            self.entity("self_sufficiency"),
            self.entity("import_cost_today"),
            self.entity("export_earnings_today"),
        )
        return markdown_card(today_story_template(totals, self.symbol))

    def _last_day_by_hour(self) -> dict | None:
        """Where each hour's energy came from over the last day, as stacked bars.

        The three sources stack to what the house and the battery took in that hour.
        """
        return stacked_hourly_graph(
            [
                self.row(self.entity("solar_today"), "Solar", SOLAR_HEX),
                self.row(self.entity("battery_discharge_kwh_today"), "From battery", BATTERY_HEX),
                self.row(self.entity("import_today"), "From grid", GRID_HEX),
            ],
            _CHART_ROWS,
        )

    def _today_story_section(self) -> dict | None:
        return grid_section(
            heading_block(heading_card("Today", "mdi:calendar-today"), [self._today_story()]),
            heading_block(
                subheading_card("Last 24 hours", "mdi:chart-bar-stacked"),
                [self._last_day_by_hour()],
            ),
            **WIDE,
        )

    def _cost_split(self, shown: frozenset[Device]) -> dict | None:
        cost = self._cost_entities(shown)
        return distribution_card(
            [
                self.row(cost.house, "House", HOUSE_HEX),
                self.row(cost.ev, "EV", BATTERY_HEX),
                self.row(cost.immersion, "Hot water", WATER_HEX),
            ]
        )

    def _today_split(self) -> dict | None:
        """Where the energy came from and what it cost, as split bars, then the day in figures."""
        sources = distribution_card(
            [
                self.row(self.entity("solar_today"), "Solar", SOLAR_HEX),
                self.row(self.entity("battery_discharge_kwh_today"), "Battery", BATTERY_HEX),
                self.row(self.entity("import_today"), "Grid", GRID_HEX),
            ]
        )
        costs = self.devices.variants(
            (Device.EV_CHARGER, Device.IMMERSION_SWITCH), self._cost_split
        )
        figures = glance_card(
            [
                entity_row(self.entity("solar_today"), "Solar"),
                entity_row(self.entity("house_kwh_today"), "Used"),
                entity_row(self.entity("import_today"), "Imported"),
                entity_row(self.entity("export_today"), "Exported"),
            ]
        )
        shares = [
            bar_tile(self.entity("solar_share"), "Home use from solar", SOLAR),
            bar_tile(self.entity("self_consumption"), "Solar kept at home", SOLAR),
        ]
        return grid_section(
            heading_block(
                heading_card("Where it came from", "mdi:home-lightning-bolt-outline"), [sources]
            ),
            heading_block(subheading_card("What it cost", "mdi:cash"), costs),
            heading_block(subheading_card("In numbers", "mdi:numeric"), [figures]),
            heading_block(subheading_card("Solar", "mdi:solar-power"), shares),
        )

    def _solar_week(self) -> dict | None:
        """What was generated on each of the last 7 days, and the forecast in figures."""
        week = day_bars([self.row(self.entity("solar_today"), "Solar", SOLAR_HEX)], _WEEK)
        forecast = (
            glance_card(
                [
                    entity_row(self.entity("solar_forecast_raw_today"), "Forecast"),
                    entity_row(self.entity("solar_actual_vs_forecast_pct"), "Reached"),
                    entity_row(self.entity("solar_forecast_kwh_today"), "Planned on"),
                    entity_row(self.entity("yesterday_forecast_accuracy_pct"), "Yesterday"),
                ]
            )
            if self.forecast
            else None
        )
        return grid_section(
            heading_block(heading_card(f"Solar, last {_WEEK} days", "mdi:calendar-week"), [week]),
            heading_block(subheading_card("Forecast", "mdi:weather-partly-cloudy"), [forecast]),
        )

    def today_sections(self) -> list:
        """Sub-view: the day in a sentence and by the hour, the split bars, the solar week."""
        return [self._today_story_section(), self._today_split(), self._solar_week()]

    # -- Tonight --

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

    def _tonight(self) -> dict | None:
        """Whether tonight charges and why, the charge's cost, and the battery as bars."""
        target = self.entity("overnight_charge_target")
        headline = (
            markdown_card(tonight_headline_template(target, self.entity("charge_plan")))
            if target
            else None
        )
        reason = self.entity("overnight_charge_reason")
        why = (
            markdown_card(
                "<details><summary>Why this plan</summary>\n\n"
                f"{state_ref(reason, ATTR_FULL_TEXT)}\n\n</details>"
            )
            if reason
            else None
        )
        return group(
            heading_card("Tonight", "mdi:weather-night"),
            [
                headline,
                *self._night_survival(),
                glance_card(
                    [
                        entity_row(self.entity("overnight_charge_cost"), "Charge cost"),
                        entity_row(self.entity("estimated_soc_at_sunrise"), "Sunrise if no charge"),
                    ]
                ),
                bar_tile(self.entity("battery_soc"), "Battery now", BATTERY),
                bar_tile(
                    self.entity("estimated_soc_at_sunrise_with_charge"), "At sunrise", BATTERY
                ),
                why,
                *self._in_force(),
            ],
        )

    def _battery_history(self) -> dict | None:
        return group(
            heading_card("Battery, last day and a half", "mdi:chart-line"),
            [
                history_graph(
                    [self.row(self.entity("battery_soc"), "Battery", BATTERY_HEX)],
                    _BATTERY_HOURS,
                    4,
                )
            ],
            **WIDE,
        )

    def _weather(self) -> dict | None:
        return group(
            heading_card("Next few days", "mdi:weather-partly-cloudy"), [weather_card(self.weather)]
        )

    def _health(self) -> dict | None:
        """The battery's wear and the inverter's temperature, in a row of figures."""
        return group(
            heading_card("Battery health", "mdi:battery-heart-variant"),
            [
                glance_card(
                    [
                        entity_row(self.entity("battery_cycles"), "Cycles"),
                        entity_row(self.entity("battery_remaining_life"), "Life left"),
                        entity_row(self.entity("days_since_full_charge"), "Since full"),
                        entity_row(self.inverter_temp("inverter_temperature"), "Inverter"),
                        entity_row(self.inverter_temp("inverter_temperature_status"), "Status"),
                    ]
                )
            ],
        )

    def plan_sections(self) -> list:
        """Sub-view: tonight's charge, the battery's last day and a half, the weather, health."""
        return [self._tonight(), self._battery_history(), self._weather(), self._health()]

    # -- Tomorrow --

    def _tomorrow(self) -> dict | None:
        """Tomorrow's solar in a sentence and through the day, and the battery at dawn."""
        if not self.forecast:
            return None
        story = tomorrow_story_template(
            self.forecast,
            self.entity("overnight_charge_target"),
            self.entity("estimated_soc_at_sunrise_with_charge"),
        )
        curve = (
            apex_solar_forecast_chart(self.half_hour_forecast)
            if self.half_hour_forecast and self.cards.installed(APEX_CARD)
            else None
        )
        return grid_section(
            heading_block(
                heading_card("Tomorrow", "mdi:weather-sunset-up"),
                [
                    markdown_card(story),
                    glance_card(
                        [
                            entity_row(self.forecast, "Solar"),
                            entity_row(
                                self.entity("estimated_soc_at_sunrise_with_charge"), "At sunrise"
                            ),
                        ]
                    ),
                ],
            ),
            heading_block(subheading_card("Solar through the day", "mdi:solar-power"), [curve]),
            **WIDE,
        )

    def _tomorrow_cost(self) -> dict | None:
        outlook = self.entity("tomorrow_outlook")
        return grid_section(
            heading_block(
                heading_card("What it should cost", "mdi:cash"),
                [self.table(self.attribute_card(outlook, "table"), total=True)],
            ),
            heading_block(
                subheading_card("Weather", "mdi:weather-partly-cloudy"),
                [weather_card(self.weather)],
            ),
        )

    def tomorrow_sections(self) -> list:
        """Sub-view: tomorrow's solar, the battery at dawn, the expected cost and the weather."""
        return [self._tomorrow(), self._tomorrow_cost()]

    # -- Bill & tariff --

    def _paid_and_would_have(self) -> dict | None:
        """What each day cost, beside what it would have cost with no solar or battery."""
        return day_bars(
            [
                self.row(self.entity("import_cost_today"), "You paid", COST_HEX),
                self.row(self.entity("cost_without_solar_today"), "Would have paid", SOLAR_HEX),
            ],
            14,
            4,
        )

    def _cost_by_use(self, shown: frozenset[Device]) -> dict | None:
        """The import cost of each day as stacked bars, split by what used it."""
        cost = self._cost_entities(shown)
        return stacked_daily_graph(
            [
                self.row(cost.house, "House", HOUSE_HEX),
                self.row(cost.ev, "EV", BATTERY_HEX),
                self.row(cost.immersion, "Hot water", WATER_HEX),
            ],
            _BILL_COST_DAYS,
            4,
        )

    def _bill_period(self) -> dict | None:
        """The saving in a sentence, the period in two rows of figures, and the cost by day."""
        paid = self.entity("accrued_bill")
        without = self.entity("bill_without_solar")
        saved = (
            markdown_card(saved_template(paid, without, self.symbol)) if paid and without else None
        )
        by_use = self.devices.variants(
            (Device.EV_CHARGER, Device.IMMERSION_SWITCH), self._cost_by_use
        )
        return grid_section(
            heading_block(
                heading_card("This bill period", "mdi:receipt-text"),
                [
                    saved,
                    glance_card(
                        [
                            entity_row(paid, "So far"),
                            entity_row(self.entity("projected_bill"), "Heading for"),
                            entity_row(self.entity("days_remaining_in_period"), "Days left"),
                        ]
                    ),
                    glance_card(
                        [
                            entity_row(self.entity("import_cost_this_month"), "Import cost"),
                            entity_row(self.entity("export_earnings_this_month"), "Export credit"),
                            entity_row(self.entity("avg_import_rate_this_month"), "Avg per kWh"),
                        ]
                    ),
                ],
            ),
            heading_block(
                subheading_card("Each day: what you paid and would have paid", "mdi:chart-bar"),
                [self._paid_and_would_have()],
            ),
            heading_block(
                subheading_card(
                    f"Cost per day by use, last {_BILL_COST_DAYS} days", "mdi:chart-bar-stacked"
                ),
                by_use,
            ),
            **WIDE,
        )

    def _tariff(self) -> dict | None:
        """When each rate applies, as a strip of the last day, then the rates themselves."""
        period = self.entity("current_rate_period")
        strip = history_graph([entity_row(period, "Rate")], 24, 1) if period else None
        if strip:
            strip["grid_options"] = {"columns": FULL}
        if report := self.entity("tariff_in_use"):
            # The report sensor builds the tables from the options each cycle, so a stored
            # copy of the dashboard follows a tariff change without a rebuild.
            return group(
                heading_card("Tariff", "mdi:clock-outline"),
                [strip, self.table(self.attribute_card(report, "html"))],
            )
        today = dt_util.now().date()
        rates = tariff_table(build_tariff(tariff_in_force(self.cfg, today)), self.cfg)
        return grid_section(
            heading_block(
                heading_card("Tariff", "mdi:clock-outline"),
                [strip, self.table(markdown_card(rates))],
            ),
            self._scheduled_changes(today),
        )

    def _scheduled_changes(self, today: date) -> list:
        """The rate changes that have not started, under the rates. Empty when none."""
        changes = scheduled_tariff_changes(self.cfg, today)
        text = tariff_changes_table(changes, self.cfg, last_tariff_review(self.cfg))
        heading = subheading_card("Scheduled rate changes", "mdi:calendar-clock")
        return heading_block(heading, [self.table(markdown_card(text)) if text else None])

    def _bill_tables(self) -> list:
        """The bill line by line, each day, and the last bill, each a small table of its own."""
        audit = self.entity("bill_audit")
        previous = self.entity("previous_bill_audit")
        return [
            group(
                heading_card("This bill, line by line", "mdi:receipt-text-outline"),
                [self.table(self.attribute_card(audit, "bill_table"), total=True)],
            ),
            group(
                heading_card("Each day", "mdi:calendar-month-outline"),
                [self.table(self.attribute_card(audit, "days_table"))],
            ),
            group(
                heading_card("Last bill", "mdi:receipt-text-clock-outline"),
                [self.table(self.attribute_card(previous, "summary_table"), total=True)],
            ),
        ]

    def bill_sections(self) -> list:
        """Sub-view: the bill period and its charts, the tariff, then the bill's tables.

        On a laptop the tariff sits beside the period and the three tables fill the row below.
        On a phone they stack in this order.
        """
        return [self._bill_period(), self._tariff(), *self._bill_tables()]

    # -- Hot water --

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

    def _water_story(self, shown: frozenset[Device]) -> dict:
        """The water in a sentence. The target, the heater and why only with the thermostat.

        A sensor with no switch has no heater and no target, so its sentence gives the
        temperature alone.
        """
        both = Device.IMMERSION_THERMOSTAT in shown
        story = WaterNow(
            self.water_sensor("immersion_water_temperature"),
            self.thermostat("immersion_target_temp") if both else None,
            self.immersion("immersion_power") if both else None,
            self.entity("immersion_divert_reason") if both else None,
        )
        return markdown_card(water_story_template(story))

    def _water_now(self) -> dict | None:
        """The water in a sentence, the heater's day in figures, and the temperature chart."""
        stories = self.devices.variants((Device.IMMERSION_THERMOSTAT,), self._water_story)
        # Without a sensor there is no sentence on the water, so why the heater is on or off
        # stands alone.
        reason = with_visibility(
            state_markdown(self.entity("immersion_divert_reason"), ATTR_FULL_TEXT),
            [
                *self.devices.visible_with(Device.IMMERSION_SWITCH),
                *self.devices.visible_without(Device.IMMERSION_SENSOR),
            ],
        )
        figures = glance_card(
            [
                entity_row(self.immersion("immersion_power"), "Heater"),
                entity_row(self.immersion("immersion_today"), "Heated"),
                entity_row(self.immersion("immersion_cost_today"), "Cost"),
                entity_row(self.immersion("immersion_savings_today"), "Solar saved"),
            ]
        )
        charts = self.devices.variants((Device.IMMERSION_THERMOSTAT,), self._temperature_card)
        return group(
            heading_card("Hot water", "mdi:water-boiler"),
            [
                *[self.devices.show_with(card, Device.IMMERSION_SENSOR) for card in stories],
                reason,
                self.devices.show_with(figures, Device.IMMERSION_SWITCH),
                *[self.devices.show_with(card, Device.IMMERSION_SENSOR) for card in charts],
            ],
            **self._when_any(Device.IMMERSION_SWITCH, Device.IMMERSION_SENSOR),
            **WIDE,
        )

    def _water_plan(self) -> dict | None:
        """The planned heating for the next ready time, the cheapest source, and the settings."""
        water = self.water_sensor("immersion_water_temperature")
        source = self.alt_heat_advice("water_heating_cheapest_source")
        schedule = self.devices.visible_while_on(self.thermostat("immersion_schedule"))
        # The sensor holds the planned heating only while scheduled heating is on.
        plan = with_visibility(
            markdown_card(plan_text_template(water)),
            [
                *self.devices.visible_with(Device.IMMERSION_THERMOSTAT, Device.IMMERSION_SENSOR),
                *schedule,
            ],
        )
        cheapest = (
            self.devices.show_with(
                markdown_card(
                    _grey(f"{{{{ state_attr('{source}', 'suggestion') or '' }}}}")
                    + "\n\n"
                    + alt_heat_schedule_template(source)
                ),
                Device.ALTERNATIVE_HEAT,
            )
            if source
            else None
        )
        settings = self.devices.variants((Device.IMMERSION_THERMOSTAT,), self._water_settings)
        switch = Device.IMMERSION_SWITCH
        # Settings is for administrators only, so this heading opens nothing.
        in_force = subheading_card("Settings in force", "mdi:tune")
        # The heading shows while a card under it does, so it is never left on its own.
        heading = with_visibility(
            heading_card("Plan", "mdi:clock-check-outline"),
            [
                {
                    "condition": "or",
                    "conditions": [*schedule, *self.devices.visible_with(Device.ALTERNATIVE_HEAT)],
                }
            ],
        )
        return grid_section(
            heading_block(heading, [plan, cheapest]),
            heading_block(in_force, [self.devices.show_with(card, switch) for card in settings]),
            **self._when(Device.IMMERSION_SWITCH),
        )

    def _water_settings(self, shown: frozenset[Device]) -> dict | None:
        """The heater's settings in force. Scheduled heating and the temperatures need the
        thermostat (the switch and the sensor together)."""
        both = Device.IMMERSION_THERMOSTAT in shown
        return glance_card(
            [
                entity_row(self.immersion("auto_immersion"), "Spare solar"),
                entity_row(self.thermostat("immersion_schedule"), "Scheduled") if both else None,
                entity_row(self.thermostat("immersion_target_temp"), "Heat to") if both else None,
                entity_row(self.thermostat("immersion_min_temp"), "Never below") if both else None,
            ]
        )

    def _week_pair(self, energy: dict | None, cost: str | None) -> dict | None:
        """The last 7 days of energy and of cost, side by side on a laptop.

        The energy row carries its name and the device's colour, so the bars match the device.
        """
        name = energy["name"] if energy else ""
        charts = [
            self.chart_title(day_bars([energy], _WEEK, _SMALL_CHART_ROWS, name)),
            self.chart_title(
                day_bars([self.row(cost, "Cost", COST_HEX)], _WEEK, _SMALL_CHART_ROWS, "Cost")
            ),
        ]
        for chart in present(charts):
            chart["grid_options"] = {"columns": 12, "rows": _SMALL_CHART_ROWS}
        return group(heading_card(f"Last {_WEEK} days", "mdi:calendar-week"), charts, **WIDE)

    def immersion_sections(self) -> list:
        """Sub-view: the water now, the plan, and the last week of heating and its cost."""
        week = self._week_pair(
            self.row(self.immersion("immersion_today"), "Heated", WATER_HEX),
            self.immersion("immersion_cost_today"),
        )
        return [
            self._water_now(),
            self._water_plan(),
            with_visibility(week, self.devices.visible_with(Device.IMMERSION_SWITCH)),
        ]

    # -- EV charger --

    def _charger_now(self) -> dict | None:
        """The charger in a sentence, this charge and today in figures, the last day's power."""
        story = ev_story_template(
            ChargerNow(
                self.ev_power(),
                self.ev("ev_charger_state"),
                self.ev("ev_charging_source"),
                self.ev("ev_solar_surplus_available"),
                self.ev("ev_protection_reason"),
            )
        )
        session_cost = self.ev("ev_session_cost")
        figures = glance_card(
            [
                entity_row(self.ev("ev_session_energy"), "This charge"),
                entity_row(session_cost, "Its cost") if session_cost else None,
                entity_row(self.ev("zappi_today"), "Today"),
                entity_row(self.ev("zappi_cost_today"), "Cost today"),
            ]
        )
        power = history_graph([entity_row(self.ev_power(), "Charge power")], 24, 4)
        return grid_section(
            heading_block(
                heading_card("EV charger", "mdi:ev-station"), [markdown_card(story), figures]
            ),
            heading_block(
                subheading_card("Charge power, last 24 hours", "mdi:chart-line"), [power]
            ),
            **self._when(Device.EV_CHARGER),
            **WIDE,
        )

    def _recent_charges(self) -> dict | None:
        return group(
            heading_card("Recent charges", "mdi:receipt-text-outline"),
            [self.table(self.attribute_card(self.ev("ev_session_cost"), "recent_table"))],
            **self._when(Device.EV_CHARGER),
        )

    def ev_sections(self) -> list:
        """Sub-view: the charger now, the last week of charging and its cost, recent charges."""
        week = self._week_pair(
            self.row(self.ev("zappi_today"), "Charged", BATTERY_HEX), self.ev("zappi_cost_today")
        )
        return [
            self._charger_now(),
            with_visibility(week, self.devices.visible_with(Device.EV_CHARGER)),
            self._recent_charges(),
        ]

    # -- Settings --

    def _when(self, *devices: Device) -> dict[str, list[dict]]:
        """The section option that shows a section while these devices are present."""
        return {"visibility": self.devices.visible_with(*devices)}

    def _when_any(self, *devices: Device) -> dict[str, list[dict]]:
        """The section option that shows a section while any of these devices is present."""
        return {"visibility": self.devices.visible_with_any(*devices)}

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

    def _charge_controls(self) -> dict | None:
        return group(
            heading_card("Tonight's charge", "mdi:battery-clock"),
            [
                switch_tile(
                    self.entity("charge_target_override_enabled"), FIXED_TARGET_NAME, BATTERY
                ),
                switch_tile(self.entity("skip_charge_override"), "Skip tonight", BATTERY),
                stepper_row(self.entity("charge_target_override"), CHARGE_TO_NAME, BATTERY),
                _help(_CHARGE_HELP),
            ],
        )

    def _planning_controls(self) -> dict | None:
        replan = tile_card(
            self.entity("charge_replan"), "Re-plan overnight", columns=FULL, color=BATTERY
        )
        if replan:
            replan["tap_action"] = replan["icon_tap_action"] = {"action": "toggle"}
        return group(
            heading_card("Charge planning", "mdi:chart-timeline-variant"),
            [
                stepper_row(self.entity("cheap_rate_floor_soc"), "Cheap rate floor", BATTERY),
                stepper_row(
                    self.entity("skip_charge_soc_threshold_pct"), "Skip charge above", BATTERY
                ),
                stepper_row(self.entity("forecast_conservatism"), "Forecast caution", SOLAR),
                replan,
                _help(_PLANNING_HELP),
            ],
        )

    def _water_controls(self) -> dict | None:
        show = self.devices.show_with
        thermostat = Device.IMMERSION_THERMOSTAT
        return group(
            heading_card("Hot water", "mdi:water-boiler"),
            [
                switch_tile(self.immersion("auto_immersion"), AUTO_DIVERT_NAME, IMMERSION),
                switch_tile(self.immersion("immersion_managed"), MANAGED_NAME, IMMERSION),
                show(
                    switch_tile(self.thermostat("immersion_schedule"), SCHEDULE_NAME, IMMERSION),
                    thermostat,
                ),
                show(
                    stepper_row(self.thermostat("immersion_target_temp"), "Heat to", IMMERSION),
                    thermostat,
                ),
                show(
                    stepper_row(self.thermostat("immersion_min_temp"), "Never below", IMMERSION),
                    thermostat,
                ),
                show(
                    stepper_row(self.thermostat("immersion_hysteresis"), "Restart drop", IMMERSION),
                    thermostat,
                ),
                stepper_row(self.immersion("surplus_divert_soc_pct"), "Min battery", IMMERSION),
                stepper_row(
                    self.immersion("surplus_divert_min_power_w"), "Min spare solar", IMMERSION
                ),
                *self.devices.variants((thermostat,), self._water_help),
            ],
            **self._when(Device.IMMERSION_SWITCH),
        )

    @staticmethod
    def _water_help(shown: frozenset[Device]) -> dict:
        """What the heater's settings do. The restart drop only with the thermostat."""
        restart = (_RESTART_DROP_HELP,) if Device.IMMERSION_THERMOSTAT in shown else ()
        return _help((_HEAT_NOW_HELP, *restart, _DIVERT_HELP))

    def _system_controls(self) -> dict | None:
        return group(
            heading_card("System", "mdi:cog-outline"),
            [
                switch_tile(self.entity("dry_run"), "Dry run", GRID),
                switch_tile(self.entity("verbose_logging"), "Verbose logging", GRID),
                _help(_SYSTEM_HELP),
            ],
        )

    def _recent_changes(self) -> dict | None:
        """What changed a setting in the last day.

        The list names the heater's settings only while the heater is there, so it is built
        once for each combination of the switch and the thermostat.
        """
        cards = self.devices.variants(
            (Device.IMMERSION_SWITCH, Device.IMMERSION_THERMOSTAT), self._recent_changes_card
        )
        return group(heading_card("Recent changes", "mdi:history"), cards)

    def settings_sections(self) -> list[Any]:
        """Sub-view, for administrators only: every switch and number that changes behaviour.

        Empty without an administrator ID, so the view is left out and no one sees it.
        """
        if not self.admin_ids:
            return []
        return [
            self._charge_controls(),
            self._planning_controls(),
            self._water_controls(),
            self._system_controls(),
            self._recent_changes(),
        ]


@dataclass(frozen=True)
class ViewSpec:
    """A view of the dashboard: its title and icon, and the builder method for its sections.

    A sub-view names the view its back arrow returns to. A tab has no back. An admin_only view
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
    ViewSpec("Home energy", "mdi:home-lightning-bolt", TAB_NOW, Builder.now_sections),
    ViewSpec("Today", "mdi:calendar-today", TAB_TODAY, Builder.today_sections),
    ViewSpec("Tonight", "mdi:battery-clock", TAB_PLAN, Builder.plan_sections),
    ViewSpec("Tomorrow", "mdi:weather-sunset-up", TAB_TOMORROW, Builder.tomorrow_sections),
    ViewSpec("Bill & tariff", "mdi:receipt-text", TAB_BILL, Builder.bill_sections),
)
SUBVIEWS = (
    ViewSpec("Hot water", "mdi:water-boiler", SUB_IMMERSION, Builder.immersion_sections, TAB_NOW),
    ViewSpec("EV charger", "mdi:ev-station", SUB_EV, Builder.ev_sections, TAB_NOW),
    ViewSpec(
        "Settings",
        "mdi:tune",
        SUB_SETTINGS,
        Builder.settings_sections,
        TAB_NOW,
        admin_only=True,
    ),
)
