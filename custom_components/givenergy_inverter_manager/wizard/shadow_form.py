"""
shadow_form.py - the shadow tariff form of Configure: what it starts at, its checks and what it
stores. Plain values only. It never touches the inverter.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..const import (
    CONF_BASE_RATE,
    CONF_DISCOUNT_RATE,
    CONF_EXPORT_RATE,
    CONF_PSO_LEVY,
    CONF_RATE_PERIODS,
    CONF_STANDING_CHARGE,
    CONF_VAT_RATE,
)
from ..core.shadow_tariffs import KEY_NAME, SHADOW_FIELDS, name_error
from ..core.wizard_model import KEY_DEFAULTS, Validation
from ..core.wizard_tariff import count_from_input, rate_period_errors

FORM_NAME = "shadow_name"  # the name field, apart from the "name" of a rate row


def starting_entry(active: Mapping[str, Any]) -> dict[str, Any]:
    """The values a new shadow tariff starts from: the active tariff's own, to edit."""
    return {key: active.get(key, KEY_DEFAULTS.get(key)) for key in SHADOW_FIELDS}


def validate_form(raw: Any, flat: Mapping[str, Any]) -> Validation:
    """Errors for the first shadow tariff form: a free name, and a rate that covers the day."""
    error = name_error(raw, str(flat.get(FORM_NAME) or ""))
    if error:
        return Validation(errors={"base": error})
    if float(flat.get(CONF_BASE_RATE) or 0) <= 0 and count_from_input(flat) == 0:
        return Validation(errors={"base": "base_rate_required"})
    return Validation()


def validate_rows(rows: list[dict[str, Any]], active: Mapping[str, Any]) -> Validation:
    """Errors for the timed rate rows, checked against the active tariff's base rate name."""
    base_name = str(active.get("base_rate_name") or KEY_DEFAULTS["base_rate_name"])
    return Validation(errors=rate_period_errors(rows, base_name))


def entry_from_form(flat: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The shadow tariff a submitted form describes. *rows* are the timed rates, may be empty."""
    return {
        KEY_NAME: str(flat[FORM_NAME]).strip(),
        CONF_BASE_RATE: float(flat[CONF_BASE_RATE]),
        CONF_EXPORT_RATE: float(flat[CONF_EXPORT_RATE]),
        CONF_RATE_PERIODS: rows,
        CONF_STANDING_CHARGE: float(flat[CONF_STANDING_CHARGE]),
        CONF_PSO_LEVY: float(flat[CONF_PSO_LEVY]),
        CONF_VAT_RATE: float(flat[CONF_VAT_RATE]),
        CONF_DISCOUNT_RATE: float(flat[CONF_DISCOUNT_RATE]),
    }
