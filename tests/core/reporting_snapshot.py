"""Render every report for one engine case, for the reporting characterisation test."""

from __future__ import annotations

import hashlib
import json

from custom_components.givenergy_inverter_manager.core import reporting
from tests.core import engine_snapshot as snap
from tests.core.flat_engine import build_coordinator_data

_REPORTS = (
    "build_today_summary_html",
    "build_today_summary_state",
    "build_charge_plan_html",
    "build_charge_plan_state",
    "build_week_summary_html",
    "build_week_summary_state",
)


def render_all(case: dict) -> dict[str, str]:
    """Run the engine for a golden engine case and render every report, with and without a plan."""
    data, _ = build_coordinator_data(**{k: snap.decode(v) for k, v in case["in"].items()})
    out = {name: getattr(reporting, name)(data) for name in _REPORTS}
    data.charge_decision = None
    out["plan_html_without_decision"] = reporting.build_charge_plan_html(data)
    out["plan_state_without_decision"] = reporting.build_charge_plan_state(data)
    return out


def digest(rendered: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(rendered, sort_keys=True).encode()).hexdigest()


def render_handmade(spec: dict) -> dict[str, str]:
    """Render every report for a CoordinatorData built from a plain dict of field values.

    spec holds "data" (CoordinatorData fields), "today"/"week"/"yesterday" (accumulator
    fields) and "decision" (ChargeDecision fields, or None).
    """
    from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
    from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision
    from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

    data = CoordinatorData()
    for name, value in spec["data"].items():
        setattr(data, name, value)
    for period in ("today", "week", "yesterday"):
        setattr(data, period, EnergyAccumulator(**spec[period]))
    data.charge_decision = ChargeDecision(**spec["decision"]) if spec["decision"] else None
    return {name: getattr(reporting, name)(data) for name in _REPORTS}
