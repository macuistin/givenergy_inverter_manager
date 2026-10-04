"""Wording of the tariff summary shown on the options and confirm forms."""

import pytest

from custom_components.givenergy_inverter_manager.config_flow import _ordinal, _tariff_summary


@pytest.mark.parametrize(
    ("day", "text"),
    [
        (1, "1st"),
        (2, "2nd"),
        (3, "3rd"),
        (4, "4th"),
        (11, "11th"),
        (12, "12th"),
        (15, "15th"),
        (16, "16th"),
        (21, "21st"),
        (22, "22nd"),
        (23, "23rd"),
        (28, "28th"),
    ],
)
def test_ordinal(day, text):
    assert _ordinal(day) == text


def _cfg(**extra):
    base = {
        "base_rate": 0.33,
        "base_rate_name": "Day",
        "rate_periods": [{"name": "Night", "rate": 0.15, "start": "23:00", "end": "08:00"}],
        "bill_start_day": 16,
        "currency": "EUR",
    }
    base.update(extra)
    return base


def test_summary_names_the_cheapest_timed_period_and_the_billing_period():
    text = _tariff_summary(_cfg())
    assert "Night at 0.1500 EUR/kWh, 23:00 to 08:00" in text
    assert "from the 16th to the 15th" in text


def test_summary_says_all_day_when_the_base_rate_is_cheapest():
    text = _tariff_summary(_cfg(base_rate=0.05))
    assert "Day at 0.0500 EUR/kWh, all day" in text


def test_summary_for_a_bill_starting_on_the_first():
    assert "from the 1st to the last day of the month" in _tariff_summary(_cfg(bill_start_day=1))


def test_summary_is_empty_when_the_tariff_cannot_be_built():
    assert _tariff_summary(_cfg(base_rate="not a number")) == ""
