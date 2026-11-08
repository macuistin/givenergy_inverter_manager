"""The bill so far under each shadow tariff, priced from the stored slots like the real one."""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.core.shadow_pricing import (
    bands_table,
    price_shadows,
    shadow_key,
    shadow_keys,
)
from custom_components.givenergy_inverter_manager.lib.tariff import SlotDay, SlotHistory
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


# A three-band smart meter tariff: Night 23:00 to 08:00, Peak 17:00 to 19:00 and Day for the rest
# (08:00 to 23:00 without the peak). Slot numbers are half hours from midnight.
_NIGHT = [*range(0, 16), *range(46, 48)]
_PEAK = range(34, 38)
_DAY = [*range(16, 34), *range(38, 46)]


def _three_band_history(night: float, day: float, peak: float) -> SlotHistory:
    """Thirty days of 16 September to 15 October, each using the given kWh per band."""
    history = SlotHistory(DUBLIN)
    for offset in range(30):
        slot_day = SlotDay(date(2026, 9, 16) + timedelta(days=offset), DUBLIN)
        for slots, kwh in ((_NIGHT, night), (_DAY, day), (_PEAK, peak)):
            for index in slots:
                slot_day.flows["import"][index] += kwh / len(slots)
                slot_day.seconds[index] = 1800
        history._days[slot_day.day] = slot_day
    return history


def _smart(**changes):  # type: ignore[no-untyped-def]
    fields = {
        "base_rate": 0.35,
        "export_rate": 0.0,
        "rate_periods": [
            {"name": "Smart Night", "rate": 0.20, "start": "23:00", "end": "08:00"},
            {"name": "Smart Peak", "rate": 0.45, "start": "17:00", "end": "19:00"},
        ],
        "standing_charge_per_day": 0.0,
        "pso_levy_per_month": 0.0,
        "vat_rate": 0.0,
        "discount_rate": 0.0,
    }
    return shadow("Smart", **{**fields, **changes})


def _total(history: SlotHistory, entry) -> float:  # type: ignore[no-untyped-def]
    report = price_shadows(history, _cfg(entry), THROUGH, "Europe/Dublin")
    assert report is not None
    return report.bills[0].total


def test_a_three_band_tariff_prices_each_band_at_its_own_rate() -> None:
    # 30 days of 10 kWh at night, 6 in the day and 4 at peak.
    total = _total(_three_band_history(10, 6, 4), _smart())
    assert total == pytest.approx(30 * (10 * 0.20 + 6 * 0.35 + 4 * 0.45))


def test_the_peak_hours_are_not_priced_at_the_day_rate() -> None:
    peak_only = _total(_three_band_history(0, 0, 4), _smart())
    assert peak_only == pytest.approx(30 * 4 * 0.45)


def test_the_edges_of_the_peak_belong_to_the_band_that_starts_there() -> None:
    history = SlotHistory(DUBLIN)
    for offset in range(30):
        slot_day = SlotDay(date(2026, 9, 16) + timedelta(days=offset), DUBLIN)
        for index in (33, 34, 37, 38):  # 16:30, 17:00, 18:30 and 19:00
            slot_day.flows["import"][index] = 1.0
            slot_day.seconds[index] = 1800
        history._days[slot_day.day] = slot_day
    assert _total(history, _smart()) == pytest.approx(30 * (0.35 + 0.45 + 0.45 + 0.35))


def test_night_across_midnight_and_the_morning_edge_use_the_night_rate() -> None:
    history = SlotHistory(DUBLIN)
    for offset in range(30):
        slot_day = SlotDay(date(2026, 9, 16) + timedelta(days=offset), DUBLIN)
        for index in (0, 15, 16, 45, 46, 47):  # 00:00, 07:30, 08:00, 22:30, 23:00, 23:30
            slot_day.flows["import"][index] = 1.0
            slot_day.seconds[index] = 1800
        history._days[slot_day.day] = slot_day
    assert _total(history, _smart()) == pytest.approx(30 * (0.20 * 4 + 0.35 * 2))


def test_vat_is_added_on_top_of_all_three_bands() -> None:
    total = _total(_three_band_history(10, 6, 4), _smart(vat_rate=9.0))
    assert total == pytest.approx(30 * (2.0 + 2.1 + 1.8) * 1.09)


def test_a_day_period_that_covers_the_peak_leaves_the_peak_at_the_day_rate() -> None:
    # Timed rates that overlap are won by the cheapest, as for the active tariff. Setting the day
    # rate as a timed period from 08:00 to 23:00 therefore swallows a dearer peak inside it. The
    # day rate belongs in the base rate instead, as the tests above do.
    trap = _smart(
        base_rate=0.99,
        rate_periods=[
            {"name": "Smart Night", "rate": 0.20, "start": "23:00", "end": "08:00"},
            {"name": "Smart Day", "rate": 0.35, "start": "08:00", "end": "23:00"},
            {"name": "Smart Peak", "rate": 0.45, "start": "17:00", "end": "19:00"},
        ],
    )
    assert _total(_three_band_history(0, 0, 4), trap) == pytest.approx(30 * 4 * 0.35)


def test_each_bill_lists_its_import_and_cost_by_band_and_the_days_with_data() -> None:
    history = _three_band_history(10, 6, 4)
    report = price_shadows(history, _cfg(_smart()), THROUGH, "Europe/Dublin")
    assert report is not None
    bill = report.bills[0]
    assert bill.days_recorded == 30
    costs = {band.band: (band.kwh, band.cost) for band in bill.bands}
    assert costs == {
        "Smart Night": pytest.approx((300.0, 60.0)),
        "Day": pytest.approx((180.0, 63.0)),  # a shadow keeps the active base rate name
        "Smart Peak": pytest.approx((120.0, 54.0)),
    }


def test_the_band_table_totals_the_energy_and_ends_in_a_total_row() -> None:
    report = price_shadows(_three_band_history(10, 6, 4), _cfg(_smart()), THROUGH, "Europe/Dublin")
    assert report is not None
    lines = bands_table(report.bills[0], "€").splitlines()
    assert lines[0] == "| Band | kWh | Energy cost |"
    assert "| Smart Peak | 120.0 | €54.00 |" in lines
    assert lines[-1] == "| **Total** | **600.0** | **€177.00** |"


def test_days_without_history_are_not_counted_as_days_with_data() -> None:
    history = _three_band_history(10, 6, 4)
    for day in list(history._days)[:20]:
        del history._days[day]
    report = price_shadows(history, _cfg(_smart()), THROUGH, "Europe/Dublin")
    assert report is not None
    assert report.bills[0].days_recorded == 10
    assert report.days == 30
