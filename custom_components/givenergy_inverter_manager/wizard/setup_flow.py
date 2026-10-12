"""
setup_flow.py - the setup wizard: a short path from the inverter to a working install.

  system             what was found, the battery and inverter fields GivTCP did not report, and a
                     checklist of what to set up now. The only screen that is always shown.
  inverter_entities  the five inverter entities, when discovery found no complete inverter
  tariff             base and export rate, how many time-of-day rates, bill details
  tariff_rates       exactly that many rows (only when the count is above zero)
  forecast           only offered when no Solcast or Forecast.Solar sensor was found
  hot_water          the immersion devices, ready-by times and alternative heating
  confirm            what was found and entered. The one write.

Only the ticked pages are shown, always in this order. The EV charger and a found forecast
sensor are used without a page. Nothing is stored until the confirm step creates the entry, and
the new install starts in dry run.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_BASE_RATE_NAME,
    CONF_BATTERY_CAPACITY,
    CONF_CURRENCY,
    CONF_DRY_RUN,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_D2,
    CONF_INVERTER_MAX_OUTPUT,
    CONF_RATE_PERIODS,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_INVERTER_MAX_OUTPUT,
)
from ..core.system_text import describe
from ..core.wizard_changes import setup_summary
from ..core.wizard_model import SETUP_PAGES, Detected, Mode, PageContext, Validation
from ..core.wizard_pages import WIRING_REQUIRED, missing_wiring
from ..core.wizard_tariff import (
    clean_bill,
    clean_tariff,
    count_from_input,
    rate_note,
    rate_prefill,
    rows_from_sections,
    validate_bill,
    validate_rates,
    validate_tariff,
)
from ..inverter.givtcp import read_rate_defaults
from .detect import best_inverter, detect, selection_of
from .flow_base import PageView, WizardPages, ordered, states_by_id
from .schemas import (
    SETUP_BILL_DEFAULTS,
    rates_schema,
    tariff_schema,
)
from .selectors import (
    PAGES_KEY,
    checklist_selector,
    currency_code,
    entity_selector,
    number_selector,
)
from .wiring import MANUAL_SERIAL, wiring_from, with_serial

CHOSEN_INVERTER = "discovered_inverter"


class SetupSteps(WizardPages):
    """The steps of the setup wizard. Mixed in before ConfigFlow."""

    hass: Any

    def _init_setup(self) -> None:
        self._init_wizard()
        self._wiring: dict[str, str] = {}
        self._queue: list[str] = []
        self._ticked: list[str] = []
        self._rate_count = 0
        self._partial: Any = None
        self._manual_entities = False

    # ── Context and counting ──────────────────────────────────────────────────

    def _detected_now(self) -> Detected:
        if self._detected is None:
            self._detected = detect(states_by_id(self.hass))
        return self._detected

    def _ctx(self) -> PageContext:
        states = states_by_id(self.hass)
        return PageContext(
            Mode.SETUP,
            dt_util.now().date(),
            detected=self._detected_now(),
            pending=self._values,
            states=states,
            home_currency=currency_code(self.hass.config.currency),
            rate_defaults=read_rate_defaults(
                self.unique_id,  # type: ignore[attr-defined]
                states.get,
                self._chosen_prefix(),
            ),
        )

    def _chosen_prefix(self) -> str | None:
        """The entity prefix of the inverter being set up, None before one is chosen."""
        serial = str(self.unique_id or "").lower()  # type: ignore[attr-defined]
        for inverter in self._detected_now().inverters:
            if inverter.serial.lower() == serial:
                return inverter.prefix
        return None

    def _total_steps(self) -> int:
        """The first screen, the entity screen if needed, the ticked pages, rates and confirm."""
        pages = self._ticked if self._ticked else ["tariff"]
        rates = 1 if "tariff" in pages and self._rate_count > 0 else 0
        manual = 1 if self._manual_entities else 0
        return 1 + manual + len(pages) + rates + 1

    def _offered_pages(self) -> list[str]:
        """The pages the checklist offers. A forecast sensor that was found is used instead."""
        found = self._detected_now().forecast is not None
        return [page for page in SETUP_PAGES if not (page == "forecast" and found)]

    # ── Routing ───────────────────────────────────────────────────────────────

    async def _next(self) -> Any:
        """Go to the next ticked page, or to the confirm step when none is left."""
        self._step_no += 1
        if self._queue:
            return await getattr(self, f"async_step_{self._queue.pop(0)}")()
        return await self.async_step_confirm()

    async def _after_page(self, step_id: str, flat: dict[str, Any]) -> Any:
        if step_id == "tariff" and self._rate_count > 0:
            self._step_no += 1
            return await self.async_step_tariff_rates()
        return await self._next()

    # ── system ────────────────────────────────────────────────────────────────

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        """Home Assistant starts the flow here. The first screen is the system step."""
        return await self.async_step_system(user_input)

    def _found_text(self) -> str:
        detected = self._detected_now()
        lines = describe(selection_of(detected))
        charger = detected.ev_chargers[0].display_name if detected.ev_chargers else None
        lines.append(
            f"EV charger: {charger}, found and used."
            if charger
            else "EV charger: none found. One is picked up by itself when it appears."
        )
        found = detected.forecast
        lines.append(
            f"Solar forecast: {found.provider} ({found.tomorrow}), found and used."
            if found
            else "Solar forecast: none found."
        )
        return "\n".join(f"- {line}" for line in lines)

    def _inverter_options(self) -> list[selector.SelectOptionDict]:
        return [
            selector.SelectOptionDict(
                value=inverter.serial,
                label=inverter.display_name
                + ("" if inverter.is_fully_configured else " (some sensors missing)"),
            )
            for inverter in self._detected_now().inverters
        ]

    def _system_schema(self) -> vol.Schema:
        detected = self._detected_now()
        best = best_inverter(detected)
        fields: dict[Any, Any] = {}
        if selection_of(detected).ask:
            fields[vol.Optional(CHOSEN_INVERTER, default=best.serial)] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=self._inverter_options())
            )
        if best is None or best.battery_capacity_kwh is None:
            fields[vol.Required(CONF_BATTERY_CAPACITY, default=DEFAULT_BATTERY_CAPACITY)] = (
                number_selector(CONF_BATTERY_CAPACITY)
            )
        fields[vol.Optional(CONF_INVERTER_MAX_OUTPUT, default=DEFAULT_INVERTER_MAX_OUTPUT)] = (
            number_selector(CONF_INVERTER_MAX_OUTPUT)
        )
        fields[vol.Required(PAGES_KEY, default=["tariff"])] = checklist_selector(
            self._offered_pages(), translation_key="setup_pages"
        )
        return vol.Schema(fields)

    def _show_system(self, user_input: dict[str, Any] | None = None) -> Any:
        schema = self._system_schema()
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)  # type: ignore[attr-defined]
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="system",
            data_schema=schema,
            last_step=False,
            description_placeholders={"found": self._found_text(), "progress": self._progress()},
        )

    def _chosen_inverter(self, user_input: dict[str, Any]) -> Any:
        """The inverter the user picked, else the best one found, None when none was found."""
        serial = user_input.get(CHOSEN_INVERTER)
        for inverter in self._detected_now().inverters:
            if inverter.serial == serial:
                return inverter
        return best_inverter(self._detected_now())

    def _store_system(self, user_input: dict[str, Any], chosen: Any) -> None:
        """Keep what the first screen gave: battery, inverter output, the home currency."""
        reported = chosen.battery_capacity_kwh if chosen else None
        capacity = user_input.get(CONF_BATTERY_CAPACITY, reported or DEFAULT_BATTERY_CAPACITY)
        output = user_input.get(CONF_INVERTER_MAX_OUTPUT, DEFAULT_INVERTER_MAX_OUTPUT)
        self._values.update(
            {
                CONF_BATTERY_CAPACITY: float(capacity),
                CONF_INVERTER_MAX_OUTPUT: float(output),
                CONF_CURRENCY: currency_code(self.hass.config.currency),
                CONF_RATE_PERIODS: [],
            }
        )
        found = self._detected_now().forecast
        if found:
            self._values[CONF_FORECAST_ENTITY] = found.tomorrow
            if found.day_after:
                self._values[CONF_FORECAST_ENTITY_D2] = found.day_after
        self._ticked = ordered(user_input.get(PAGES_KEY) or [], tuple(self._offered_pages()))
        self._queue = list(self._ticked)
        self._rate_count = 0

    async def async_step_system(self, user_input: dict[str, Any] | None = None) -> Any:
        """Step 1: what was found, the missing numbers and the checklist."""
        if user_input is None:
            return self._show_system()
        chosen = self._chosen_inverter(user_input)
        self._store_system(user_input, chosen)
        if chosen is not None and chosen.is_fully_configured:
            await self._set_unique_id(chosen.serial)
            self._wiring = wiring_from(chosen)
            return await self._next()
        self._partial = chosen
        self._manual_entities = True
        self._step_no += 1
        return await self.async_step_inverter_entities()

    async def _set_unique_id(self, serial: str) -> None:
        await self.async_set_unique_id(serial)  # type: ignore[attr-defined]
        self._abort_if_unique_id_configured()  # type: ignore[attr-defined]

    # ── inverter_entities ─────────────────────────────────────────────────────

    def _entities_schema(self) -> vol.Schema:
        found = wiring_from(self._partial) if self._partial else {}
        fields: dict[Any, Any] = {}
        for key in WIRING_REQUIRED:
            marker = (
                vol.Required(key, description={"suggested_value": found[key]})
                if key in found
                else vol.Required(key)
            )
            fields[marker] = entity_selector()
        return vol.Schema(fields)

    async def async_step_inverter_entities(self, user_input: dict[str, Any] | None = None) -> Any:
        """The five inverter entities, picked by hand."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = missing_wiring(user_input)
            if not errors:
                serial = self._partial.serial if self._partial else MANUAL_SERIAL
                found = wiring_from(self._partial) if self._partial else {}
                self._wiring = {**found, **user_input}
                await self._set_unique_id(serial)
                return await self._next()
        schema = self._entities_schema()
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)  # type: ignore[attr-defined]
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="inverter_entities",
            data_schema=schema,
            errors=errors,
            last_step=False,
            description_placeholders={"progress": self._progress()},
        )

    # ── tariff ────────────────────────────────────────────────────────────────

    def _tariff_view(self) -> PageView:
        ctx = self._ctx()
        offered = rate_prefill(ctx.rate_defaults)
        return PageView(
            "tariff",
            tariff_schema(ctx),
            self._validate_tariff,
            self._store_tariff,
            {"rate_note": rate_note(offered.day_rate, offered.export_rate)},
            last_step=False,
        )

    @staticmethod
    def _validate_tariff(flat: dict[str, Any]) -> Validation:
        return _first_errors(validate_tariff(flat), validate_bill(_bill_values(flat), []))

    def _store_tariff(self, flat: dict[str, Any]) -> dict[str, Any]:
        self._rate_count = count_from_input(flat)
        return {**clean_tariff(flat), **clean_bill(_bill_values(flat)), CONF_RATE_PERIODS: []}

    async def async_step_tariff(self, user_input: dict[str, Any] | None = None) -> Any:
        """The rates, how many time-of-day rates there are, and the bill details."""
        return await self._page(user_input, self._tariff_view())

    # ── tariff_rates ──────────────────────────────────────────────────────────

    def _rates_view(self) -> PageView:
        ctx = self._ctx()
        count = self._rate_count
        country = self.hass.config.country
        base = str(self._values.get(CONF_BASE_RATE_NAME, SETUP_BILL_DEFAULTS[CONF_BASE_RATE_NAME]))

        def rows(flat: dict[str, Any]) -> list[dict[str, Any]]:
            return rows_from_sections(flat, count)

        return PageView(
            "tariff_rates",
            rates_schema(ctx, count, country),
            lambda flat: validate_rates(rows(flat), base),
            lambda flat: {CONF_RATE_PERIODS: rows(flat)},
            {"rate_note": rate_note(rate_prefill(ctx.rate_defaults).night_rate)},
            last_step=False,
        )

    async def async_step_tariff_rates(self, user_input: dict[str, Any] | None = None) -> Any:
        """Exactly as many rows as the count on the tariff screen."""
        return await self._page(user_input, self._rates_view())

    # ── forecast and hot water ────────────────────────────────────────────────

    async def async_step_forecast(self, user_input: dict[str, Any] | None = None) -> Any:
        """The forecast sensors. Offered only when none was found."""
        return await self._page(user_input, self._forecast_view())

    async def async_step_hot_water(self, user_input: dict[str, Any] | None = None) -> Any:
        """The immersion devices, ready-by times and alternative heating."""
        return await self._page(user_input, self._hot_water_view())

    # ── confirm ───────────────────────────────────────────────────────────────

    def _entry_data(self) -> dict[str, Any]:
        """The data of the entry: the wiring, what was entered, and dry run on."""
        entered = {k: v for k, v in self._values.items() if v is not None and v != ""}
        serial = self.unique_id or MANUAL_SERIAL  # type: ignore[attr-defined]
        return {**with_serial(self._wiring, str(serial)), **entered, CONF_DRY_RUN: True}

    def _summary_text(self) -> str:
        detected = self._detected_now()
        charger = detected.ev_chargers[0].display_name if detected.ev_chargers else None
        values = with_serial({**self._wiring, **self._values}, str(self.unique_id or MANUAL_SERIAL))  # type: ignore[attr-defined]
        return setup_summary(values, charger, tariff_asked="tariff" in self._ticked)

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> Any:
        """What was found and entered. Submitting creates the entry, in dry run."""
        if user_input is not None:
            return self.async_create_entry(  # type: ignore[attr-defined]
                title="GivEnergy Inverter Manager", data=self._entry_data()
            )
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="confirm",
            data_schema=vol.Schema({}),
            last_step=True,
            description_placeholders={
                "summary": self._summary_text(),
                "warnings": _warnings_block(self._warning_lines()),
                "progress": self._progress(),
            },
        )


def _bill_values(flat: dict[str, Any]) -> dict[str, Any]:
    """The bill details a tariff submission carried, over the new-install defaults."""
    return {**SETUP_BILL_DEFAULTS, **{k: v for k, v in flat.items() if k in _BILL_FIELDS}}


_BILL_FIELDS = frozenset({*SETUP_BILL_DEFAULTS, CONF_CURRENCY})


def _first_errors(*results: Validation) -> Validation:
    for result in results:
        if result.errors:
            return result
    return Validation()


def _warnings_block(warnings: list[str]) -> str:
    return "\n".join(f"- {warning}" for warning in warnings) if warnings else ""
