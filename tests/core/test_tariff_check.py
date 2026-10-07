"""Comparing the tariff entered here with the rates GivTCP holds."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.const import GIVTCP_RATE_TOLERANCE_PCT
from custom_components.givenergy_inverter_manager.core.tariff import build_tariff
from custom_components.givenergy_inverter_manager.core.tariff_check import (
    GivTCPRates,
    describe_rate_mismatches,
    find_rate_mismatches,
)
from tests.conftest import _nightboost_cfg

# Base 0.3334, Night 0.1644, Nightboost 0.0965, export 0.195.
TARIFF = build_tariff(_nightboost_cfg())


def _mismatches(**rates):
    return find_rate_mismatches(TARIFF, GivTCPRates(**rates), GIVTCP_RATE_TOLERANCE_PCT)


def test_rates_that_match_raise_nothing():
    assert _mismatches(day=0.3334, night=0.1644, export=0.195) == []


def test_a_day_rate_that_differs_names_both_values():
    (mismatch,) = _mismatches(day=0.395)

    assert (mismatch.label, mismatch.here, mismatch.givtcp) == ("Day rate", 0.3334, 0.395)
    assert mismatch.line == "Day rate: 0.3334 here, 0.395 in GivTCP"


def test_an_export_rate_that_differs_is_reported():
    (mismatch,) = _mismatches(export=0.2)

    assert (mismatch.label, mismatch.here, mismatch.givtcp) == ("Export rate", 0.195, 0.2)


@pytest.mark.parametrize("night", [0.1644, 0.0965])
def test_the_night_rate_agrees_when_it_matches_any_timed_period(night):
    assert _mismatches(night=night) == []


def test_a_night_rate_that_matches_no_timed_period_is_compared_with_the_closest():
    (mismatch,) = _mismatches(night=0.14)

    assert (mismatch.label, mismatch.here) == ("Night rate", 0.1644)


def test_a_tariff_with_no_timed_period_has_no_night_rate_to_compare():
    flat = build_tariff({**_nightboost_cfg(), "rate_periods": []})

    assert find_rate_mismatches(flat, GivTCPRates(night=0.05), GIVTCP_RATE_TOLERANCE_PCT) == []


def test_a_difference_inside_the_tolerance_is_ignored():
    just_inside = 0.3334 * (1 + GIVTCP_RATE_TOLERANCE_PCT / 100 - 0.001)

    assert _mismatches(day=just_inside) == []


def test_a_difference_just_beyond_the_tolerance_is_reported():
    just_beyond = 0.3334 * (1 + GIVTCP_RATE_TOLERANCE_PCT / 100 + 0.001)

    assert len(_mismatches(day=just_beyond)) == 1


def test_a_lower_givtcp_rate_is_reported_too():
    assert len(_mismatches(day=0.30)) == 1


def test_rates_givtcp_does_not_hold_are_skipped():
    assert _mismatches(day=None, night=None, export=None) == []


def test_a_zero_rate_on_either_side_is_skipped():
    no_export_here = build_tariff({**_nightboost_cfg(), "export_rate": 0.0})

    assert _mismatches(export=0.0) == []
    assert find_rate_mismatches(no_export_here, GivTCPRates(export=0.05), 2.0) == []


def test_any_held_is_false_when_no_rate_is_held():
    assert GivTCPRates().any_held is False
    assert GivTCPRates(export=0.2).any_held is True


def test_the_description_lists_one_rate_per_line():
    text = describe_rate_mismatches(_mismatches(day=0.395, export=0.2))

    assert text == (
        "- Day rate: 0.3334 here, 0.395 in GivTCP\n- Export rate: 0.195 here, 0.2 in GivTCP"
    )
