"""The battery, forecast, hot water and EV pages, and the inverter wiring."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from custom_components.givenergy_inverter_manager.core.wizard_model import Mode, PageContext
from custom_components.givenergy_inverter_manager.core.wizard_pages import (
    alt_heat_label_errors,
    battery_summary,
    charge_planning_summary,
    clean_battery,
    clean_charge_planning,
    clean_ev,
    clean_forecast,
    clean_hot_water,
    ev_summary,
    flatten_sections,
    forecast_summary,
    hot_water_summary,
    missing_wiring,
    sensor_check,
    unavailable_wiring,
    validate_charge_planning,
    validate_forecast,
    validate_hot_water,
)


def _state(value: str, unit: str | None = "kWh") -> SimpleNamespace:
    return SimpleNamespace(state=value, attributes={"unit_of_measurement": unit} if unit else {})


def _ctx(states=None, current=None) -> PageContext:
    return PageContext(Mode.OPTIONS, date(2031, 6, 15), states=states or {}, current=current or {})


class TestFlatten:
    def test_sections_are_merged_one_level_deep(self):
        flat = flatten_sections(
            {
                "base_rate": 0.3,
                "bill_details": {"vat_rate": 9.0},
                "alt_heat": {"alt_heat_enabled": True},
                "other": {"kept": "as a dict"},
            }
        )

        assert flat == {
            "base_rate": 0.3,
            "vat_rate": 9.0,
            "alt_heat_enabled": True,
            "other": {"kept": "as a dict"},
        }


class TestWiring:
    FIVE = {
        "solar_power_entity": "sensor.pv",
        "battery_soc_entity": "sensor.soc",
        "battery_power_entity": "sensor.bp",
        "grid_power_entity": "sensor.grid",
        "house_load_entity": "sensor.load",
    }

    def test_all_five_are_needed(self):
        assert missing_wiring(self.FIVE) == {}
        assert missing_wiring({**self.FIVE, "grid_power_entity": ""}) == {"base": "missing_entities"}
        assert missing_wiring({}) == {"base": "missing_entities"}

    def test_each_must_exist_and_not_read_unavailable(self):
        states = {entity: _state("1") for entity in self.FIVE.values()}
        assert unavailable_wiring(self.FIVE, states) == {}

        states["sensor.grid"] = _state("unavailable")
        assert unavailable_wiring(self.FIVE, states) == {"base": "missing_entities"}
        del states["sensor.grid"]
        assert unavailable_wiring(self.FIVE, states) == {"base": "missing_entities"}


class TestBattery:
    def test_the_values_are_numbers_and_only_what_was_sent_is_stored(self):
        cleaned = clean_battery(
            {
                "battery_capacity_kwh": "13.5",
                "inverter_max_output_kw": 3.6,
                "battery_cost_eur": 4500,
                "battery_throughput_budget_kwh": 0,
            }
        )

        assert cleaned == {
            "battery_capacity_kwh": 13.5,
            "inverter_max_output_kw": 3.6,
            "battery_cost_eur": 4500.0,
            "battery_throughput_budget_kwh": 0.0,
            "battery_capacity_entity": "",
            "inverter_max_output_entity": "",
        }
        assert clean_battery({"battery_capacity_kwh": 12}) == {
            "battery_capacity_kwh": 12.0,
            "battery_capacity_entity": "",
            "inverter_max_output_entity": "",
        }
        assert clean_battery({}) == {}

    def test_the_chosen_sensors_are_kept_and_a_cleared_one_is_stored_empty(self):
        cleaned = clean_battery(
            {
                "battery_capacity_kwh": 10,
                "inverter_max_output_kw": 5,
                "battery_capacity_entity": "sensor.cap",
            }
        )

        assert cleaned["battery_capacity_entity"] == "sensor.cap"
        assert cleaned["inverter_max_output_entity"] == ""

    def test_the_battery_page_no_longer_stores_the_charge_planning_values(self):
        assert clean_battery({"battery_min_soc_pct": 12, "overnight_charge_target_pct": 90}) == {}


class TestChargePlanning:
    def test_the_values_are_numbers_and_only_what_was_sent_is_stored(self):
        cleaned = clean_charge_planning(
            {"battery_min_soc_pct": 12.0, "overnight_charge_target_pct": 90}
        )

        assert cleaned == {"battery_min_soc_pct": 12, "overnight_charge_target_pct": 90}
        assert clean_charge_planning({"battery_min_soc_pct": 12}) == {"battery_min_soc_pct": 12}
        assert clean_charge_planning({}) == {}

    def test_the_seasons_are_sorted_months_and_a_bool(self):
        cleaned = clean_charge_planning(
            {
                "charge_winter_months": ["12", "1", "2"],
                "charge_shoulder_months": ["4", "3"],
                "charge_winter_uses_forecast": 1,
            }
        )
        assert cleaned == {
            "charge_winter_months": [1, 2, 12],
            "charge_shoulder_months": [3, 4],
            "charge_winter_uses_forecast": True,
        }

    def test_a_month_in_both_lists_is_an_error(self):
        result = validate_charge_planning(
            {"charge_winter_months": ["1"], "charge_shoulder_months": ["1", "2"]}, _ctx()
        )
        assert result.errors == {"base": "season_months_overlap"}

    def test_the_summary_names_the_minimum_and_the_cap(self):
        assert (
            charge_planning_summary(
                {"battery_min_soc_pct": 12, "overnight_charge_target_pct": 90}
            )
            == "minimum charge 12%, overnight cap 90%"
        )

    def test_a_floor_below_the_new_minimum_warns_but_never_blocks(self):
        result = validate_charge_planning({"battery_min_soc_pct": 20}, _ctx(current={"cheap_rate_floor_soc": 15}))

        assert result.errors == {}
        assert len(result.warnings) == 1
        assert "Cheap rate floor SoC" in result.warnings[0]

    def test_a_floor_of_zero_is_off_and_never_warns(self):
        result = validate_charge_planning({"battery_min_soc_pct": 20}, _ctx(current={"cheap_rate_floor_soc": 0}))

        assert result.warnings == ()

    def test_the_default_floor_is_checked_when_none_is_saved(self):
        assert validate_charge_planning({"battery_min_soc_pct": 30}, _ctx()).warnings == ()
        assert validate_charge_planning({"battery_min_soc_pct": 45}, _ctx()).warnings != ()

    def test_the_summary_names_the_capacity_and_the_inverter(self):
        assert (
            battery_summary({"battery_capacity_kwh": 9.5, "inverter_max_output_kw": 5.0})
            == "battery 9.5 kWh, inverter 5 kW"
        )


class TestForecast:
    def test_a_sensor_left_out_was_cleared_and_is_stored_empty(self):
        assert clean_forecast({"forecast_entity": "sensor.f"}) == {
            "forecast_entity": "sensor.f",
            "forecast_entity_p10": "",
            "forecast_entity_d2": "",
            "carbon_intensity_entity": "",
        }

    def test_a_sensor_reading_kwh_or_wh_is_fine(self):
        states = {"sensor.f": _state("14.2", "kWh"), "sensor.p": _state("9800", "Wh")}
        values = {"forecast_entity": "sensor.f", "forecast_entity_p10": "sensor.p"}

        assert validate_forecast(values, _ctx(states)).warnings == ()

    @pytest.mark.parametrize(
        "state", [_state("14.2", "W"), _state("lots", "kWh"), _state("14.2", None)]
    )
    def test_a_sensor_that_does_not_read_a_number_in_energy_units_warns(self, state):
        result = validate_forecast({"forecast_entity": "sensor.f"}, _ctx({"sensor.f": state}))

        assert result.errors == {}
        assert "sensor.f" in result.warnings[0]

    def test_a_missing_or_unavailable_sensor_is_not_judged(self):
        states = {"sensor.u": _state("unavailable")}
        values = {"forecast_entity": "sensor.gone", "forecast_entity_d2": "sensor.u"}

        assert validate_forecast(values, _ctx(states)).warnings == ()

    def test_the_carbon_sensor_is_not_an_energy_sensor(self):
        states = {"sensor.c": _state("187", "g/kWh")}

        assert validate_forecast({"carbon_intensity_entity": "sensor.c"}, _ctx(states)).warnings == ()

    def test_the_read_only_check_says_what_each_sensor_reads(self):
        states = {"sensor.f": _state("14.2", "kWh"), "sensor.u": _state("unavailable")}

        assert sensor_check("sensor.f", states) == "sensor.f reads 14.2 kWh."
        assert sensor_check("sensor.u", states) == "sensor.u is unavailable at the moment."
        assert sensor_check("sensor.x", states) == "sensor.x does not exist."
        assert sensor_check("sensor.f", {"sensor.f": _state("3", None)}) == "sensor.f reads 3."

    def test_the_summary(self):
        assert forecast_summary({"forecast_entity": "sensor.f"}) == "forecast sensor: sensor.f"
        assert "seasonal estimate" in forecast_summary({})


class TestHotWater:
    ALT = {
        "alt_heat_enabled": True,
        "alt_heat_label": "  Heat   pump ",
        "alt_heat_cost_unit": "kwh_heat",
        "alt_heat_cost": 0.08,
        "alt_heat_cost_entity": "sensor.gas",
    }

    def test_everything_is_cleaned(self):
        cleaned = clean_hot_water(
            {
                "immersion_switch_entity": "switch.heater",
                "immersion_temp_sensor_entity": "sensor.cylinder",
                "immersion_wattage_w": 2800,
                "immersion_ready_times": ["18:00", "07:00", "07:00:00"],
                **self.ALT,
            }
        )

        assert cleaned == {
            "immersion_switch_entity": "switch.heater",
            "immersion_temp_sensor_entity": "sensor.cylinder",
            "immersion_wattage_w": 2800.0,
            "immersion_ready_times": ["07:00", "18:00"],
            "alt_heat_enabled": True,
            "alt_heat_label": "Heat pump",
            "alt_heat_cost_unit": "kwh_heat",
            "alt_heat_cost": 0.08,
            "alt_heat_cost_entity": "sensor.gas",
        }

    def test_what_the_user_cleared_is_stored_empty(self):
        cleaned = clean_hot_water({"alt_heat_enabled": True})

        assert cleaned["immersion_switch_entity"] == ""
        assert cleaned["immersion_temp_sensor_entity"] == ""
        assert cleaned["immersion_ready_times"] == []
        assert cleaned["alt_heat_cost"] == ""
        assert cleaned["alt_heat_cost_entity"] == ""
        assert "immersion_wattage_w" not in cleaned

    def test_a_label_the_form_did_not_send_is_left_alone(self):
        assert "alt_heat_label" not in clean_hot_water({})

    def test_a_submission_without_the_alternative_heating_section_leaves_it_alone(self):
        cleaned = clean_hot_water({"immersion_switch_entity": "switch.h"})

        assert not {k for k in cleaned if k.startswith("alt_heat")}

    @pytest.mark.parametrize(
        ("label", "error"),
        [
            ("", "alt_heat_label_empty"),
            ("   ", "alt_heat_label_empty"),
            (None, "alt_heat_label_empty"),
            ("x" * 21, "alt_heat_label_too_long"),
            ("x" * 500, "alt_heat_label_too_long"),
        ],
    )
    def test_a_bad_label_is_refused_while_the_setting_is_on(self, label, error):
        values = {"alt_heat_enabled": True, "alt_heat_label": label}

        assert alt_heat_label_errors(values) == {"base": error}
        assert validate_hot_water(values, _ctx()).errors == {"base": error}

    @pytest.mark.parametrize("label", ["Oil", "Heat pump", "x" * 20, "  y  "])
    def test_a_good_label_is_accepted(self, label):
        assert alt_heat_label_errors({"alt_heat_enabled": True, "alt_heat_label": label}) == {}

    def test_the_label_is_not_checked_while_off_or_not_sent(self):
        assert alt_heat_label_errors({"alt_heat_enabled": False, "alt_heat_label": ""}) == {}
        assert alt_heat_label_errors({"alt_heat_enabled": True}) == {}
        assert alt_heat_label_errors({}) == {}

    def test_a_ready_time_that_does_not_parse_is_an_error(self):
        result = validate_hot_water({"immersion_ready_times": ["07:00", "seven"]}, _ctx())

        assert result.errors == {"base": "immersion_ready_time_invalid"}

    def test_ready_times_without_a_temperature_sensor_warn(self):
        result = validate_hot_water({"immersion_ready_times": ["07:00"]}, _ctx())
        assert "temperature sensor" in result.warnings[0]
        with_sensor = {"immersion_ready_times": ["07:00"], "immersion_temp_sensor_entity": "sensor.t"}
        assert validate_hot_water(with_sensor, _ctx()).warnings == ()

    def test_more_than_four_ready_times_warn(self):
        times = [f"0{n}:00" for n in range(5)]
        values = {"immersion_ready_times": times, "immersion_temp_sensor_entity": "sensor.t"}

        assert "5 ready-by times" in validate_hot_water(values, _ctx()).warnings[0]

    def test_alternative_heating_needs_a_switch_and_a_cost_to_give_advice(self):
        result = validate_hot_water({"alt_heat_enabled": True}, _ctx())

        assert result.errors == {}
        assert len(result.warnings) == 2
        assert "immersion switch" in result.warnings[0]
        assert "cost" in result.warnings[1]

    def test_a_complete_alternative_heating_setup_has_nothing_to_warn_about(self):
        values = {"alt_heat_enabled": True, "immersion_switch_entity": "switch.h", "alt_heat_cost": 0.9}

        assert validate_hot_water(values, _ctx()).warnings == ()
        sensor_cost = {"alt_heat_enabled": True, "immersion_switch_entity": "switch.h"}
        sensor_cost["alt_heat_cost_entity"] = "sensor.c"
        assert validate_hot_water(sensor_cost, _ctx()).warnings == ()

    def test_nothing_to_warn_about_when_alternative_heating_is_off(self):
        assert validate_hot_water({"alt_heat_enabled": False}, _ctx()).warnings == ()

    def test_the_summary(self):
        assert hot_water_summary({}) == "no immersion switch"
        line = hot_water_summary(
            {"immersion_switch_entity": "switch.h", "alt_heat_enabled": True, "alt_heat_label": "Gas"}
        )
        assert line == "immersion switch switch.h, alternative heating: Gas"


class TestEv:
    def test_the_efficiency_is_a_number_and_only_stored_when_sent(self):
        assert clean_ev({"car_efficiency_kwh_per_100km": "17.5"}) == {
            "car_efficiency_kwh_per_100km": 17.5
        }
        assert clean_ev({}) == {}

    def test_the_summary_falls_back_to_the_default(self):
        assert ev_summary({}) == "car efficiency 15 kWh per 100 km"
        assert ev_summary({"car_efficiency_kwh_per_100km": 17.5}) == "car efficiency 17.5 kWh per 100 km"
