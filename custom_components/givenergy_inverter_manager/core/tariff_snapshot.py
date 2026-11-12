"""
tariff_snapshot.py: the part of the saved options that prices a bill, as plain data.

A stored bill row holds this snapshot when the tariff changes (lib/tariff/bill_days.py). It
names the integration's own option keys, so it stays here. Pure Python, no Home Assistant
imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_BILL_START_DAY,
    CONF_CURRENCY,
    CONF_DISCOUNT_RATE,
    CONF_EXPORT_RATE,
    CONF_PSO_LEVY,
    CONF_RATE_PERIODS,
    CONF_STANDING_CHARGE,
    CONF_VAT_INCLUDED,
    CONF_VAT_RATE,
)

TARIFF_KEYS = (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_RATE_PERIODS,
    CONF_EXPORT_RATE,
    CONF_STANDING_CHARGE,
    CONF_PSO_LEVY,
    CONF_VAT_INCLUDED,
    CONF_VAT_RATE,
    CONF_DISCOUNT_RATE,
    CONF_BILL_START_DAY,
    CONF_CURRENCY,
)


def tariff_snapshot(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """The part of the options that prices a bill, as plain data that a row can store."""
    return {key: _plain(cfg[key]) for key in TARIFF_KEYS if key in cfg}


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value
