"""The coordinator follows a dated rate change without a reload, and raises the stale-tariff repair."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import homeassistant.helpers.issue_registry as ir
import pytest

from custom_components.givenergy_inverter_manager import coordinator as coordinator_module
from custom_components.givenergy_inverter_manager.const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_EXPORT_RATE,
    CONF_RATE_PERIODS,
    CONF_TARIFF_CHANGES,
    CONF_TARIFF_REVIEWED_ON,
    TARIFF_REVIEW_STALE_DAYS,
)
from custom_components.givenergy_inverter_manager.repairs import (
    ISSUE_TARIFF_REVIEW_DUE,
    LEARN_MORE_URLS,
)
from tests.test_coordinator import FakeCoordinator, _cfg

DAY = date(2026, 10, 31)
CHANGE_DAY = date(2026, 11, 1)
LATE_NIGHT = [{"name": "Night", "rate": 0.2, "start": "23:30", "end": "07:00"}]


def _change(periods: list[dict]) -> dict:
    return {
        "effective": CHANGE_DAY.isoformat(),
        CONF_BASE_RATE: 0.4,
        CONF_BASE_RATE_NAME: "Standard",
        CONF_EXPORT_RATE: 0.21,
        CONF_RATE_PERIODS: periods,
    }


def _local(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=timezone.utc)


def _set_today(monkeypatch, day: date) -> None:
    monkeypatch.setattr(FakeCoordinator, "_now", staticmethod(lambda: _local(day)))


class TestEffectiveConfig:
    def test_with_no_change_it_is_the_plain_merge(self, monkeypatch):
        _set_today(monkeypatch, CHANGE_DAY)
        coord = FakeCoordinator(cfg=_cfg())
        coord.entry.options = {"battery_min_soc_pct": 12}
        assert coord._effective_cfg() == {**_cfg(), "battery_min_soc_pct": 12}

    def test_the_old_rates_are_in_force_the_day_before(self, monkeypatch):
        _set_today(monkeypatch, DAY)
        coord = FakeCoordinator(cfg=_cfg())
        coord.entry.options = {CONF_TARIFF_CHANGES: [_change(LATE_NIGHT)]}
        assert coord._effective_cfg()[CONF_BASE_RATE] == pytest.approx(0.3334)

    def test_the_new_rates_are_in_force_from_the_date(self, monkeypatch):
        _set_today(monkeypatch, CHANGE_DAY)
        coord = FakeCoordinator(cfg=_cfg())
        coord.entry.options = {CONF_TARIFF_CHANGES: [_change(LATE_NIGHT)]}
        effective = coord._effective_cfg()
        assert effective[CONF_BASE_RATE] == pytest.approx(0.4)
        assert effective[CONF_RATE_PERIODS] == LATE_NIGHT


class _TimeListeners:
    """Records the time listeners the coordinator registers and cancels."""

    def __init__(self) -> None:
        self.registered: list[tuple[int, int]] = []
        self.cancelled: list[tuple[int, int]] = []

    def track(self, hass, action, hour, minute, second):
        trigger = (hour, minute)
        self.registered.append(trigger)
        return lambda: self.cancelled.append(trigger)


@pytest.fixture
def listeners(monkeypatch):
    recorder = _TimeListeners()
    monkeypatch.setattr(coordinator_module, "async_track_time_change", recorder.track)
    return recorder


class TestChargeTargetListener:
    def test_the_trigger_is_one_minute_before_the_cheapest_rate_starts(self, monkeypatch, listeners):
        _set_today(monkeypatch, DAY)
        coord = FakeCoordinator(cfg=_cfg())
        coord._register_charge_target_listener()
        assert listeners.registered == [(1, 59)]

    def test_a_change_that_moves_the_cheap_window_moves_the_trigger_at_midnight(
        self, monkeypatch, listeners
    ):
        _set_today(monkeypatch, DAY)
        coord = FakeCoordinator(cfg=_cfg())
        coord.entry.options = {CONF_TARIFF_CHANGES: [_change(LATE_NIGHT)]}
        coord._register_charge_target_listener()
        _set_today(monkeypatch, CHANGE_DAY)
        coord._register_charge_target_listener()
        assert listeners.registered == [(1, 59), (23, 29)]
        assert listeners.cancelled == [(1, 59)]

    def test_an_unchanged_trigger_is_not_registered_again(self, monkeypatch, listeners):
        _set_today(monkeypatch, DAY)
        coord = FakeCoordinator(cfg=_cfg())
        coord._register_charge_target_listener()
        coord._register_charge_target_listener()
        assert listeners.registered == [(1, 59)]
        assert listeners.cancelled == []

    def test_a_change_to_a_flat_tariff_cancels_the_listener(self, monkeypatch, listeners):
        _set_today(monkeypatch, DAY)
        coord = FakeCoordinator(cfg=_cfg())
        coord.entry.options = {CONF_TARIFF_CHANGES: [_change([])]}
        coord._register_charge_target_listener()
        _set_today(monkeypatch, CHANGE_DAY)
        coord._register_charge_target_listener()
        assert listeners.registered == [(1, 59)]
        assert listeners.cancelled == [(1, 59)]


@pytest.fixture(autouse=True)
def _fresh_issue_mocks():
    ir.async_create_issue.reset_mock()
    ir.async_delete_issue.reset_mock()


def _raised() -> list:
    return [c for c in ir.async_create_issue.call_args_list if c.args[2] == ISSUE_TARIFF_REVIEW_DUE]


def _cleared() -> int:
    return sum(1 for c in ir.async_delete_issue.call_args_list if c.args[2] == ISSUE_TARIFF_REVIEW_DUE)


def _coord_created(monkeypatch, days_ago: int, **options) -> FakeCoordinator:
    _set_today(monkeypatch, DAY)
    coord = FakeCoordinator(cfg=_cfg())
    coord.entry.created_at = _local(DAY) - timedelta(days=days_ago)
    coord.entry.options = options
    return coord


class TestStaleTariffRepair:
    def test_an_old_entry_that_was_never_reviewed_raises_a_fixable_issue(self, monkeypatch):
        coord = _coord_created(monkeypatch, TARIFF_REVIEW_STALE_DAYS + 30)

        coord._check_config_repair_issues(coord._effective_cfg())

        (call,) = _raised()
        assert call.kwargs["is_fixable"] is True
        assert call.kwargs["severity"] == "warning"
        assert call.kwargs["translation_key"] == ISSUE_TARIFF_REVIEW_DUE
        assert call.kwargs["learn_more_url"] == LEARN_MORE_URLS[ISSUE_TARIFF_REVIEW_DUE]
        assert call.kwargs["translation_placeholders"] == {
            "last_reviewed": (DAY - timedelta(days=TARIFF_REVIEW_STALE_DAYS + 30)).isoformat(),
            "days": str(TARIFF_REVIEW_STALE_DAYS + 30),
        }

    def test_a_recent_entry_raises_nothing_and_clears_the_issue(self, monkeypatch):
        coord = _coord_created(monkeypatch, 10)

        coord._check_config_repair_issues(coord._effective_cfg())

        assert _raised() == []
        assert _cleared() == 1

    def test_a_recent_review_clears_the_issue_on_an_old_entry(self, monkeypatch):
        coord = _coord_created(
            monkeypatch,
            TARIFF_REVIEW_STALE_DAYS + 30,
            **{CONF_TARIFF_REVIEWED_ON: (DAY - timedelta(days=3)).isoformat()},
        )

        coord._check_config_repair_issues(coord._effective_cfg())

        assert _raised() == []
        assert _cleared() == 1

    def test_the_issue_waits_for_the_stale_limit(self, monkeypatch):
        coord = _coord_created(monkeypatch, TARIFF_REVIEW_STALE_DAYS - 1)

        coord._check_config_repair_issues(coord._effective_cfg())

        assert _raised() == []

    def test_an_entry_without_a_creation_date_raises_nothing(self, monkeypatch):
        _set_today(monkeypatch, DAY)
        coord = FakeCoordinator(cfg=_cfg())

        coord._check_tariff_review(coord._effective_cfg())

        assert _raised() == []
        assert _cleared() == 0
