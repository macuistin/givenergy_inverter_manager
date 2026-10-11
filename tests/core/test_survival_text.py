"""The night survival text says when tonight's planned charge changes the picture.

The level of Battery Overnight Confidence is judged on the night without a charge, so on an
evening with a charge planned it can read May run low while the battery ends the night near the
target. The summary (the Now tile) and the explanation (the Battery detail view) therefore give
the figure with the planned charge too, whenever one counts, and say whether it covers a night
that is tight or short. They give one figure on a night with no charge in it. The verdict, the
confidence level and the outlook phrase do not depend on the charge.
"""

from __future__ import annotations

import itertools
from datetime import datetime

import pytest

from custom_components.givenergy_inverter_manager import sensor_values as values
from custom_components.givenergy_inverter_manager.const import STATE_MAX_LENGTH
from custom_components.givenergy_inverter_manager.core.battery import (
    SurvivalReport,
    survival_attributes,
)
from tests.core.test_sunrise_charge_engine import EVENING, _data

SHORTFALL = "Battery may run low. Estimated shortfall: 1.8kWh before solar starts."
FIGURE_ONLY = "Battery should last until solar. Estimated SoC at sunrise: 12%"


def _attrs(*, survive=True, without=40.0, with_charge=None, min_soc=10.0, reason="ok"):
    return survival_attributes(SurvivalReport(survive, without, min_soc, 60.0, reason, with_charge))


class TestAPlannedChargeThatCountsAndTheBatteryLastsAnyway:
    """Safe without a charge: the charge only adds the second figure."""

    def test_a_safe_night_says_both_figures_in_the_summary(self):
        assert _attrs(without=36.4, with_charge=89.2)["summary"] == (
            "Lasts the night · 36% at sunrise without a charge, about 89% with tonight's charge"
        )

    def test_a_safe_night_says_both_figures_in_the_explanation(self):
        assert _attrs(without=36.4, with_charge=89.2)["explanation"] == (
            "The battery should last until solar starts. It is expected to reach about 36% at "
            "sunrise without a charge, and about 89% with tonight's planned charge."
        )

    def test_the_outlook_and_the_level_figures_are_the_ones_without_a_charge(self):
        attrs = _attrs(without=36.4, with_charge=89.2)
        assert attrs["outlook"] == "Lasts the night"
        assert attrs["estimated_soc_at_sunrise"] == 36.4


class TestATightNightWithAPlannedCharge:
    def test_a_charge_that_covers_it_is_said_to_cover_it(self):
        attrs = _attrs(without=12.0, with_charge=89.0)
        assert attrs["outlook"] == "Only just lasts the night"
        assert attrs["summary"] == (
            "Only just lasts the night without a charge · tonight's charge covers it, "
            "about 89% at sunrise"
        )
        assert attrs["explanation"] == (
            "The battery should last until solar starts, but only just. Without a charge it is "
            "expected to reach about 12% at sunrise, within 5 points of the 10% minimum. "
            "Tonight's planned charge covers this: about 89% at sunrise."
        )

    def test_a_charge_that_leaves_it_tight_is_said_not_to_cover_it(self):
        attrs = _attrs(without=11.0, with_charge=14.0)
        assert attrs["outlook"] == "Only just lasts the night"
        assert attrs["summary"] == (
            "Only just lasts the night, even with tonight's charge · about 14% at sunrise"
        )
        assert attrs["explanation"].endswith(
            "Tonight's planned charge does not cover this: about 14% at sunrise."
        )

    def test_a_battery_that_ends_exactly_on_the_minimum_survives_only_because_of_the_charge(self):
        attrs = _attrs(survive=True, without=10.0, with_charge=89.0)
        assert attrs["outlook"] == "Only just lasts the night"
        assert "without a charge · tonight's charge covers it" in attrs["summary"]


class TestAShortNightWithAPlannedCharge:
    """The no-charge figure is at the floor: the night survives only because of the charge."""

    def test_a_charge_that_covers_it_says_so_and_keeps_the_shortfall(self):
        attrs = _attrs(survive=False, without=10.0, with_charge=89.0, reason=SHORTFALL)
        assert attrs["outlook"] == "May run low"
        assert attrs["summary"] == (
            "May run low without a charge · tonight's charge covers it, about 89% at sunrise"
        )
        assert attrs["explanation"] == (
            f"{SHORTFALL} Tonight's planned charge covers this: about 89% at sunrise."
        )

    def test_a_charge_that_does_not_reach_the_margin_says_so(self):
        attrs = _attrs(survive=False, without=10.0, with_charge=13.0, reason=SHORTFALL)
        assert attrs["summary"] == "May run low, even with tonight's charge · about 13% at sunrise"
        assert attrs["explanation"] == (
            f"{SHORTFALL} Tonight's planned charge does not cover this: about 13% at sunrise."
        )

    def test_the_covering_line_is_at_the_warning_margin(self):
        covered = _attrs(survive=False, without=10.0, with_charge=15.0, reason=SHORTFALL)
        short = _attrs(survive=False, without=10.0, with_charge=14.9, reason=SHORTFALL)
        assert "covers it" in covered["summary"]
        assert "even with tonight's charge" in short["summary"]

    def test_a_reason_without_a_full_stop_still_reads_as_a_sentence(self):
        attrs = _attrs(survive=False, without=10.0, with_charge=89.0, reason="Runs out")
        assert attrs["explanation"] == "Runs out. Tonight's planned charge covers this: about 89% at sunrise."


class TestNoChargeCounts:
    """One figure, as before: a skipped night, no timed window, a window that is over."""

    @pytest.mark.parametrize(
        ("kwargs", "summary"),
        [
            ({"without": 36.4}, "Lasts the night · 36% at sunrise"),
            ({"without": 12.0}, "Only just lasts the night · 12% at sunrise"),
            ({"survive": False, "without": 10.0}, "May run low"),
        ],
    )
    def test_the_summary_quotes_the_one_figure(self, kwargs, summary):
        assert _attrs(**kwargs)["summary"] == summary
        assert _attrs(**kwargs, with_charge=None)["summary"] == summary

    def test_the_explanations_are_as_before(self):
        assert _attrs(without=40.0, reason=FIGURE_ONLY)["explanation"] == FIGURE_ONLY
        assert _attrs(survive=False, without=10.0, reason=SHORTFALL)["explanation"] == SHORTFALL
        assert _attrs(without=12.0)["explanation"] == (
            "The battery should last until solar starts, but only just. "
            "It is expected to reach about 12% at sunrise, within 5 points of the 10% minimum."
        )

    @pytest.mark.parametrize("without", [36.0, 12.0, 10.0])
    def test_a_charge_that_adds_less_than_a_whole_point_says_nothing(self, without):
        quiet = _attrs(without=without, with_charge=without + 0.4)
        assert quiet == _attrs(without=without)

    def test_a_figure_with_the_charge_below_the_one_without_says_nothing(self):
        assert _attrs(without=36.4, with_charge=30.0) == _attrs(without=36.4)


class TestTheVerdictDoesNotMove:
    GRID = list(
        itertools.product(
            (True, False), (10.0, 12.0, 14.9, 15.0, 36.4), (None, 10.0, 14.0, 20.0, 89.0)
        )
    )

    @pytest.mark.parametrize(("survive", "without", "with_charge"), GRID)
    def test_the_outlook_and_the_figures_do_not_read_the_charge(self, survive, without, with_charge):
        alone = _attrs(survive=survive, without=without)
        both = _attrs(survive=survive, without=without, with_charge=with_charge)
        for key in ("outlook", "battery_soc", "estimated_soc_at_sunrise", "minimum_soc", "warning_below_soc"):
            assert both[key] == alone[key]

    @pytest.mark.parametrize(("survive", "without", "with_charge"), GRID)
    def test_every_text_stays_short_enough_for_a_state(self, survive, without, with_charge):
        attrs = _attrs(survive=survive, without=without, with_charge=with_charge, reason=SHORTFALL)
        assert len(attrs["summary"]) <= 100
        assert len(attrs["explanation"]) <= STATE_MAX_LENGTH

    @pytest.mark.parametrize(("survive", "without", "with_charge"), GRID)
    def test_no_text_says_survival(self, survive, without, with_charge):
        attrs = _attrs(survive=survive, without=without, with_charge=with_charge)
        assert "surviv" not in (attrs["summary"] + attrs["explanation"]).lower()


class TestWithTheEngine:
    """The evening of the review: 19:00 in June, a charge planned for 02:00 to 04:00."""

    @staticmethod
    def _attrs_of(data):
        return values.night_survival_attributes(data)

    def test_a_battery_that_would_run_flat_shows_the_charge_that_covers_it(self):
        data = _data(EVENING, 66.0)
        attrs = self._attrs_of(data)
        assert values.night_survival_confidence(data) == "Critical"
        assert attrs["outlook"] == "May run low"
        assert attrs["summary"] == (
            "May run low without a charge · tonight's charge covers it, about 67% at sunrise"
        )
        assert attrs["explanation"].startswith("Battery may run low. Estimated shortfall:")
        assert attrs["explanation"].endswith("Tonight's planned charge covers this: about 67% at sunrise.")

    def test_a_battery_that_lasts_with_room_to_spare_shows_both_figures(self):
        data = _data(EVENING, 95.0)
        attrs = self._attrs_of(data)
        assert values.night_survival_confidence(data) == "Safe"
        assert attrs["summary"] == (
            "Lasts the night · 20% at sunrise without a charge, about 67% with tonight's charge"
        )

    def test_a_tight_battery_shows_that_the_charge_covers_it(self):
        data = _data(EVENING, 90.0)
        attrs = self._attrs_of(data)
        assert values.night_survival_confidence(data) == "Warning"
        assert attrs["summary"] == (
            "Only just lasts the night without a charge · tonight's charge covers it, "
            "about 67% at sunrise"
        )
        assert "Without a charge it is expected to reach about 15% at sunrise" in attrs["explanation"]

    @pytest.mark.parametrize("soc", [66.0, 90.0, 95.0])
    def test_a_skipped_night_quotes_the_one_figure(self, soc):
        data = _data(EVENING, soc, override_skip_charge=True, override_charge_target=None)
        attrs = self._attrs_of(data)
        assert not data.sunrise_with_charge.charge_counts
        assert "with tonight's charge" not in attrs["summary"]
        assert "planned charge" not in attrs["explanation"]
        assert "even with" not in attrs["summary"]

    def test_a_night_with_no_timed_window_quotes_the_one_figure(self):
        cfg = {**_cfg(), "rate_periods": []}
        attrs = self._attrs_of(_data(EVENING, 66.0, cfg=cfg))
        assert attrs["summary"] == "May run low"

    def test_a_window_that_is_over_quotes_the_one_figure(self):
        data = _data(datetime(2026, 6, 15, 5, 0), 85.0)
        assert not data.sunrise_with_charge.charge_counts
        assert "tonight's charge" not in self._attrs_of(data)["summary"]

    def test_a_battery_already_at_the_target_when_the_window_opens_adds_nothing_to_say(self):
        data = _data(datetime(2026, 6, 15, 23, 0), 95.0, override_charge_target=50)
        assert not data.sunrise_with_charge.charge_counts
        assert "tonight's charge" not in self._attrs_of(data)["summary"]

    @pytest.mark.parametrize("soc", [66.0, 88.0, 90.0, 95.0, 100.0])
    def test_the_verdict_is_the_same_with_the_charge_planned_or_skipped(self, soc):
        planned = _data(EVENING, soc)
        skipped = _data(EVENING, soc, override_skip_charge=True, override_charge_target=None)
        assert planned.will_survive_night == skipped.will_survive_night
        assert planned.survival_reason == skipped.survival_reason
        assert planned.estimated_soc_at_sunrise == skipped.estimated_soc_at_sunrise
        assert values.night_survival_confidence(planned) == values.night_survival_confidence(skipped)
        assert self._attrs_of(planned)["outlook"] == self._attrs_of(skipped)["outlook"]

    @pytest.mark.parametrize("soc", [66.0, 90.0, 95.0])
    def test_the_texts_fit_a_state(self, soc):
        attrs = self._attrs_of(_data(EVENING, soc))
        assert len(attrs["summary"]) <= 100
        assert len(attrs["explanation"]) <= STATE_MAX_LENGTH


def _cfg():
    from tests.conftest import _nightboost_cfg

    return _nightboost_cfg()
