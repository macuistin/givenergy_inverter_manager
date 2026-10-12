"""The tariff pages of the wizards: counts, rows, validation and what a save asks for."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.givenergy_inverter_manager.core.tariff import options_after_tariff_save
from custom_components.givenergy_inverter_manager.core.wizard_tariff import (
    MAX_RATE_PERIODS,
    clean_bill,
    clean_tariff,
    count_from_input,
    default_rate_rows,
    night_window,
    ordinal,
    rate_count,
    rate_period_errors,
    rows_from_sections,
    tariff_page_summary,
    tariff_submission,
    tariff_summary,
    validate_bill,
    validate_change_date,
    validate_rates,
    validate_tariff,
)

TODAY = date(2031, 6, 15)
NIGHT = {"name": "Night", "rate": 0.15, "start": "23:00", "end": "08:00"}
BOOST = {"name": "Boost", "rate": 0.08, "start": "02:00", "end": "04:00"}
IN_FORCE = {
    "base_rate": 0.33,
    "base_rate_name": "Day",
    "export_rate": 0.2,
    "rate_periods": [NIGHT],
    "vat_rate": 9.0,
}


def test_the_count_is_the_number_of_saved_rates_and_never_above_the_form_cap():
    assert rate_count([]) == 0
    assert rate_count([NIGHT, BOOST]) == 2
    assert rate_count([NIGHT] * 8) == MAX_RATE_PERIODS
    assert rate_count(None) == 0


@pytest.mark.parametrize(
    ("submitted", "expected"), [("2", 2), (3, 3), ("", 0), ("x", 0), (None, 0), ("-1", 0)]
)
def test_the_count_reads_what_the_select_sent(submitted, expected):
    assert count_from_input({"rate_count": submitted}) == expected


def test_a_missing_count_is_zero():
    assert count_from_input({}) == 0


class TestRows:
    def test_new_rows_get_names_and_windows_that_cannot_clash(self):
        rows = default_rate_rows(5, [], night_window("IE"))

        assert [r["name"] for r in rows] == ["Night", "Peak", "Rate 3", "Rate 4", "Rate 5"]
        assert all(r["rate"] is None for r in rows)
        assert all(r["start"] != r["end"] for r in rows)
        assert rows[0]["start"] == "23:00:00"
        assert rows[0]["end"] == "08:00:00"

    def test_saved_rows_come_first_with_times_as_the_selector_wants_them(self):
        rows = default_rate_rows(2, [NIGHT], night_window("GB"))

        assert rows[0] == {"name": "Night", "rate": 0.15, "start": "23:00:00", "end": "08:00:00"}
        assert rows[1]["name"] == "Peak"
        assert rows[1]["rate"] is None

    def test_lowering_the_count_drops_the_last_rows(self):
        rows = default_rate_rows(1, [NIGHT, BOOST], night_window(None))

        assert [r["name"] for r in rows] == ["Night"]

    def test_the_night_window_follows_the_country_and_has_a_fallback(self):
        assert night_window("ie") == ("23:00", "08:00")
        assert night_window("GB") == ("00:30", "07:30")
        assert night_window("DE") == ("23:00", "07:00")
        assert night_window(None) == ("23:00", "07:00")

    def test_rows_come_back_as_stored_periods(self):
        submitted = {
            "rate_period_1": {"name": " Night ", "rate": 0.15, "start": "23:00:00", "end": "08:00:00"},
            "rate_period_2": {"name": "Boost", "rate": 0.08, "start": "02:00:00", "end": "04:00:00"},
        }

        assert rows_from_sections(submitted, 2) == [NIGHT, BOOST]

    def test_a_row_the_client_left_out_is_skipped_and_rows_beyond_the_count_are_ignored(self):
        submitted = {"rate_period_2": BOOST | {"start": "02:00:00", "end": "04:00:00"}}
        submitted["rate_period_3"] = {"name": "Ignored", "rate": 1, "start": "01:00", "end": "02:00"}

        assert [r["name"] for r in rows_from_sections(submitted, 2)] == ["Boost"]


class TestValidation:
    def test_a_zero_base_rate_needs_a_timed_rate_to_cover_the_day(self):
        assert validate_tariff({"base_rate": 0.0, "rate_count": "0"}).errors == {
            "base": "base_rate_required"
        }
        assert validate_tariff({"base_rate": 0.0, "rate_count": "1"}).errors == {}
        assert validate_tariff({"base_rate": 0.3, "rate_count": "0"}).errors == {}

    def test_more_rows_than_the_cap_is_refused(self):
        assert validate_tariff({"base_rate": 0.3, "rate_count": "6"}).errors == {
            "base": "too_many_periods"
        }
        assert rate_period_errors([NIGHT] * 6) == {"base": "too_many_periods"}

    def test_a_row_cannot_start_and_end_together(self):
        assert rate_period_errors([{**NIGHT, "end": "23:00"}]) == {"base": "rate_period_zero_length"}

    def test_a_row_needs_a_name(self):
        assert rate_period_errors([{**NIGHT, "name": ""}]) == {"base": "rate_period_name_missing"}

    def test_names_are_unique_whatever_the_case_and_differ_from_the_base_name(self):
        assert rate_period_errors([NIGHT, {**BOOST, "name": "NIGHT"}]) == {
            "base": "rate_period_duplicate_name"
        }
        assert rate_period_errors([NIGHT], "night") == {"base": "rate_period_duplicate_name"}
        assert rate_period_errors([NIGHT, BOOST], "Day") == {}
        assert rate_period_errors([]) == {}

    def test_the_rates_step_reports_the_same_errors(self):
        assert validate_rates([NIGHT], "Night").errors == {"base": "rate_period_duplicate_name"}
        assert validate_rates([NIGHT], "Day").errors == {}

    def test_the_bill_step_needs_a_base_name_that_differs_from_the_timed_names(self):
        assert validate_bill({"base_rate_name": " "}, []).errors == {"base": "base_rate_name_missing"}
        assert validate_bill({"base_rate_name": "night"}, [NIGHT]).errors == {
            "base": "rate_period_duplicate_name"
        }
        assert validate_bill({"base_rate_name": "Day"}, [NIGHT]).errors == {}

    def test_a_rate_change_cannot_start_in_the_past_but_today_is_fine(self):
        assert validate_change_date(date(2031, 6, 14), TODAY).errors == {
            "base": "tariff_change_date_in_past"
        }
        assert validate_change_date(TODAY, TODAY).errors == {}
        assert validate_change_date(None, TODAY).errors == {}


class TestClean:
    def test_the_tariff_values_are_numbers(self):
        assert clean_tariff({"base_rate": "0.3", "export_rate": 0.1, "rate_count": "2"}) == {
            "base_rate": 0.3,
            "export_rate": 0.1,
        }

    def test_the_bill_values_have_their_stored_types_and_only_what_was_sent(self):
        cleaned = clean_bill(
            {
                "currency": "GBP",
                "base_rate_name": " Standard ",
                "bill_start_day": 16.0,
                "standing_charge_per_day": "0.5",
                "pso_levy_per_month": 1,
                "vat_rate": 5,
                "discount_rate": 0,
            }
        )

        assert cleaned == {
            "currency": "GBP",
            "base_rate_name": "Standard",
            "bill_start_day": 16,
            "standing_charge_per_day": 0.5,
            "pso_levy_per_month": 1.0,
            "vat_rate": 5.0,
            "discount_rate": 0.0,
        }
        assert clean_bill({"vat_rate": 5}) == {"vat_rate": 5.0}


class TestSubmission:
    def test_only_what_differs_from_the_rates_in_force_is_asked_for(self):
        sub = tariff_submission({"base_rate": 0.33, "export_rate": 0.25}, IN_FORCE, IN_FORCE, (None, False))

        assert sub.updates == {"export_rate": 0.25}
        assert sub.effective is None
        assert sub.cancel_scheduled is False

    def test_a_dated_change_carries_the_complete_set_of_unit_rates(self):
        sub = tariff_submission({"base_rate": 0.4}, IN_FORCE, IN_FORCE, (date(2031, 9, 1), False))

        assert sub.updates == {
            "base_rate": 0.4,
            "base_rate_name": "Day",
            "export_rate": 0.2,
            "rate_periods": [NIGHT],
        }
        saved = options_after_tariff_save({}, IN_FORCE, sub, TODAY)
        (change,) = saved["tariff_changes"]
        assert change["effective"] == "2031-09-01"
        assert change["rate_periods"] == [NIGHT]
        assert "base_rate" not in saved

    def test_saving_over_a_started_change_writes_the_rates_in_force(self):
        saved_cfg = {**IN_FORCE, "base_rate": 0.30}  # the dated change in force has base 0.33
        sub = tariff_submission({"vat_rate": 13.5}, saved_cfg, IN_FORCE, (None, False))

        assert sub.updates["vat_rate"] == 13.5
        assert sub.updates["base_rate"] == 0.33
        assert sub.updates["rate_periods"] == [NIGHT]

    def test_an_unchanged_tariff_with_nothing_in_force_adds_no_rates(self):
        sub = tariff_submission({"vat_rate": 13.5}, IN_FORCE, IN_FORCE, (None, False))

        assert sub.updates == {"vat_rate": 13.5}

    def test_the_cancel_request_is_passed_on(self):
        sub = tariff_submission({}, IN_FORCE, IN_FORCE, (None, True))

        assert sub.cancel_scheduled is True
        assert sub.updates == {}


class TestText:
    @pytest.mark.parametrize(
        ("day", "text"), [(1, "1st"), (2, "2nd"), (3, "3rd"), (11, "11th"), (22, "22nd"), (28, "28th")]
    )
    def test_ordinal(self, day, text):
        assert ordinal(day) == text

    def test_the_summary_names_the_cheapest_rate_and_the_billing_period(self):
        text = tariff_summary({**IN_FORCE, "bill_start_day": 16, "currency": "EUR"})

        assert "Night at 0.1500 EUR/kWh, 23:00 to 08:00" in text
        assert "from the 16th to the 15th" in text

    def test_the_summary_is_empty_when_the_tariff_cannot_be_built(self):
        assert tariff_summary({"base_rate": "not a number"}) == ""

    def test_the_page_summary_for_a_set_and_an_unset_tariff(self):
        assert tariff_page_summary({}) == "not set yet"
        line = tariff_page_summary({**IN_FORCE, "currency": "GBP"})
        assert "Day 0.3300 GBP/kWh, export 0.2000" in line
        assert "1 time-of-day rate" in line
        assert "rates" not in line


# ── Starting values from the inverter integration ─────────────────────────────


class TestRatePrefill:
    def test_a_readable_rate_above_zero_is_offered(self):
        from custom_components.givenergy_inverter_manager.core.inverter_values import RateDefaults
        from custom_components.givenergy_inverter_manager.core.wizard_tariff import rate_prefill

        offered = rate_prefill(RateDefaults(day_rate=0.29, night_rate=0.14, export_rate=0.1))

        assert (offered.day_rate, offered.night_rate, offered.export_rate) == (0.29, 0.14, 0.1)

    @pytest.mark.parametrize("value", [None, 0, 0.0, -0.1])
    def test_a_missing_zero_or_negative_rate_is_not_offered(self, value):
        from custom_components.givenergy_inverter_manager.core.inverter_values import RateDefaults
        from custom_components.givenergy_inverter_manager.core.wizard_tariff import rate_prefill

        offered = rate_prefill(RateDefaults(day_rate=value, night_rate=value, export_rate=value))

        assert offered == RateDefaults()

    def test_nothing_held_offers_nothing(self):
        from custom_components.givenergy_inverter_manager.core.inverter_values import RateDefaults
        from custom_components.givenergy_inverter_manager.core.wizard_tariff import rate_prefill

        assert rate_prefill(None) == RateDefaults()

    def test_each_rate_is_judged_on_its_own(self):
        from custom_components.givenergy_inverter_manager.core.inverter_values import RateDefaults
        from custom_components.givenergy_inverter_manager.core.wizard_tariff import rate_prefill

        offered = rate_prefill(RateDefaults(day_rate=0.29, night_rate=0, export_rate=None))

        assert (offered.day_rate, offered.night_rate, offered.export_rate) == (0.29, None, None)

    def test_the_note_appears_only_when_a_value_was_offered(self):
        from custom_components.givenergy_inverter_manager.core.wizard_tariff import (
            RATE_NOTE,
            rate_note,
        )

        assert rate_note(None, None) == ""
        assert rate_note(None, 0.1) == f"\n\n{RATE_NOTE}"

    def test_the_night_rate_goes_to_the_first_new_row_and_the_window_is_not_taken(self):
        from custom_components.givenergy_inverter_manager.core.wizard_tariff import (
            default_rate_rows,
        )

        rows = default_rate_rows(2, [], ("23:00", "07:00"), night_rate=0.14)

        assert [r["rate"] for r in rows] == [0.14, None]
        assert (rows[0]["start"], rows[0]["end"]) == ("23:00:00", "07:00:00")

    def test_a_saved_first_row_keeps_its_own_rate(self):
        from custom_components.givenergy_inverter_manager.core.wizard_tariff import (
            default_rate_rows,
        )

        saved = [{"name": "Night", "rate": 0.2, "start": "00:00", "end": "05:00"}]

        assert default_rate_rows(1, saved, ("23:00", "07:00"), night_rate=0.14)[0]["rate"] == 0.2
