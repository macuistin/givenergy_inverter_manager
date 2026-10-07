"""Dated rate changes and the stale-tariff age, as pure logic (no Home Assistant)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_CURRENCY,
    CONF_EXPORT_RATE,
    CONF_RATE_PERIODS,
    CONF_STANDING_CHARGE,
    CONF_TARIFF_CHANGES,
    CONF_TARIFF_REVIEWED_ON,
    CONF_VAT_RATE,
    TARIFF_REVIEW_STALE_DAYS,
)
from custom_components.givenergy_inverter_manager.core.tariff import (
    TariffChange,
    TariffSubmission,
    build_tariff,
    changes_started,
    changes_still_ahead,
    changes_with_scheduled,
    last_tariff_review,
    options_after_reconfigure,
    options_after_tariff_save,
    parse_tariff_changes,
    scheduled_tariff_changes,
    stale_tariff_age_days,
    tariff_in_force,
)
from tests.conftest import _nightboost_cfg

TODAY = date(2026, 6, 15)
CHANGE_DAY = date(2026, 11, 1)
NEW_PERIODS = [{"name": "Night", "rate": 0.2, "start": "23:00", "end": "07:00"}]


def _rates(base: float = 0.4, export: float = 0.21) -> dict:
    return {
        CONF_BASE_RATE: base,
        CONF_BASE_RATE_NAME: "Standard",
        CONF_EXPORT_RATE: export,
        CONF_RATE_PERIODS: NEW_PERIODS,
    }


def _change(day: date = CHANGE_DAY, **rates) -> dict:
    return {"effective": day.isoformat(), **(_rates(**rates))}


def _cfg(*changes: dict) -> dict:
    cfg = _nightboost_cfg()
    if changes:
        cfg[CONF_TARIFF_CHANGES] = list(changes)
    return cfg


class TestTariffInForce:
    def test_no_change_returns_the_config_itself(self):
        cfg = _nightboost_cfg()
        assert tariff_in_force(cfg, TODAY) is cfg

    def test_old_rates_apply_up_to_the_day_before(self):
        cfg = _cfg(_change())
        in_force = tariff_in_force(cfg, date(2026, 10, 31))
        assert in_force[CONF_BASE_RATE] == pytest.approx(0.3334)
        assert in_force[CONF_BASE_RATE_NAME] == "Day"

    def test_new_rates_apply_from_the_effective_date(self):
        cfg = _cfg(_change())
        in_force = tariff_in_force(cfg, CHANGE_DAY)
        assert in_force[CONF_BASE_RATE] == pytest.approx(0.4)
        assert in_force[CONF_BASE_RATE_NAME] == "Standard"
        assert in_force[CONF_EXPORT_RATE] == pytest.approx(0.21)
        assert in_force[CONF_RATE_PERIODS] == NEW_PERIODS

    def test_charges_are_not_dated(self):
        cfg = _cfg(_change())
        in_force = tariff_in_force(cfg, CHANGE_DAY)
        assert in_force[CONF_STANDING_CHARGE] == cfg[CONF_STANDING_CHARGE]
        assert in_force[CONF_VAT_RATE] == cfg[CONF_VAT_RATE]

    def test_the_latest_started_change_wins_on_its_own(self):
        cfg = _cfg(_change(date(2026, 8, 1), base=0.35), _change(CHANGE_DAY, base=0.4))
        assert tariff_in_force(cfg, date(2026, 9, 1))[CONF_BASE_RATE] == pytest.approx(0.35)
        assert tariff_in_force(cfg, date(2026, 12, 1))[CONF_BASE_RATE] == pytest.approx(0.4)

    def test_the_tariff_built_from_it_prices_each_side_of_the_date(self):
        cfg = _cfg(_change())
        noon = {"before": datetime(2026, 10, 31, 12), "after": datetime(2026, 11, 1, 12)}
        before = build_tariff(tariff_in_force(cfg, noon["before"].date()))
        after = build_tariff(tariff_in_force(cfg, noon["after"].date()))
        assert before.get_current_rate(noon["before"]).rate == pytest.approx(0.3334)
        assert after.get_current_rate(noon["after"]).rate == pytest.approx(0.4)

    def test_a_malformed_change_is_skipped(self):
        broken = [
            {"effective": "not a date", **_rates()},
            {"effective": "2026-11-01", CONF_BASE_RATE: 0.4},
            {"effective": "2026-11-01", **{**_rates(), CONF_RATE_PERIODS: "Night"}},
            "nonsense",
        ]
        cfg = _cfg(*broken)
        assert tariff_in_force(cfg, date(2027, 1, 1)) is cfg

    def test_stored_changes_that_are_not_a_list_are_ignored(self):
        cfg = _nightboost_cfg()
        cfg[CONF_TARIFF_CHANGES] = "2026-11-01"
        assert tariff_in_force(cfg, date(2027, 1, 1)) is cfg


class TestParseTariffChanges:
    def test_changes_come_back_in_date_order(self):
        raw = [_change(date(2026, 12, 1)), _change(date(2026, 9, 1))]
        assert [c.effective for c in parse_tariff_changes(raw)] == [
            date(2026, 9, 1),
            date(2026, 12, 1),
        ]

    def test_two_entries_for_one_date_keep_the_later(self):
        raw = [_change(base=0.4), _change(base=0.45)]
        (only,) = parse_tariff_changes(raw)
        assert only.rates[CONF_BASE_RATE] == pytest.approx(0.45)

    def test_scheduled_changes_are_those_after_today(self):
        cfg = _cfg(_change(date(2026, 6, 15)), _change(CHANGE_DAY))
        assert [c.effective for c in scheduled_tariff_changes(cfg, TODAY)] == [CHANGE_DAY]


class TestStoredChanges:
    def test_adding_a_change_for_a_stored_date_replaces_it(self):
        raw = [_change(base=0.4)]
        updated = changes_with_scheduled(raw, TariffChange(CHANGE_DAY, _rates(base=0.5)))
        assert len(updated) == 1
        assert updated[0][CONF_BASE_RATE] == pytest.approx(0.5)

    def test_adding_a_change_keeps_the_others_in_date_order(self):
        raw = [_change(date(2026, 12, 1))]
        updated = changes_with_scheduled(raw, TariffChange(CHANGE_DAY, _rates()))
        assert [c["effective"] for c in updated] == ["2026-11-01", "2026-12-01"]

    def test_still_ahead_and_started_split_the_changes_at_today(self):
        raw = [_change(date(2026, 6, 1)), _change(TODAY), _change(CHANGE_DAY)]
        assert [c["effective"] for c in changes_started(raw, TODAY)] == ["2026-06-01", "2026-06-15"]
        assert [c["effective"] for c in changes_still_ahead(raw, TODAY)] == ["2026-11-01"]

    def test_a_stored_change_survives_a_round_trip(self):
        change = TariffChange(CHANGE_DAY, _rates())
        assert parse_tariff_changes([change.as_stored()]) == [change]


def _updates(base: float = 0.4) -> dict:
    """What the options form parses to: rates, charges and the currency."""
    return {
        **_rates(base=base),
        CONF_STANDING_CHARGE: 0.9,
        CONF_VAT_RATE: 13.5,
        CONF_CURRENCY: "EUR",
    }


class TestOptionsAfterTariffSave:
    def test_with_no_change_it_is_the_plain_merge(self):
        options = {"battery_min_soc_pct": 12}
        in_force = _nightboost_cfg()
        updates = _updates_of(in_force)
        saved = options_after_tariff_save(options, in_force, TariffSubmission(updates), TODAY)
        assert saved == {**options, **updates}

    def test_a_dated_save_records_the_rates_and_leaves_the_saved_ones(self):
        options = {CONF_BASE_RATE: 0.3334}
        sub = TariffSubmission(_updates(), effective=CHANGE_DAY)
        saved = options_after_tariff_save(options, _nightboost_cfg(), sub, TODAY)
        assert saved[CONF_BASE_RATE] == pytest.approx(0.3334)
        assert saved[CONF_TARIFF_CHANGES] == [{"effective": "2026-11-01", **_rates()}]

    def test_a_dated_save_applies_the_charges_now(self):
        sub = TariffSubmission(_updates(), effective=CHANGE_DAY)
        saved = options_after_tariff_save({}, _nightboost_cfg(), sub, TODAY)
        assert saved[CONF_STANDING_CHARGE] == pytest.approx(0.9)
        assert saved[CONF_VAT_RATE] == pytest.approx(13.5)
        assert CONF_EXPORT_RATE not in saved

    def test_a_dated_save_counts_as_a_review(self):
        sub = TariffSubmission(_updates(), effective=CHANGE_DAY)
        saved = options_after_tariff_save({}, _nightboost_cfg(), sub, TODAY)
        assert saved[CONF_TARIFF_REVIEWED_ON] == "2026-06-15"

    def test_a_dated_save_keeps_a_change_in_force_so_the_old_rates_stay_current(self):
        options = {CONF_TARIFF_CHANGES: [_change(date(2026, 6, 1), base=0.35)]}
        sub = TariffSubmission(_updates(), effective=CHANGE_DAY)
        saved = options_after_tariff_save(options, tariff_in_force(_cfg(*options[CONF_TARIFF_CHANGES]), TODAY), sub, TODAY)
        assert [c["effective"] for c in saved[CONF_TARIFF_CHANGES]] == ["2026-06-01", "2026-11-01"]

    def test_a_save_dated_today_applies_now(self):
        sub = TariffSubmission(_updates(), effective=TODAY)
        saved = options_after_tariff_save({}, _nightboost_cfg(), sub, TODAY)
        assert saved[CONF_BASE_RATE] == pytest.approx(0.4)
        assert CONF_TARIFF_CHANGES not in saved

    def test_saving_now_supersedes_started_changes_and_keeps_those_ahead(self):
        options = {CONF_TARIFF_CHANGES: [_change(date(2026, 6, 1), base=0.35), _change()]}
        in_force = tariff_in_force(_cfg(*options[CONF_TARIFF_CHANGES]), TODAY)
        saved = options_after_tariff_save(options, in_force, TariffSubmission(_updates(0.37)), TODAY)
        assert saved[CONF_BASE_RATE] == pytest.approx(0.37)
        assert [c["effective"] for c in saved[CONF_TARIFF_CHANGES]] == ["2026-11-01"]

    def test_saving_now_leaves_no_empty_key_behind(self):
        options = {CONF_TARIFF_CHANGES: [_change(date(2026, 6, 1))]}
        in_force = tariff_in_force(_cfg(*options[CONF_TARIFF_CHANGES]), TODAY)
        saved = options_after_tariff_save(options, in_force, TariffSubmission(_updates()), TODAY)
        assert CONF_TARIFF_CHANGES not in saved

    def test_cancelling_removes_only_changes_that_have_not_started(self):
        options = {CONF_TARIFF_CHANGES: [_change(date(2026, 6, 1)), _change()]}
        in_force = tariff_in_force(_cfg(*options[CONF_TARIFF_CHANGES]), TODAY)
        sub = TariffSubmission(_updates_of(in_force), cancel_scheduled=True)
        saved = options_after_tariff_save(options, in_force, sub, TODAY)
        assert CONF_TARIFF_CHANGES not in saved

    def test_cancelling_leaves_a_started_change_in_force(self):
        options = {CONF_TARIFF_CHANGES: [_change(date(2026, 6, 1)), _change()]}
        in_force = tariff_in_force(_cfg(*options[CONF_TARIFF_CHANGES]), TODAY)
        sub = TariffSubmission(_updates_of(in_force), effective=date(2026, 12, 1), cancel_scheduled=True)
        saved = options_after_tariff_save(options, in_force, sub, TODAY)
        assert [c["effective"] for c in saved[CONF_TARIFF_CHANGES]] == ["2026-06-01", "2026-12-01"]

    def test_an_unchanged_tariff_does_not_move_the_review_date(self):
        in_force = _nightboost_cfg()
        sub = TariffSubmission(_updates_of(in_force))
        saved = options_after_tariff_save({}, in_force, sub, TODAY)
        assert CONF_TARIFF_REVIEWED_ON not in saved

    def test_a_changed_tariff_moves_the_review_date(self):
        in_force = _nightboost_cfg()
        saved = options_after_tariff_save({}, in_force, TariffSubmission(_updates()), TODAY)
        assert saved[CONF_TARIFF_REVIEWED_ON] == "2026-06-15"


def _updates_of(cfg: dict) -> dict:
    """The form values that leave *cfg* unchanged."""
    return {
        CONF_BASE_RATE: cfg[CONF_BASE_RATE],
        CONF_BASE_RATE_NAME: cfg[CONF_BASE_RATE_NAME],
        CONF_EXPORT_RATE: cfg[CONF_EXPORT_RATE],
        CONF_RATE_PERIODS: cfg[CONF_RATE_PERIODS],
        CONF_CURRENCY: "EUR",
    }


class TestOptionsAfterReconfigure:
    def test_saved_options_for_the_updated_keys_go_and_the_review_date_is_set(self):
        options = {CONF_BASE_RATE: 0.3, "battery_min_soc_pct": 12}
        saved = options_after_reconfigure(options, {CONF_BASE_RATE: 0.4}, TODAY)
        assert saved == {"battery_min_soc_pct": 12, CONF_TARIFF_REVIEWED_ON: "2026-06-15"}

    def test_started_changes_end_and_scheduled_ones_stay(self):
        options = {CONF_TARIFF_CHANGES: [_change(date(2026, 6, 1)), _change()]}
        saved = options_after_reconfigure(options, {CONF_BASE_RATE: 0.4}, TODAY)
        assert [c["effective"] for c in saved[CONF_TARIFF_CHANGES]] == ["2026-11-01"]


class TestStaleTariffAge:
    REVIEWED = date(2025, 6, 15)

    @staticmethod
    def _cfg(reviewed: date | None) -> dict:
        return {} if reviewed is None else {CONF_TARIFF_REVIEWED_ON: reviewed.isoformat()}

    def test_a_tariff_with_no_recorded_review_is_never_stale(self):
        assert last_tariff_review({}) is None
        assert stale_tariff_age_days({}, TODAY) is None

    def test_a_bad_review_date_counts_as_none_recorded(self):
        cfg = {CONF_TARIFF_REVIEWED_ON: "last spring"}
        assert last_tariff_review(cfg) is None
        assert stale_tariff_age_days(cfg, TODAY) is None

    def test_one_day_short_of_the_limit_is_not_stale(self):
        today = date.fromordinal(self.REVIEWED.toordinal() + TARIFF_REVIEW_STALE_DAYS - 1)
        assert stale_tariff_age_days(self._cfg(self.REVIEWED), today) is None

    def test_the_limit_day_is_stale_and_reports_the_age(self):
        today = date.fromordinal(self.REVIEWED.toordinal() + TARIFF_REVIEW_STALE_DAYS)
        age = stale_tariff_age_days(self._cfg(self.REVIEWED), today)
        assert age == TARIFF_REVIEW_STALE_DAYS

    def test_a_review_in_the_future_is_not_stale(self):
        assert stale_tariff_age_days(self._cfg(date(2027, 1, 1)), TODAY) is None
