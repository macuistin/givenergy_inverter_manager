"""
options_flow.py - the options wizard: "What would you like to change?"

  init           a checklist of pages, each with a one-line status of what is set now
  tariff         base rate, export rate, how many time-of-day rates, and tick boxes for what
                 to edit next, then in this order: tariff_rates, bill, schedule_change
  battery, forecast, hot_water, ev   one form each
  confirm        every changed value before and after, and whether it applies now or reloads

Only the ticked pages are shown, in a fixed order. The pages collect values on the handler and
write nothing. The one write happens at the end, as a read-modify-write of the options as they
are at that moment (never a copy taken when the wizard opened), so a control moved while the
wizard was open keeps its new value. A page that was not ticked is never rewritten, and a value
equal to what is already in force is not written at all.

The confirm step is skipped when exactly one page was ticked and its change applies without a
reload.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from ..config_helpers import effective_config, merge_config
from ..const import (
    CONF_BASE_RATE_NAME,
    CONF_RATE_PERIODS,
    CONF_TARIFF_REVIEWED_ON,
    DEFAULT_BASE_RATE_NAME,
)
from ..core.reload_policy import Effect, change_effect
from ..core.tariff import options_after_tariff_save, tariff_in_force
from ..core.wizard_changes import confirm_text
from ..core.wizard_model import (
    OPTION_PAGES,
    PAGE_KEYS,
    PAGE_STEPS,
    Detected,
    Mode,
    PageContext,
    Validation,
    changed_values,
)
from ..core.wizard_pages import (
    battery_summary,
    clean_battery,
    clean_ev,
    ev_summary,
    forecast_summary,
    hot_water_summary,
    validate_battery,
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
from .flow_base import PageView, WizardPages, ordered, states_by_id
from .schemas import (
    CANCEL_SCHEDULED,
    CHANGE_DATE,
    CONFIRM_CURRENT,
    EDIT_BILL,
    EDIT_RATES,
    SCHEDULE_CHANGE,
    battery_schema,
    bill_schema,
    ev_schema,
    rates_schema,
    schedule_schema,
    tariff_schema,
)
from .selectors import PAGES_KEY, checklist_selector, currency_code

PAGE_TITLES: dict[str, str] = {
    "tariff": "Tariff",
    "battery": "Battery and charging",
    "forecast": "Solar forecast",
    "hot_water": "Hot water",
    "ev": "EV charger",
}
_TARIFF_KEYS = frozenset(
    key for step in PAGE_STEPS["tariff"] for key in PAGE_KEYS[step]
)


class OptionsSteps(WizardPages):
    """The steps of the options wizard. Mixed in before OptionsFlow."""

    hass: Any
    config_entry: Any

    def _init_options(self) -> None:
        self._init_wizard()
        self._ticked: list[str] = []
        self._queue: list[str] = []
        self._substeps: list[str] = []
        self._rate_count = 0
        self._edit_date: date | None = None
        self._cancel_scheduled = False
        self._confirm_current = False
        self._tariff_touched = False
        self._extra_steps = 0

    # ── Context ───────────────────────────────────────────────────────────────

    def _today(self) -> date:
        return dt_util.now().date()

    def _ctx(self) -> PageContext:
        if self._detected is None:
            self._detected = detect(states_by_id(self.hass))
        current = tariff_in_force(effective_config(self.config_entry), self._today())
        return PageContext(
            Mode.OPTIONS,
            self._today(),
            detected=self._detected,
            current=current,
            pending=self._values,
            states=states_by_id(self.hass),
            home_currency=currency_code(self.hass.config.currency),
        )

    def _detected_now(self) -> Detected:
        return self._ctx().detected

    def _total_steps(self) -> int:
        """The checklist, every step of the ticked pages, and the confirm step when it is shown."""
        pages = self._ticked or ["tariff"]
        return 1 + len(pages) + self._extra_steps + (0 if len(pages) == 1 else 1)

    def _is_last_form(self) -> bool:
        """True when this form is the last one and the confirm step may be skipped."""
        return len(self._ticked) == 1 and not self._queue and not self._substeps

    # ── init: the checklist ───────────────────────────────────────────────────

    def _page_summaries(self) -> dict[str, str]:
        current = self._ctx().current
        return {
            "tariff": tariff_page_summary(current),
            "battery": battery_summary(current),
            "forecast": forecast_summary(current),
            "hot_water": hot_water_summary(current),
            "ev": ev_summary(current),
        }

    def _checklist_options(self) -> list[selector.SelectOptionDict]:
        summaries = self._page_summaries()
        return [
            selector.SelectOptionDict(value=page, label=f"{PAGE_TITLES[page]}: {summaries[page]}")
            for page in OPTION_PAGES
        ]

    def _show_init(self, errors: dict[str, str] | None = None) -> Any:
        schema = vol.Schema(
            {vol.Required(PAGES_KEY, default=[]): checklist_selector(self._checklist_options())}
        )
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="init",
            data_schema=schema,
            errors=errors or {},
            last_step=False,
            description_placeholders={"progress": self._progress()},
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        """Step 1: what would you like to change? Nothing is ticked to begin with."""
        if user_input is None:
            return self._show_init()
        self._ticked = ordered(user_input.get(PAGES_KEY) or [], OPTION_PAGES)
        if not self._ticked:
            return self._show_init({"base": "nothing_ticked"})
        self._queue = list(self._ticked)
        return await self._next_page()

    # ── Routing ───────────────────────────────────────────────────────────────

    async def _next_page(self) -> Any:
        """Go to the next ticked page, or finish when none is left."""
        self._step_no += 1
        if self._queue:
            page = self._queue.pop(0)
            return await getattr(self, f"async_step_{page}")()
        return await self._finish()

    async def _next_substep(self) -> Any:
        """Go to the next tariff screen the ticks asked for, else the next page."""
        if self._substeps:
            self._step_no += 1
            return await getattr(self, f"async_step_{self._substeps.pop(0)}")()
        return await self._next_page()

    async def _after_page(self, step_id: str, flat: dict[str, Any]) -> Any:
        if step_id == "tariff":
            self._plan_tariff_steps(flat)
            return await self._next_substep()
        if step_id in PAGE_STEPS["tariff"]:
            return await self._next_substep()
        return await self._next_page()

    # ── tariff and its screens ────────────────────────────────────────────────

    def _plan_tariff_steps(self, flat: dict[str, Any]) -> None:
        """Decide which of the rates, bill and schedule screens follow the tariff screen."""
        saved = rate_count(self._ctx().current.get(CONF_RATE_PERIODS))
        self._rate_count = count_from_input(flat)
        self._tariff_touched = True
        self._confirm_current = bool(flat.get(CONFIRM_CURRENT))
        editing_rows = bool(flat.get(EDIT_RATES)) or self._rate_count != saved
        self._substeps = []
        if self._rate_count == 0 and saved > 0:
            self._values[CONF_RATE_PERIODS] = []
        if self._rate_count > 0 and editing_rows:
            self._substeps.append("tariff_rates")
        if flat.get(EDIT_BILL):
            self._substeps.append("bill")
        if flat.get(SCHEDULE_CHANGE):
            self._substeps.append("schedule_change")
        self._extra_steps = len(self._substeps)

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
        return rows_from_sections(flat, self._rate_count)

    def _base_name(self) -> str:
        ctx = self._ctx()
        return str(ctx.value(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME))

    async def async_step_tariff_rates(self, user_input: dict[str, Any] | None = None) -> Any:
        """Exactly as many rows as the count says. Raising it adds blank rows."""
        ctx = self._ctx()
        view = PageView(
            "tariff_rates",
            rates_schema(ctx, self._rate_count, self.hass.config.country),
            lambda flat: validate_rates(self._rows(flat), self._base_name()),
            lambda flat: {CONF_RATE_PERIODS: self._rows(flat)},
            last_step=self._is_last_form(),
        )
        return await self._page(user_input, view)

    async def async_step_bill(self, user_input: dict[str, Any] | None = None) -> Any:
        """Currency, base rate name, bill start day, standing charge, levy, VAT, discount."""
        ctx = self._ctx()
        periods = ctx.value(CONF_RATE_PERIODS, [])
        view = PageView(
            "bill",
            bill_schema(ctx),
            lambda flat: validate_bill(flat, periods),
            clean_bill,
            last_step=self._is_last_form(),
        )
        return await self._page(user_input, view)

    async def async_step_schedule_change(self, user_input: dict[str, Any] | None = None) -> Any:
        """The date the rates just entered start, and a way to cancel the scheduled ones."""
        ctx = self._ctx()

        def check(flat: dict[str, Any]) -> Any:
            return validate_change_date(_date_of(flat), ctx.today)

        def keep(flat: dict[str, Any]) -> dict[str, Any]:
            self._edit_date = _date_of(flat)
            self._cancel_scheduled = bool(flat.get(CANCEL_SCHEDULED))
            return {}

        view = PageView(
            "schedule_change", schedule_schema(ctx), check, keep, last_step=self._is_last_form()
        )
        return await self._page(user_input, view)

    # ── the other pages ───────────────────────────────────────────────────────

    async def async_step_battery(self, user_input: dict[str, Any] | None = None) -> Any:
        """Capacity, inverter output, minimum charge, overnight cap, cost, throughput budget."""
        ctx = self._ctx()
        view = PageView(
            "battery",
            battery_schema(ctx),
            lambda flat: validate_battery(flat, ctx),
            clean_battery,
            last_step=self._is_last_form(),
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
            last_step=self._is_last_form(),
        )
        return await self._page(user_input, view)

    # ── apply ─────────────────────────────────────────────────────────────────

    def _tariff_part(self) -> dict[str, Any]:
        return {k: v for k, v in self._values.items() if k in _TARIFF_KEYS}

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
        options.update(changed_values(other, effective))
        return options

    def _before_and_after(self) -> tuple[dict[str, Any], dict[str, Any]]:
        entry = self.config_entry
        return effective_config(entry), merge_config(entry.data, self._new_options())

    async def _finish(self) -> Any:
        """Write now when one page was ticked and nothing reloads, else ask first."""
        before, after = self._before_and_after()
        if len(self._ticked) == 1 and change_effect(before, after) is not Effect.RELOAD:
            return self.async_create_entry(title="", data=self._new_options())  # type: ignore[attr-defined]
        return await self.async_step_confirm()

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
                "progress": self._progress(),
            },
        )


def _date_of(flat: dict[str, Any]) -> date | None:
    """The date a rate change was asked to start, None for none or a value that is not one."""
    try:
        return date.fromisoformat(str(flat[CHANGE_DATE]))
    except (KeyError, ValueError):
        return None

