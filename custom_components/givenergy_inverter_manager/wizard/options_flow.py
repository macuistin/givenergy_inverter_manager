"""
options_flow.py - Configure: a menu of pages, each opened, changed and returned from.

  init           the menu: Tariff, Battery, Charge planning, Hot water, EV charger, each with a
                 line on what is set now, and Save changes once something has changed
  tariff_menu    Rates, Time-of-day rates, Bill details, Schedule a rate change, The tariff is
                 still current, and Back
  tariff, tariff_rates, bill, schedule_change, battery, charge_planning (then forecast),
  hot_water, ev  one form each, then back to the menu they were opened from
  confirm        every changed value before and after, and whether it applies now or reloads

The pages collect values on the handler and write nothing. The one write happens at confirm,
as a read-modify-write of the options as they are at that moment (never a copy taken when the
flow opened), so a control moved while Configure was open keeps its new value. A page that was
not opened is never rewritten, and a value equal to what is already in force is not written.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol
from homeassistant.util import dt as dt_util

from ..config_helpers import effective_config, merge_config
from ..const import (
    CONF_BASE_RATE_NAME,
    CONF_RATE_PERIODS,
    CONF_TARIFF_REVIEWED_ON,
    DEFAULT_BASE_RATE_NAME,
)
from ..core.reload_policy import Effect, change_effect
from ..core.seasons import season_defaults
from ..core.tariff import options_after_tariff_save, tariff_in_force
from ..core.wizard_changes import confirm_text
from ..core.wizard_model import (
    PAGE_KEYS,
    PAGE_STEPS,
    Mode,
    PageContext,
    Validation,
    changed_values,
)
from ..core.wizard_pages import (
    battery_summary,
    charge_planning_summary,
    clean_battery,
    clean_charge_planning,
    clean_ev,
    ev_summary,
    forecast_summary,
    hot_water_summary,
    validate_battery,
    validate_charge_planning,
)
from ..core.wizard_tariff import (
    clean_bill,
    clean_tariff,
    count_from_input,
    rate_count,
    rows_from_sections,
    scheduled_changes_summary,
    tariff_page_summary,
    tariff_submission,
    tariff_summary,
    validate_bill,
    validate_change_date,
    validate_rates,
    validate_tariff,
)
from .detect import detect
from .flow_base import PageView, WizardPages, states_by_id
from .schemas import (
    CANCEL_SCHEDULED,
    CHANGE_DATE,
    battery_schema,
    bill_schema,
    charge_planning_schema,
    ev_schema,
    rates_schema,
    schedule_schema,
    tariff_schema,
)
from .selectors import currency_code

# The main menu, in order. The tariff opens a menu of its own.
MENU_PAGES: tuple[str, ...] = ("tariff_menu", "battery", "charge_planning", "hot_water", "ev")
_TARIFF_KEYS = frozenset(
    key for step in PAGE_STEPS["tariff"] for key in PAGE_KEYS[step]
)


class OptionsSteps(WizardPages):
    """The steps of the options wizard. Mixed in before OptionsFlow."""

    hass: Any
    config_entry: Any

    def _init_options(self) -> None:
        self._init_wizard()
        self._rate_count: int | None = None
        self._edit_date: date | None = None
        self._cancel_scheduled = False
        self._confirm_current = False
        self._tariff_touched = False

    # ── Context ───────────────────────────────────────────────────────────────

    def _today(self) -> date:
        return dt_util.now().date()

    def _ctx(self) -> PageContext:
        if self._detected is None:
            self._detected = detect(states_by_id(self.hass))
        # The season months a user never set are shown at their latitude defaults, so saving the
        # page unchanged stores nothing for them.
        current = tariff_in_force(
            self._with_season_defaults(effective_config(self.config_entry)), self._today()
        )
        return PageContext(
            Mode.OPTIONS,
            self._today(),
            detected=self._detected,
            current=current,
            pending=self._values,
            states=states_by_id(self.hass),
            home_currency=currency_code(self.hass.config.currency),
            latitude=self.hass.config.latitude,
        )

    def _progress(self) -> str:
        """A menu has no fixed order of steps, so there is no step count to show."""
        return ""

    # ── init: the menu ────────────────────────────────────────────────────────

    def _page_summaries(self) -> dict[str, str]:
        current = self._ctx().current
        return {
            "tariff_summary_line": tariff_page_summary(current),
            "battery_summary": battery_summary(current),
            "charge_planning_summary": (
                f"{charge_planning_summary(current)}, {forecast_summary(current)}"
            ),
            "hot_water_summary": hot_water_summary(current),
            "ev_summary": ev_summary(current),
        }

    def _pending(self) -> tuple[str, Effect | None]:
        """The changes not saved yet, as text, and whether saving them reloads. Empty if none."""
        if self._new_options() == dict(self.config_entry.options):
            return "", None
        before, after = self._before_and_after()
        changes = confirm_text(before, after)
        if self._confirm_current:
            changes = f"{changes}\n\nThe tariff is confirmed as current today."
        return changes, change_effect(before, after)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        """The menu. Each page comes back here, and Save changes shows once one has changed."""
        changes, effect = self._pending()
        options = [*MENU_PAGES]
        if changes:
            options.append("confirm")
        unsaved = (
            f"**Not saved yet**\n\n{changes}\n\n"
            if changes
            else ""
        )
        save_note = (
            "Reloads the integration, so entities are unavailable for a few seconds."
            if effect is Effect.RELOAD
            else "Applies at once."
        )
        return self.async_show_menu(  # type: ignore[attr-defined]
            step_id="init",
            menu_options=options,
            description_placeholders={
                **self._page_summaries(),
                "unsaved": unsaved,
                "save_note": save_note,
            },
        )

    # ── Routing ───────────────────────────────────────────────────────────────

    async def _after_page(self, step_id: str, flat: dict[str, Any]) -> Any:
        if step_id == "tariff":
            return await self._after_tariff(flat)
        if step_id == "charge_planning":
            # The solar forecast is the second screen of charge planning.
            return await self.async_step_forecast()
        if step_id in PAGE_STEPS["tariff"]:
            return await self.async_step_tariff_menu()
        return await self.async_step_init()

    # ── the tariff menu ───────────────────────────────────────────────────────

    def _saved_rate_count(self) -> int:
        return rate_count(self._ctx().current.get(CONF_RATE_PERIODS))

    def _current_rate_count(self) -> int:
        """The count chosen on the Rates screen, else the count of the rates as they stand."""
        if self._rate_count is not None:
            return self._rate_count
        pending = self._values.get(CONF_RATE_PERIODS)
        return len(pending) if pending is not None else self._saved_rate_count()

    async def async_step_tariff_menu(self, user_input: dict[str, Any] | None = None) -> Any:
        """What to change in the tariff. Time-of-day rates shows while there is at least one."""
        options = ["tariff"]
        if self._current_rate_count() > 0:
            options.append("tariff_rates")
        options += ["bill", "schedule_change", "tariff_reviewed", "init"]
        ctx = self._ctx()
        scheduled = scheduled_changes_summary(ctx.current, ctx.today)
        summary = tariff_summary(ctx.current)
        reviewed = (
            "\n\nThe tariff will be confirmed as current today when you save."
            if self._confirm_current
            else ""
        )
        return self.async_show_menu(  # type: ignore[attr-defined]
            step_id="tariff_menu",
            menu_options=options,
            description_placeholders={
                "tariff_summary": f"{summary}\n\n{scheduled}" if scheduled else summary,
                "reviewed": reviewed,
            },
        )

    async def async_step_tariff_reviewed(self, user_input: dict[str, Any] | None = None) -> Any:
        """Record today as the day the tariff was checked, so the yearly reminder resets."""
        self._tariff_touched = True
        self._confirm_current = True
        return await self.async_step_tariff_menu()

    # ── tariff and its screens ────────────────────────────────────────────────

    async def _after_tariff(self, flat: dict[str, Any]) -> Any:
        """After Rates: the rate rows when the count changed to one or more, else the menu."""
        before = self._current_rate_count()
        self._rate_count = count_from_input(flat)
        self._tariff_touched = True
        if self._rate_count == 0 and self._saved_rate_count() > 0:
            self._values[CONF_RATE_PERIODS] = []
        if self._rate_count > 0 and self._rate_count != before:
            return await self.async_step_tariff_rates()
        return await self.async_step_tariff_menu()

    def _tariff_view(self) -> PageView:
        ctx = self._ctx()
        scheduled = scheduled_changes_summary(ctx.current, ctx.today)
        summary = tariff_summary(ctx.current)
        text = f"{summary}\n\n{scheduled}" if scheduled else summary
        return PageView(
            "tariff",
            tariff_schema(ctx),
            validate_tariff,
            clean_tariff,
            {"tariff_summary": text},
            last_step=False,
        )

    async def async_step_tariff(self, user_input: dict[str, Any] | None = None) -> Any:
        """The rates, how many time-of-day rates there are, and what to edit next."""
        return await self._page(user_input, self._tariff_view())

    def _rows(self, flat: dict[str, Any]) -> list[dict[str, Any]]:
        return rows_from_sections(flat, self._current_rate_count())

    def _base_name(self) -> str:
        ctx = self._ctx()
        return str(ctx.value(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME))

    async def async_step_tariff_rates(self, user_input: dict[str, Any] | None = None) -> Any:
        """Exactly as many rows as the count says. Raising it adds blank rows."""
        ctx = self._ctx()
        view = PageView(
            "tariff_rates",
            rates_schema(ctx, self._current_rate_count(), self.hass.config.country),
            lambda flat: validate_rates(self._rows(flat), self._base_name()),
            self._store_rows,
        )
        return await self._page(user_input, view)

    def _store_rows(self, flat: dict[str, Any]) -> dict[str, Any]:
        self._tariff_touched = True
        return {CONF_RATE_PERIODS: self._rows(flat)}

    async def async_step_bill(self, user_input: dict[str, Any] | None = None) -> Any:
        """Currency, base rate name, bill start day, standing charge, levy, VAT, discount."""
        ctx = self._ctx()
        periods = ctx.value(CONF_RATE_PERIODS, [])
        view = PageView(
            "bill",
            bill_schema(ctx),
            lambda flat: validate_bill(flat, periods),
            self._touch_tariff(clean_bill),
        )
        return await self._page(user_input, view)

    async def async_step_schedule_change(self, user_input: dict[str, Any] | None = None) -> Any:
        """The date the rates just entered start, and a way to cancel the scheduled ones."""
        ctx = self._ctx()

        def check(flat: dict[str, Any]) -> Any:
            return validate_change_date(_date_of(flat), ctx.today)

        def keep(flat: dict[str, Any]) -> dict[str, Any]:
            self._tariff_touched = True
            self._edit_date = _date_of(flat)
            self._cancel_scheduled = bool(flat.get(CANCEL_SCHEDULED))
            return {}

        view = PageView("schedule_change", schedule_schema(ctx), check, keep)
        return await self._page(user_input, view)

    # ── the other pages ───────────────────────────────────────────────────────

    def _touch_tariff(self, clean: Any) -> Any:
        """*clean*, and note that the tariff was changed, so the save rebuilds it."""

        def store(flat: dict[str, Any]) -> dict[str, Any]:
            self._tariff_touched = True
            return clean(flat)

        return store

    async def async_step_battery(self, user_input: dict[str, Any] | None = None) -> Any:
        """Capacity, inverter output, cost and throughput budget."""
        ctx = self._ctx()
        view = PageView(
            "battery",
            battery_schema(ctx),
            lambda flat: validate_battery(flat, ctx),
            clean_battery,
        )
        return await self._page(user_input, view)

    async def async_step_charge_planning(self, user_input: dict[str, Any] | None = None) -> Any:
        """Minimum charge, overnight cap, the winter and shoulder months and winter behaviour.

        The solar forecast sensors follow on the next screen: this page and that one together
        are what the overnight plan is worked out from.
        """
        ctx = self._ctx()
        view = PageView(
            "charge_planning",
            charge_planning_schema(ctx),
            lambda flat: validate_charge_planning(flat, ctx),
            clean_charge_planning,
        )
        return await self._page(user_input, view)

    async def async_step_forecast(self, user_input: dict[str, Any] | None = None) -> Any:
        """The forecast sensors, with what was found and a read-only test of the sensors."""
        return await self._page(user_input, self._forecast_view())

    async def async_step_hot_water(self, user_input: dict[str, Any] | None = None) -> Any:
        """The immersion devices, ready-by times and alternative heating."""
        return await self._page(user_input, self._hot_water_view())

    async def async_step_ev(self, user_input: dict[str, Any] | None = None) -> Any:
        """The car efficiency. The charger is found by itself."""
        ctx = self._ctx()
        chargers = ctx.detected.ev_chargers
        charger = (
            f"Found and used: {', '.join(c.display_name for c in chargers)}."
            if chargers
            else "No EV charger was found. One is picked up by itself when it appears."
        )
        view = PageView(
            "ev",
            ev_schema(ctx),
            lambda _flat: Validation(),
            clean_ev,
            {"charger": charger},
        )
        return await self._page(user_input, view)

    # ── apply ─────────────────────────────────────────────────────────────────

    def _tariff_part(self) -> dict[str, Any]:
        return {k: v for k, v in self._values.items() if k in _TARIFF_KEYS}

    def _with_season_defaults(self, config: dict[str, Any]) -> dict[str, Any]:
        """The config with the season months the user never set at their latitude defaults."""
        return {**season_defaults(self.hass.config.latitude), **config}

    def _new_options(self) -> dict[str, Any]:
        """The options after the wizard, built from the options as they are now."""
        entry = self.config_entry
        today = self._today()
        options = dict(entry.options)
        effective = effective_config(entry)
        in_force = tariff_in_force(effective, today)
        if self._tariff_touched:
            dated = (self._edit_date, self._cancel_scheduled)
            sub = tariff_submission(self._tariff_part(), effective, in_force, dated)
            if sub.updates or sub.effective is not None or sub.cancel_scheduled:
                options = options_after_tariff_save(options, in_force, sub, today)
            if self._confirm_current:
                options[CONF_TARIFF_REVIEWED_ON] = today.isoformat()
        other = {k: v for k, v in self._values.items() if k not in _TARIFF_KEYS}
        options.update(changed_values(other, self._with_season_defaults(effective)))
        return options

    def _before_and_after(self) -> tuple[dict[str, Any], dict[str, Any]]:
        entry = self.config_entry
        return (
            self._with_season_defaults(effective_config(entry)),
            self._with_season_defaults(merge_config(entry.data, self._new_options())),
        )

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> Any:
        """Every change before and after, and whether it applies now or reloads."""
        if user_input is not None:
            return self.async_create_entry(title="", data=self._new_options())  # type: ignore[attr-defined]
        before, after = self._before_and_after()
        notes = self._warning_lines()
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="confirm",
            data_schema=vol.Schema({}),
            last_step=True,
            description_placeholders={
                "changes": confirm_text(before, after),
                "warnings": ("\n".join(f"- {n}" for n in notes) + "\n\n") if notes else "",
            },
        )


def _date_of(flat: dict[str, Any]) -> date | None:
    """The date a rate change was asked to start, None for none or a value that is not one."""
    try:
        return date.fromisoformat(str(flat[CHANGE_DATE]))
    except (KeyError, ValueError):
        return None

