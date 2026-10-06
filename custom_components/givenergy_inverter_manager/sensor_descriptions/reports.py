"""HTML report sensors."""

from __future__ import annotations

from ..core.reporting import (
    build_charge_plan_html,
    build_charge_plan_state,
    build_today_summary_html,
    build_today_summary_state,
    build_week_summary_html,
    build_week_summary_state,
)
from .base import GivEnergyManagerSensorDescription

DESCRIPTIONS: tuple[GivEnergyManagerSensorDescription, ...] = (
    # ── HTML report sensors (disabled by default) ─────────────────────────────
    GivEnergyManagerSensorDescription(
        key="today_summary",
        translation_key="today_summary",
        icon="mdi:newspaper-variant-outline",
        entity_registry_enabled_default=False,
        value_fn=build_today_summary_state,
        html_fn=build_today_summary_html,
    ),
    GivEnergyManagerSensorDescription(
        key="charge_plan",
        translation_key="charge_plan",
        icon="mdi:battery-clock-outline",
        entity_registry_enabled_default=False,
        value_fn=build_charge_plan_state,
        html_fn=build_charge_plan_html,
    ),
    GivEnergyManagerSensorDescription(
        key="week_summary",
        translation_key="week_summary",
        icon="mdi:calendar-week-outline",
        entity_registry_enabled_default=False,
        value_fn=build_week_summary_state,
        html_fn=build_week_summary_html,
    ),
)
