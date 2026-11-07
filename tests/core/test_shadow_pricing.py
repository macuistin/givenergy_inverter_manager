"""The bill so far under each shadow tariff, priced from the stored slots like the real one."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.core.shadow_pricing import (
    price_shadows,
    shadow_key,
    shadow_keys,
)
from custom_components.givenergy_inverter_manager.lib.tariff import SlotHistory
from tests.core.test_shadow_tariffs import ACTIVE, shadow
from tests.lib.tariff.test_reprice import _october_bill_days

DUBLIN = ZoneInfo("Europe/Dublin")
THROUGH = date(2026, 10, 15)


def _history() -> SlotHistory:
    history = SlotHistory(DUBLIN)
    history._days = {day.day: day for day in _october_bill_days()}
    return history


def _cfg(*shadows):  # type: ignore[no-untyped-def]
    return {**ACTIVE, "shadow_tariffs": list(shadows)}


def test_no_shadow_tariff_gives_no_report() -> None:
    assert price_shadows(_history(), _cfg(), THROUGH, "Europe/Dublin") is None


def test_a_copy_of_the_active_tariff_costs_the_same() -> None:
    report = price_shadows(_history(), _cfg(shadow("Same")), THROUGH, "Europe/Dublin")
    assert report is not None
    assert report.bills[0].difference == 0
    assert report.bills[0].total == report.active_total


def test_a_dearer_tariff_is_positive_and_a_cheaper_one_negative() -> None:
    report = price_shadows(
        _history(),
        _cfg(shadow("Dear", base_rate=0.9, rate_periods=[]), shadow("Cheap", vat_rate=0.0)),
        THROUGH,
        "Europe/Dublin",
    )
    assert report is not None
    dear, cheap = report.bills
    assert dear.difference > 0
    assert cheap.difference < 0
    assert dear.difference == pytest.approx(dear.total - report.active_total, abs=0.01)


def test_every_tariff_is_priced_over_the_active_bill_period() -> None:
    report = price_shadows(_history(), _cfg(shadow("A")), THROUGH, "Europe/Dublin")
    assert report is not None
    assert (report.first_day, report.through) == (date(2026, 9, 16), THROUGH)
    assert (report.days, report.period_days) == (30, 30)
    assert report.bills[0].data_from == date(2026, 9, 16)
    assert report.bills[0].coverage == 1.0


def test_a_start_day_a_monthly_period_cannot_name_gives_no_report() -> None:
    cfg = {**_cfg(shadow("A")), "bill_start_day": 30}
    assert price_shadows(_history(), cfg, THROUGH, "Europe/Dublin") is None


def test_the_keys_are_words_that_stay_apart() -> None:
    assert shadow_keys([shadow("Night saver"), shadow("night-saver"), shadow("!!")]) == [
        "night_saver",
        "night_saver_2",
        "tariff",
    ]
    taken: set[str] = set()
    assert shadow_key("Flat", taken) == "flat"
    assert shadow_key("flat", taken) == "flat_2"
