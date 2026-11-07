"""
tariff_config.py - the tariff built from the saved options.

Kept apart from tariff.py because it needs only the option keys and the defaults, none of which
import anything. A shadow tariff is built the same way, and the code that does so may not reach
the inverter through any chain of imports (tests/test_shadow_cannot_write.py).
"""

from __future__ import annotations

import logging
from datetime import time
from typing import Any

from ..conf import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_BILL_START_DAY,
    CONF_DISCOUNT_RATE,
    CONF_EXPORT_RATE,
    CONF_PSO_LEVY,
    CONF_RATE_PERIODS,
    CONF_STANDING_CHARGE,
    CONF_VAT_RATE,
)
from ..defaults import (
    DEFAULT_BASE_RATE,
    DEFAULT_BASE_RATE_NAME,
    DEFAULT_BILL_START_DAY,
    DEFAULT_DISCOUNT_RATE,
    DEFAULT_EXPORT_RATE,
    DEFAULT_PSO_LEVY,
    DEFAULT_RATE_PERIODS,
    DEFAULT_STANDING_CHARGE,
    DEFAULT_VAT_RATE,
)
from ..lib.tariff import RatePeriod, TariffConfig

_LOG = logging.getLogger(__name__)


def build_tariff(cfg: dict[str, Any]) -> TariffConfig:
    """Build a TariffConfig from a merged config dict."""
    periods: list[RatePeriod] = []
    for p in cfg.get(CONF_RATE_PERIODS, DEFAULT_RATE_PERIODS):
        try:
            s = p["start"].split(":")
            e = p["end"].split(":")
            period = RatePeriod(
                name=p["name"],
                rate=float(p["rate"]),
                start=time(int(s[0]), int(s[1])),
                end=time(int(e[0]), int(e[1])),
            )
        except (KeyError, ValueError, IndexError) as err:
            _LOG.warning("Skipping malformed rate period %s: %s", p, err)
            continue
        if period.start == period.end:
            _LOG.warning(
                "Skipping rate period %s: start and end are both %s, so it never applies",
                p.get("name"),
                period.start.strftime("%H:%M"),
            )
            continue
        periods.append(period)

    return TariffConfig(
        rate_periods=periods,
        base_rate=float(cfg.get(CONF_BASE_RATE, DEFAULT_BASE_RATE)),
        base_rate_name=str(cfg.get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)),
        export_rate=float(cfg.get(CONF_EXPORT_RATE, DEFAULT_EXPORT_RATE)),
        standing_charge=float(cfg.get(CONF_STANDING_CHARGE, DEFAULT_STANDING_CHARGE)),
        pso_levy=float(cfg.get(CONF_PSO_LEVY, DEFAULT_PSO_LEVY)),
        vat_rate=float(cfg.get(CONF_VAT_RATE, DEFAULT_VAT_RATE)),
        discount_rate=float(cfg.get(CONF_DISCOUNT_RATE, DEFAULT_DISCOUNT_RATE)),
        bill_start_day=int(cfg.get(CONF_BILL_START_DAY, DEFAULT_BILL_START_DAY)),
    )
