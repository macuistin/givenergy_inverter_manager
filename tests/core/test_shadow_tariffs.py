"""The shadow tariffs as the options store them: the limit, names and the tariff they build."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.const import MAX_SHADOW_TARIFFS
from custom_components.givenergy_inverter_manager.core.shadow_tariffs import (
    name_error,
    shadow_config,
    shadow_entries,
    shadow_summary,
    with_shadow,
    without_shadow,
)
from custom_components.givenergy_inverter_manager.core.tariff import build_tariff
from custom_components.givenergy_inverter_manager.wizard.shadow_form import (
    entry_from_form,
    starting_entry,
    validate_rows,
)

ACTIVE = {
    "base_rate": 0.365,
    "base_rate_name": "Day",
    "export_rate": 0.195,
    "rate_periods": [{"name": "Night", "rate": 0.18, "start": "23:00", "end": "08:00"}],
    "standing_charge_per_day": 0.8259,
    "pso_levy_per_month": 1.46,
    "vat_rate": 9.0,
    "discount_rate": 5.5,
    "bill_start_day": 16,
}


def shadow(name: str, **changes):  # type: ignore[no-untyped-def]
    return {"name": name, **starting_entry(ACTIVE), **changes}


def test_the_limit_is_three() -> None:
    assert MAX_SHADOW_TARIFFS == 3


def test_a_new_shadow_starts_at_the_active_tariff() -> None:
    start = starting_entry(ACTIVE)
    assert start["base_rate"] == 0.365
    assert start["rate_periods"] == ACTIVE["rate_periods"]
    assert "bill_start_day" not in start
    assert "base_rate_name" not in start


def test_a_shadow_is_built_on_the_active_bill_dates_and_base_rate_name() -> None:
    tariff = build_tariff(
        shadow_config(shadow("Cheap", base_rate=0.30, standing_charge_per_day=0.5), ACTIVE)
    )
    assert tariff.base_rate == 0.30
    assert tariff.standing_charge == 0.5
    assert tariff.base_rate_name == "Day"
    assert tariff.bill_start_day == 16


def test_adding_up_to_the_limit_then_refusing() -> None:
    saved: list = []
    for index in range(MAX_SHADOW_TARIFFS):
        saved = with_shadow(saved, shadow(f"Tariff {index}"))
    assert [e["name"] for e in saved] == ["Tariff 0", "Tariff 1", "Tariff 2"]
    assert name_error(saved, "Another") == "shadow_limit"
    with pytest.raises(ValueError, match="shadow_limit"):
        with_shadow(saved, shadow("Another"))


def test_names_are_needed_and_differ_ignoring_case() -> None:
    saved = [shadow("Night saver")]
    assert name_error(saved, "  ") == "shadow_name_missing"
    assert name_error(saved, "NIGHT SAVER") == "shadow_name_duplicate"
    assert name_error(saved, "Flat") is None


def test_removing_by_name() -> None:
    saved = [shadow("A"), shadow("B")]
    assert [e["name"] for e in without_shadow(saved, "A")] == ["B"]
    assert without_shadow(saved, "missing") == saved


def test_unreadable_entries_are_skipped_and_the_list_is_capped() -> None:
    raw = [shadow("A"), {"name": "no fields"}, "text", shadow(""), *[shadow(f"X{i}") for i in range(5)]]
    names = [e["name"] for e in shadow_entries(raw)]
    assert names == ["A", "X0", "X1"]
    assert shadow_entries(None) == []
    assert shadow_entries("a") == []


def test_the_summary_for_the_menu() -> None:
    assert shadow_summary([]) == "None set up"
    assert shadow_summary([shadow("A"), shadow("B")]) == "2 of 3: A, B"


def test_a_form_becomes_a_stored_tariff() -> None:
    flat = {
        "shadow_name": " Flat ",
        "base_rate": "0.25",
        "export_rate": 0.1,
        "standing_charge_per_day": 0.5,
        "pso_levy_per_month": 0,
        "vat_rate": 9,
        "discount_rate": 0,
    }
    entry = entry_from_form(flat, [])
    assert entry["name"] == "Flat"
    assert entry["base_rate"] == 0.25
    assert with_shadow([], entry)[0]["rate_periods"] == []


def test_timed_rates_must_not_repeat_the_active_base_rate_name() -> None:
    rows = [{"name": "day", "rate": 0.1, "start": "00:00", "end": "06:00"}]
    assert validate_rows(rows, ACTIVE).errors == {"base": "rate_period_duplicate_name"}
    assert validate_rows([{**rows[0], "name": "Night"}], ACTIVE).errors == {}
