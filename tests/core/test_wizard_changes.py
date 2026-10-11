"""The words of the options confirm step: before and after, and whether it reloads."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.core import reload_policy
from custom_components.givenergy_inverter_manager.core.wizard_changes import (
    LABELS,
    confirm_text,
    describe_changes,
    effect_line,
    show,
)
from custom_components.givenergy_inverter_manager.core.wizard_model import PAGE_KEYS


def test_every_page_key_has_a_label_a_person_can_read():
    owned = {key for keys in PAGE_KEYS.values() for key in keys}

    assert owned <= set(LABELS)


def test_a_changed_number_reads_before_and_after_with_its_unit():
    lines = describe_changes(
        {"battery_capacity_kwh": 9.5, "battery_min_soc_pct": 10},
        {"battery_capacity_kwh": 13.5, "battery_min_soc_pct": 10},
    )

    assert lines == ["Battery capacity: 9.5 kWh to 13.5 kWh"]


def test_an_unset_value_is_shown_as_what_the_engine_uses():
    assert describe_changes({}, {"alt_heat_label": "Gas"}) == ["Alternative heating name: Oil to Gas"]


def test_a_cleared_entity_reads_as_not_set():
    lines = describe_changes({"forecast_entity": "sensor.f"}, {"forecast_entity": ""})

    assert lines == ["Forecast sensor: sensor.f to not set"]


def test_a_switch_reads_on_or_off():
    assert describe_changes({"alt_heat_enabled": False}, {"alt_heat_enabled": True}) == [
        "Alternative water heating: off to on"
    ]


def test_rate_rows_and_dated_changes_read_in_words():
    night = {"name": "Night", "rate": 0.15, "start": "23:00", "end": "08:00"}

    lines = describe_changes(
        {"rate_periods": []},
        {"rate_periods": [night], "tariff_changes": [{"effective": "2031-09-01"}]},
    )

    assert "Scheduled rate changes (start dates): none to 2031-09-01" in lines
    assert "Time-of-day rates: none to Night 0.1500 (23:00 to 08:00)" in lines


def test_a_ready_time_list_reads_as_a_list():
    assert show("immersion_ready_times", ["07:00", "18:00"]) == "07:00, 18:00"
    assert show("immersion_ready_times", []) == "not set"


def test_the_lines_come_in_a_stable_order():
    lines = describe_changes({}, {"export_rate": 0.1, "base_rate": 0.3})

    assert [line.split(":")[0] for line in lines] == ["Base rate", "Export rate"]


def test_a_live_change_says_it_applies_now():
    before, after = {"battery_min_soc_pct": 10}, {"battery_min_soc_pct": 12}

    assert effect_line(before, after) == "Applies now. The integration does not reload."


def test_a_device_change_says_why_it_reloads():
    line = effect_line({}, {"immersion_switch_entity": "switch.h", "battery_min_soc_pct": 12})

    assert line.startswith("Reloads the integration because you changed immersion switch.")
    assert "battery" not in line


def test_no_change_says_so():
    assert effect_line({"base_rate": 0.3}, {"base_rate": 0.3}) == "Nothing changes."
    assert confirm_text({"base_rate": 0.3}, {"base_rate": 0.3}) == (
        "No values changed.\n\nNothing changes."
    )


def test_the_confirm_text_lists_each_change_then_the_effect():
    text = confirm_text({"base_rate": 0.3}, {"base_rate": 0.32})

    assert text == "- Base rate: 0.3 to 0.32\n\nApplies now. The integration does not reload."


def test_reload_keys_names_only_the_keys_that_reload():
    old = {"immersion_switch_entity": "", "battery_min_soc_pct": 10, "currency": "EUR"}
    new = {"immersion_switch_entity": "switch.h", "battery_min_soc_pct": 12, "currency": "GBP"}

    assert reload_policy.reload_keys(old, new) == {"immersion_switch_entity", "currency"}
    assert reload_policy.reload_keys(old, old) == frozenset()


def test_the_setup_summary_says_dry_run_is_on():
    from custom_components.givenergy_inverter_manager.core.wizard_changes import setup_summary

    text = setup_summary({}, None, tariff_asked=False)

    assert "Dry run is on. Nothing is sent to your inverter, immersion or EV charger" in text


def test_the_setup_summary_says_when_the_tariff_was_left_for_later():
    from custom_components.givenergy_inverter_manager.core.wizard_changes import setup_summary

    text = setup_summary({}, None, tariff_asked=False)

    assert "Tariff: not set yet." in text
    assert "placeholder rate" in text
    assert "Cheapest rate" not in text


def test_the_setup_summary_lists_the_tariff_the_charger_and_the_sensors():
    from custom_components.givenergy_inverter_manager.core.wizard_changes import setup_summary

    values = {
        "inverter_serial": "ab1",
        "base_rate": 0.3,
        "base_rate_name": "Day",
        "rate_periods": [{"name": "Night", "rate": 0.12, "start": "23:00", "end": "08:00"}],
        "battery_capacity_kwh": 9.5,
        "inverter_max_output_kw": 5.0,
        "forecast_entity": "sensor.f",
        "immersion_switch_entity": "switch.h",
    }

    text = setup_summary(values, "Zappi", tariff_asked=True)

    assert "- Inverter: ab1." in text
    assert "Cheapest rate in your saved tariff: Night at 0.1200 EUR/kWh, 23:00 to 08:00" in text
    assert "Base rate: Day 0.3000. Timed rates: Night 0.1200 (23:00 to 08:00)." in text
    assert "Battery 9.5 kWh, inverter 5 kW." in text
    assert "EV charger: Zappi." in text
    assert "Solar forecast sensor: sensor.f." in text
    assert "Hot water: immersion switch switch.h." in text
