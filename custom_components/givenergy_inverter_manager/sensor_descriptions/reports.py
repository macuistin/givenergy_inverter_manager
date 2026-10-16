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
        value_fn=build_charge_plan_state,
        html_fn=build_charge_plan_html,
    ),
    GivEnergyManagerSensorDescription(
        key="tariff_in_use",
        translation_key="tariff_in_use",
        icon="mdi:table",
        value_fn=lambda data: data.tariff_report_state,
        html_fn=lambda data: data.tariff_report_html,
    ),
    GivEnergyManagerSensorDescription(
        key="bill_audit",
        translation_key="bill_audit",
        icon="mdi:receipt-text-outline",
        value_fn=lambda data: data.bill_audit_state,
        html_fn=lambda data: data.bill_audit_html,
        attrs_fn=lambda data: {
            "bill_table": data.bill_audit_bill_table,
            "days_table": data.bill_audit_days_table,
        },
    ),
    GivEnergyManagerSensorDescription(
        key="previous_bill_audit",
        translation_key="previous_bill_audit",
        icon="mdi:receipt-text-clock-outline",
        value_fn=lambda data: data.previous_bill_audit_state,
        html_fn=lambda data: data.previous_bill_audit_html,
        attrs_fn=lambda data: {
            "summary_table": data.previous_bill_audit_summary_table,
            "period": data.previous_bill_audit_period,
        },
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
