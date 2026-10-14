"""Unit tests for core/window_guard.py: put a charge window that ran into the day rate back."""

from __future__ import annotations

from datetime import date, datetime, time

from custom_components.givenergy_inverter_manager.const import REPLAN_MAX_WRITES
from custom_components.givenergy_inverter_manager.core.charge_window import window_stays_cheap
from custom_components.givenergy_inverter_manager.core.tariff import build_tariff
from custom_components.givenergy_inverter_manager.core.window_guard import (
    GuardInputs,
    decide_repair,
    manager_has_written,
    parse_clock,
    repairs_today,
)

ENTITY = "select.charge_end"
TODAY = date(2026, 10, 13)
TARIFF = build_tariff(
    {
        "base_rate": 0.365,
        "rate_periods": [
            {"name": "Night", "rate": 0.18, "start": "23:00", "end": "08:00"},
            {"name": "Nightboost", "rate": 0.1056, "start": "02:00", "end": "04:00"},
        ],
    }
)
WRITTEN = {"time": "2026-10-13T01:59:00+01:00", "entity_id": ENTITY, "value": "04:00", "reason": "x"}


def _repair_entry(hour: int) -> dict:
    stamp = datetime(2026, 10, 13, hour, 0).isoformat()
    return {"time": stamp, "entity_id": ENTITY, "value": "n", "reason": "window repair"}


def _inputs(start: str | None, end: str | None, **overrides) -> GuardInputs:
    values = {
        "tariff": TARIFF,
        "live_start": parse_clock(start) if start else None,
        "live_end": parse_clock(end) if end else None,
        "planned_start": time(2, 0),
        "planned_end": time(4, 0),
        "override_active": False,
        "log": [WRITTEN],
        "entity_id": ENTITY,
        "today": TODAY,
    }
    return GuardInputs(**{**values, **overrides})


class TestWindowStaysCheap:
    def test_the_cheapest_period_is_cheap(self):
        assert window_stays_cheap(TARIFF, time(2, 0), time(4, 0))

    def test_the_whole_night_band_is_cheap(self):
        assert window_stays_cheap(TARIFF, time(23, 0), time(8, 0))

    def test_a_window_that_wraps_past_midnight_inside_the_night_band_is_cheap(self):
        assert window_stays_cheap(TARIFF, time(23, 30), time(6, 0))

    def test_the_window_set_by_hand_on_13_october_ran_into_the_day_rate(self):
        assert not window_stays_cheap(TARIFF, time(2, 0), time(0, 10))

    def test_one_minute_past_the_end_of_the_night_band_is_not_cheap(self):
        assert not window_stays_cheap(TARIFF, time(2, 0), time(8, 1))

    def test_an_unused_window_counts_as_cheap(self):
        assert window_stays_cheap(TARIFF, time(0, 0), time(0, 0))

    def test_a_flat_tariff_has_no_cheap_hours_to_protect(self):
        flat = build_tariff({"base_rate": 0.3, "rate_periods": []})
        assert window_stays_cheap(flat, time(9, 0), time(17, 0))


class TestDecideRepair:
    def test_a_window_into_the_day_rate_is_set_back_to_the_plan(self):
        repair = decide_repair(_inputs("02:00", "00:10"))

        assert repair is not None
        assert (repair.start, repair.end) == (time(2, 0), time(4, 0))
        assert repair.note == (
            "the window was 02:00 to 00:10, past the cheap rate, set back to 02:00 to 04:00"
        )

    def test_a_window_inside_the_cheap_hours_is_left_alone(self):
        assert decide_repair(_inputs("02:00", "04:00")) is None

    def test_an_unreadable_window_is_left_alone(self):
        assert decide_repair(_inputs(None, None)) is None

    def test_a_manual_charge_or_skip_override_is_left_alone(self):
        assert decide_repair(_inputs("02:00", "00:10", override_active=True)) is None

    def test_a_schedule_the_manager_never_wrote_over_is_left_alone(self):
        assert decide_repair(_inputs("02:00", "00:10", log=[])) is None

    def test_outside_changes_and_notes_do_not_count_as_a_manager_write(self):
        outside = {**WRITTEN, "reason": "external"}
        note = {**WRITTEN, "reason": "retry"}
        assert decide_repair(_inputs("02:00", "00:10", log=[outside, note])) is None

    def test_it_stops_after_the_daily_limit(self):
        log = [WRITTEN] + [_repair_entry(h) for h in range(REPLAN_MAX_WRITES)]

        assert decide_repair(_inputs("02:00", "00:10", log=log)) is None

    def test_one_repair_short_of_the_limit_still_acts(self):
        log = [WRITTEN] + [_repair_entry(h) for h in range(REPLAN_MAX_WRITES - 1)]

        assert decide_repair(_inputs("02:00", "00:10", log=log)) is not None

    def test_repairs_on_an_earlier_day_do_not_count(self):
        old = {**_repair_entry(1), "time": datetime(2026, 10, 12, 1, 0).isoformat()}
        assert repairs_today([old] * 5, ENTITY, TODAY) == 0


class TestHelpers:
    def test_parse_clock_reads_both_clock_formats_and_rejects_the_rest(self):
        assert parse_clock("04:00") == time(4, 0)
        assert parse_clock("04:00:00") == time(4, 0)
        assert parse_clock("unavailable") is None

    def test_manager_has_written_needs_a_real_write(self):
        assert manager_has_written([WRITTEN])
        assert not manager_has_written([{**WRITTEN, "reason": "window repair"}])
