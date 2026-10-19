"""A frozen GivTCP feed is told from a quiet one by when entities were last reported."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.givenergy_inverter_manager.const import GIVTCP_FROZEN_AFTER_S
from custom_components.givenergy_inverter_manager.lib.guards.freshness import (
    frozen_age_s,
    newest_report,
)

NOW = datetime(2031, 3, 4, 2, 0, tzinfo=timezone.utc)


def _ago(seconds: float) -> datetime:
    return NOW - timedelta(seconds=seconds)


class TestNewestReport:
    def test_the_latest_report_wins(self):
        assert newest_report([_ago(900), _ago(40), _ago(300)]) == _ago(40)

    def test_entities_with_no_report_are_left_out(self):
        assert newest_report([None, _ago(40), None]) == _ago(40)

    def test_nothing_reported_gives_none(self):
        assert newest_report([]) is None
        assert newest_report([None]) is None


class TestFrozenAge:
    def test_a_feed_reporting_every_cycle_is_not_frozen(self):
        assert frozen_age_s(_ago(30), NOW) is None

    def test_a_brief_hiccup_is_not_frozen(self):
        assert frozen_age_s(_ago(180), NOW) is None

    def test_exactly_the_limit_is_not_yet_frozen(self):
        assert frozen_age_s(_ago(GIVTCP_FROZEN_AFTER_S), NOW) is None

    def test_just_past_the_limit_is_frozen_and_gives_the_age(self):
        assert frozen_age_s(_ago(GIVTCP_FROZEN_AFTER_S + 30), NOW) == pytest.approx(630)

    def test_an_overnight_outage_is_frozen(self):
        assert frozen_age_s(_ago(9 * 3600), NOW) == pytest.approx(9 * 3600)

    def test_no_report_at_all_is_not_frozen(self):
        # Entities that are missing are the silent check's case.
        assert frozen_age_s(None, NOW) is None

    def test_a_report_dated_after_now_is_not_frozen(self):
        assert frozen_age_s(NOW + timedelta(seconds=5), NOW) is None


def test_the_limit_is_ten_minutes_so_an_add_on_restart_passes():
    assert GIVTCP_FROZEN_AFTER_S == 600
