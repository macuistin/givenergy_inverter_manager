"""The words and values of the "choose a tariff from the list" screens."""

from __future__ import annotations

from datetime import date, time

from custom_components.givenergy_inverter_manager.core.wizard_store import (
    choose_tariff,
    country_choices,
    default_country,
    review_text,
    source_options,
    source_record,
    source_text,
)
from custom_components.givenergy_inverter_manager.lib.tariff import (
    Locale,
    TariffConfig,
    definition_from_config,
)
from custom_components.givenergy_inverter_manager.lib.tariff.periods import RatePeriod

LOCALE = Locale("EUR", "IE", "Europe/Dublin", date(2026, 1, 1))


def _definition(**changes: object):  # noqa: ANN202
    values = {
        "rate_periods": [RatePeriod("Night", 0.18, time(23), time(8))],
        "base_rate": 0.365,
        "base_rate_name": "Day",
        "export_rate": 0.195,
        "standing_charge": 0.8259,
        "pso_levy": 1.46,
        "vat_rate": 9.0,
        "discount_rate": 5.5,
        "bill_start_day": 1,
    }
    values.update(changes)
    return definition_from_config(TariffConfig(**values), LOCALE)  # type: ignore[arg-type]


def test_only_countries_with_tariffs_are_offered_and_a_partial_one_says_so() -> None:
    choices = country_choices(
        {
            "IE": {"availability": "available"},
            "GB": {"availability": "partial", "reason": "some suppliers"},
            "XX": {"availability": "unavailable"},
            "ZZ": {"availability": "available"},
        }
    )
    assert choices == {
        "GB": "United Kingdom (some suppliers only)",
        "IE": "Ireland",
        "ZZ": "ZZ",
    }


def test_the_home_country_is_the_default_when_the_store_holds_it() -> None:
    choices = {"GB": "United Kingdom", "IE": "Ireland"}
    assert default_country(choices, "ie") == "IE"
    assert default_country(choices, "FR") == "GB"
    assert default_country(choices, None) == "GB"
    assert default_country({}, "IE") is None


def test_a_tariff_the_options_can_hold_becomes_options_with_the_bill_start_day() -> None:
    choice = choose_tariff(_definition(), 16)
    assert choice.usable
    assert choice.options["bill_start_day"] == 16
    assert choice.options["base_rate"] == 0.365


def test_a_tariff_the_options_cannot_hold_gives_its_reasons() -> None:
    off_grid = _definition(rate_periods=[RatePeriod("Night", 0.18, time(23, 10), time(8))])
    choice = choose_tariff(off_grid, 1)
    assert not choice.usable
    assert any("half hours" in reason for reason in choice.reasons)
    assert choice.options == {}


def test_the_source_record_and_options_carry_where_the_tariff_came_from() -> None:
    definition = _definition()
    picked = {"country": "IE", "provider": "p", "tariff": "t", "area": "all"}
    record = source_record(picked, definition)
    assert record == {
        "kind": "store",
        "country": "IE",
        "provider": "p",
        "tariff": "t",
        "area": "all",
        "name": definition.name,
        "provider_name": definition.provider.name,
        "effective_from": "2026-01-01",
        "auto_update": True,
    }
    options = source_options(record, choose_tariff(definition, 1))
    assert options["tariff_source"] == record
    assert options["vat_rate"] == 9.0


def test_the_review_reads_like_a_bill() -> None:
    definition = _definition()
    text = review_text(definition, choose_tariff(definition, 1))
    assert "- Day: 0.365 EUR per kWh" in text
    assert "- Night: 0.18 EUR per kWh, 23:00 to 08:00" in text
    assert "- Standing charge: 0.8259 EUR per day" in text
    assert "- Levy: 1.46 EUR per billing period" in text
    assert "- Discount: 5.5% off the energy charge" in text
    assert "- VAT: 9%, added to the prices" in text
    assert "Prices in force from 1 January 2026, as published." in text
    assert "Check them against your bill." in text


def test_the_review_of_a_tariff_that_cannot_be_used_says_why_and_what_to_do() -> None:
    definition = _definition(rate_periods=[RatePeriod("Night", 0.18, time(23, 10), time(8))])
    text = review_text(definition, choose_tariff(definition, 1))
    assert "cannot be used as your tariff yet" in text
    assert "- a timed rate starts or ends between half hours" in text
    assert "Enter it myself" in text


def test_the_source_is_described_for_each_kind() -> None:
    record = {
        "kind": "store",
        "provider_name": "P Energy",
        "name": "Plan",
        "effective_from": "2026-01-01",
        "auto_update": True,
    }
    assert source_text(None) == "Entered by hand"
    assert source_text({"kind": "other"}) == "Entered by hand"
    assert source_text(record) == "P Energy Plan, prices from 2026-01-01, from the store"
    assert source_text({**record, "kind": "based_on"}) == (
        "P Energy Plan, prices from 2026-01-01, then edited by hand"
    )
