"""Helpers for the tests that build plans and usage for the cheapest-plan search.

The search itself is the store's `lib/tariffranking`, and its tests are copied to `tests/lib/tariffranking`.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from utility_tariffs_lib.tariff import (
    Locale,
    SlotHistory,
    definition_from_config,
)
from utility_tariffs_lib.tariffranking import (
    Candidate,
    Usage,
    Window,
    ranges,
)

from custom_components.givenergy_inverter_manager.core.tariff_config import build_tariff
from tests.core.test_shadow_tariffs import ACTIVE
from tests.support.bill_shape import october_bill_days

DUBLIN = ZoneInfo("Europe/Dublin")
THROUGH = date(2026, 10, 15)


def _definition(**changes):  # type: ignore[no-untyped-def]
    options = {**ACTIVE, **{k: v for k, v in changes.items() if k != "name"}}
    return definition_from_config(
        build_tariff(options), Locale("EUR", "IE", "Europe/Dublin", date(2000, 1, 1))
    )


def _candidate(key: str, **changes) -> Candidate:  # type: ignore[no-untyped-def]
    return Candidate(key, key.title(), _definition(**changes))


def _usage(window: Window, through: date = THROUGH) -> Usage:
    history = SlotHistory(DUBLIN)
    history._days = {day.day: day for day in october_bill_days()}
    return Usage(history, ranges(window, through, 16))
