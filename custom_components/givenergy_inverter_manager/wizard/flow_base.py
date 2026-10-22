"""
flow_base.py - what the setup wizard and the options wizard share.

Both wizards are a list of pages. The user ticks the pages to go through, each page is one form,
and nothing is stored until the confirm step. This mixin holds the pieces that do not depend on
which wizard it is:

  PageView / _page   show a form, check a submission, ask again once for a warning, and keep
                     the cleaned values on the handler (plain values, no Home Assistant object)
  forecast and hot water views, which are the same page in both wizards
  progress text      "Step 2 of about 4."

The flows decide where to go next (_after_page) and what the confirm step writes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol

from ..const import (
    CONF_CARBON_INTENSITY_ENTITY,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_D2,
    CONF_FORECAST_ENTITY_P10,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TEMP_SENSOR,
)
from ..core.wizard_model import Detected, PageContext, Validation
from ..core.wizard_pages import (
    clean_forecast,
    clean_hot_water,
    flatten_sections,
    sensor_check,
    validate_forecast,
    validate_hot_water,
)
from .schemas import forecast_schema, hot_water_schema


@dataclass(frozen=True)
class PageView:
    """One form: its schema, how to check a submission and what to store from it."""

    step_id: str
    schema: vol.Schema
    validate: Callable[[dict[str, Any]], Validation]
    store: Callable[[dict[str, Any]], dict[str, Any]]
    placeholders: dict[str, str] = field(default_factory=dict)
    last_step: bool = False


def ordered(ticked: list[str], order: tuple[str, ...]) -> list[str]:
    """The ticked pages in the fixed order, whatever order the client sent them in."""
    chosen = set(ticked or [])
    return [page for page in order if page in chosen]


def bullet_lines(lines: list[str]) -> str:
    """Non-empty lines as a Markdown list."""
    return "\n".join(f"- {line}" for line in lines if line)


class WizardPages:
    """The page machinery of both wizards. Mixed in before the Home Assistant flow class."""

    _values: dict[str, Any]
    _warned: dict[str, tuple[str, ...]]
    _step_no: int
    _detected: Detected | None

    def _init_wizard(self) -> None:
        self._values = {}
        self._warned = {}
        self._step_no = 1
        self._detected = None

    # What the wizards fill in. Each flow supplies its own.
    def _ctx(self) -> PageContext:
        raise NotImplementedError  # pragma: no cover

    def _total_steps(self) -> int:
        raise NotImplementedError  # pragma: no cover

    async def _after_page(self, step_id: str, flat: dict[str, Any]) -> Any:
        raise NotImplementedError  # pragma: no cover

    def _is_last_form(self) -> bool:
        """True when this form is the last one. Only the options wizard can skip its confirm."""
        return False

    def _progress(self) -> str:
        return f"Step {self._step_no} of about {max(self._total_steps(), self._step_no)}."

    def _placeholders(self, view: PageView, warnings: tuple[str, ...]) -> dict[str, str]:
        note = "\n\n".join(f"Check: {warning}" for warning in warnings)
        return {
            "progress": self._progress(),
            "warnings": f"{note}\n\n" if note else "",
            **view.placeholders,
        }

    def _show_page(
        self,
        view: PageView,
        user_input: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
        warnings: tuple[str, ...] = (),
    ) -> Any:
        """Show the form. After an error or a warning it suggests what was submitted."""
        schema = view.schema
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)  # type: ignore[attr-defined]
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id=view.step_id,
            data_schema=schema,
            errors=errors or {},
            description_placeholders=self._placeholders(view, warnings),
            last_step=view.last_step,
        )

    async def _page(self, user_input: dict[str, Any] | None, view: PageView) -> Any:
        """Show a page, or check what it was submitted with and move on.

        An error shows the form again. A warning shows it once more with the note, and the
        next submission with the same warnings goes through, so a warning never blocks saving.
        """
        if user_input is None:
            return self._show_page(view)
        flat = flatten_sections(user_input)
        result = view.validate(flat)
        if result.errors:
            return self._show_page(view, user_input, errors=result.errors)
        if result.warnings and self._warned.get(view.step_id) != result.warnings:
            self._warned[view.step_id] = result.warnings
            return self._show_page(view, user_input, warnings=result.warnings)
        self._values.update(view.store(flat))
        return await self._after_page(view.step_id, flat)

    def _warning_lines(self) -> list[str]:
        """The warnings still standing after the pages were submitted."""
        return [warning for warnings in self._warned.values() for warning in warnings]

    # ── Pages that are the same in both wizards ───────────────────────────────

    def _sensor_report(self, ctx: PageContext, keys: tuple[str, ...]) -> str:
        """What the sensors in force read now, one line each, or a note when none is set."""
        lines = [sensor_check(ctx.current[key], ctx.states) for key in keys if ctx.current.get(key)]
        return bullet_lines(lines) or "No sensor is set yet."

    def _forecast_view(self) -> PageView:
        ctx = self._ctx()
        found = ctx.detected.forecast
        detected = (
            f"Found {found.provider}: {found.tomorrow}."
            if found
            else "No Solcast or Forecast.Solar sensor was found."
        )
        report = self._sensor_report(
            ctx,
            (
                CONF_FORECAST_ENTITY,
                CONF_FORECAST_ENTITY_P10,
                CONF_FORECAST_ENTITY_D2,
                CONF_CARBON_INTENSITY_ENTITY,
            ),
        )
        return PageView(
            "forecast",
            forecast_schema(ctx),
            lambda flat: validate_forecast(flat, ctx),
            clean_forecast,
            {"detected": detected, "check": report},
            self._is_last_form(),
        )

    def _hot_water_view(self) -> PageView:
        ctx = self._ctx()
        names = ctx.detected.immersion_candidates
        candidates = (
            f"Switches that look like an immersion heater: {', '.join(names)}."
            if names
            else "No switch with immersion in its name was found."
        )
        report = self._sensor_report(ctx, (CONF_IMMERSION_SWITCH, CONF_IMMERSION_TEMP_SENSOR))
        return PageView(
            "hot_water",
            hot_water_schema(ctx),
            lambda flat: validate_hot_water(flat, ctx),
            clean_hot_water,
            {"candidates": candidates, "check": report},
            self._is_last_form(),
        )


def states_by_id(hass: Any) -> Mapping[str, Any]:
    """Every state in the system by entity id, for discovery and the sensor checks."""
    return {state.entity_id: state for state in hass.states.async_all()}
