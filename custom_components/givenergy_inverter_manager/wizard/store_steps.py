"""
store_steps.py - the "choose a tariff from the list" screens, shared by the setup wizard.

  tariff_source   a menu: choose from the list, or enter it myself
  store_country   the countries the store holds, Home Assistant's own country first
  store_provider  the suppliers in that country
  store_plan      the plans of that supplier with a price in force today
  store_area      only when the plan has more than one area (for example a region)
  store_review    the rates in the words of a bill, and the bill start day

Setup can never be blocked by the store. Any failure to read it, or a tariff the saved rates
cannot price to the cent, ends in the menu with only "enter it myself", and the hand-entry page
(`tariff`) is unchanged. Nothing is stored until the review screen is submitted, and then only
in the handler's values, like every other page.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.util import dt as dt_util

from ..const import CONF_BILL_START_DAY
from ..core.wizard_store import (
    StoreChoice,
    choose_tariff,
    country_choices,
    default_country,
    review_text,
    source_options,
    source_record,
)
from ..lib.tariff import TariffDefinition
from ..lib.tariffstore import StoreError
from ..tariff_store import TariffStoreAccess
from .selectors import number_selector, store_choice_selector

_LOG = logging.getLogger(__name__)

# What reading or parsing a store file can raise. A timeout is an OSError.
STORE_ERRORS = (StoreError, OSError, ValueError, KeyError, TypeError)
FROM_LIST = "store_country"


class StoreSteps:
    """The store screens. Mixed in before the setup wizard's other pages."""

    hass: Any
    _values: dict[str, Any]

    def _init_store(self) -> None:
        self._picked: dict[str, str] = {}
        self._access: TariffStoreAccess | None = None
        self._definition: TariffDefinition | None = None
        self._choice = StoreChoice()

    def _store(self) -> TariffStoreAccess:
        if self._access is None:
            self._access = TariffStoreAccess(self.hass)
        return self._access

    # What the two wizards do differently. Each flow supplies its own.
    def _hand_entry(self) -> str:
        """The step that leaves the list: typing the rates in (setup) or the tariff menu."""
        raise NotImplementedError  # pragma: no cover

    def _source_text(self) -> str:
        """Where the tariff in force came from, for the menu. Setup has none yet."""
        return ""

    def _bill_day_default(self) -> int:
        raise NotImplementedError  # pragma: no cover

    async def _store_finished(self, options: dict[str, Any]) -> Any:
        """Keep the chosen tariff's options and go on to the next screen."""
        raise NotImplementedError  # pragma: no cover

    def _menu(self, note: str, options: list[str]) -> Any:
        return self.async_show_menu(  # type: ignore[attr-defined]
            step_id="tariff_source",
            menu_options=options,
            description_placeholders={
                "progress": self._progress(),  # type: ignore[attr-defined]
                "note": note,
                **({"source": self._source_text()} if self._source_text() else {}),
            },
        )

    def _store_failed(self, err: Exception) -> Any:
        """One line, and the way that cannot fail."""
        _LOG.warning("The tariff store could not be read: %s", err)
        return self._menu(
            "The list of tariffs could not be read, so enter the rates yourself. "
            "You can choose from the list later in Configure.",
            [self._hand_entry()],
        )

    def _pick_form(
        self, step_id: str, field: str, options: dict[str, str], default: str | None
    ) -> Any:
        key = vol.Required(field, default=default) if default else vol.Required(field)
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id=step_id,
            data_schema=vol.Schema({key: store_choice_selector(options)}),
            description_placeholders={"progress": self._progress(), **self._picked},  # type: ignore[attr-defined]
        )

    # ── country, supplier, plan ───────────────────────────────────────────────

    async def async_step_store_country(self, user_input: dict[str, Any] | None = None) -> Any:
        """The countries the store holds. Opening the list reads the store's index again, so a
        plan added since the last look is offered. Anything unchanged comes from the cache."""
        try:
            if user_input is None:
                await self._store().async_refresh()
            countries = country_choices(await self._store().async_countries())
        except STORE_ERRORS as err:
            return self._store_failed(err)
        if user_input is not None:
            self._picked = {"country": user_input["country"]}
            return await self.async_step_store_provider()
        if not countries:
            return self._store_failed(StoreError("no country is listed"))
        home = default_country(countries, getattr(self.hass.config, "country", None))
        return self._pick_form("store_country", "country", countries, home)

    async def async_step_store_provider(self, user_input: dict[str, Any] | None = None) -> Any:
        """The suppliers of the chosen country."""
        country = self._picked["country"]
        try:
            providers = await self._store().async_providers(country)
        except STORE_ERRORS as err:
            return self._store_failed(err)
        if user_input is not None:
            self._picked["provider"] = user_input["provider"]
            return await self.async_step_store_plan()
        return self._pick_form("store_provider", "provider", providers, None)

    async def async_step_store_plan(self, user_input: dict[str, Any] | None = None) -> Any:
        """The plans of the chosen supplier that have prices in force today."""
        today = dt_util.now().date()
        try:
            plans = await self._store().async_tariffs(
                self._picked["country"], self._picked["provider"], today
            )
        except STORE_ERRORS as err:
            return self._store_failed(err)
        if not plans:
            return self._menu(
                "That supplier has no plan with prices in force today. Choose another, or "
                "enter the rates yourself.",
                [FROM_LIST, self._hand_entry()],
            )
        if user_input is not None:
            self._picked["tariff"] = user_input["tariff"]
            return await self.async_step_store_area()
        return self._pick_form("store_plan", "tariff", plans, None)

    # ── area and review ───────────────────────────────────────────────────────

    async def async_step_store_area(self, user_input: dict[str, Any] | None = None) -> Any:
        """Only asked when the plan has more than one area. Never guessed from the location."""
        today = dt_util.now().date()
        try:
            areas = await self._store().async_areas(
                self._picked["country"], self._picked["provider"], self._picked["tariff"], today
            )
        except STORE_ERRORS as err:
            return self._store_failed(err)
        if user_input is not None:
            self._picked["area"] = user_input["area"]
            return await self.async_step_store_review()
        if len(areas) == 1:
            self._picked["area"] = next(iter(areas))
            return await self.async_step_store_review()
        return self._pick_form("store_area", "area", areas, None)

    async def _load_choice(self) -> None:
        picked = self._picked
        self._definition = await self._store().async_definition(
            picked["country"],
            picked["provider"],
            picked["tariff"],
            dt_util.now().date(),
            area=picked["area"],
        )
        self._choice = choose_tariff(self._definition, self._bill_day_default())

    async def async_step_store_review(self, user_input: dict[str, Any] | None = None) -> Any:
        """The rates as a bill reads them. Submitting copies them into the tariff options."""
        try:
            if user_input is None:
                await self._load_choice()
        except STORE_ERRORS as err:
            return self._store_failed(err)
        definition = self._definition
        assert definition is not None  # noqa: S101 - set by _load_choice before a form is shown
        if user_input is not None:
            return await self._store_chosen(definition, int(user_input[CONF_BILL_START_DAY]))
        text = review_text(definition, self._choice)
        if not self._choice.usable:
            return self._menu(text, [FROM_LIST, self._hand_entry()])
        default = self._bill_day_default()
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="store_review",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BILL_START_DAY, default=default): number_selector(
                        CONF_BILL_START_DAY
                    )
                }
            ),
            description_placeholders={
                "progress": self._progress(),  # type: ignore[attr-defined]
                "name": definition.name,
                "review": text,
            },
        )

    async def _store_chosen(self, definition: TariffDefinition, bill_start_day: int) -> Any:
        record = source_record(self._picked, definition)
        options = source_options(record, self._choice)
        options[CONF_BILL_START_DAY] = bill_start_day
        return await self._store_finished(options)
