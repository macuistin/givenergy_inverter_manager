"""The reload table: what saving each config key needs.

The expected effect of every key is written out here from the settings reference in the
design brief and the audit of where the coordinator reads each key. The key list comes from
const.py and from the forms in the config flow golden, never from the policy module, so a
new option fails these tests until someone places it on purpose.
"""

from __future__ import annotations

import json

import pytest

from custom_components.givenergy_inverter_manager import const
from custom_components.givenergy_inverter_manager.core.reload_policy import (
    Effect,
    change_effect,
    changed_keys,
)
from tests.helpers import ROOT

RELOAD = Effect.RELOAD
LIVE = Effect.LIVE

# key: (old value, new value, effect of the change). Both values are set, so a key that
# decides a device by presence is covered separately below.
KEY_TABLE: dict[str, tuple[object, object, Effect]] = {
    # Wiring: the inverter serial and the eleven entity IDs.
    "inverter_serial": ("ab1", "cd2", RELOAD),
    "solar_power_entity": ("sensor.a", "sensor.b", RELOAD),
    "battery_soc_entity": ("sensor.a", "sensor.b", RELOAD),
    "battery_power_entity": ("sensor.a", "sensor.b", RELOAD),
    "grid_power_entity": ("sensor.a", "sensor.b", RELOAD),
    "house_load_entity": ("sensor.a", "sensor.b", RELOAD),
    "inverter_temp_entity": ("sensor.a", "sensor.b", RELOAD),
    "target_soc_entity": ("number.a", "number.b", RELOAD),
    "enable_charge_target_entity": ("switch.a", "switch.b", RELOAD),
    "enable_charge_schedule_entity": ("switch.a", "switch.b", RELOAD),
    "charge_start_time_entity": ("select.a", "select.b", RELOAD),
    "charge_end_time_entity": ("select.a", "select.b", RELOAD),
    # The optional device set.
    "immersion_switch_entity": ("switch.a", "switch.b", RELOAD),
    "immersion_temp_sensor_entity": ("sensor.a", "sensor.b", RELOAD),
    # Read once at setup: forecast history seeding, the unit of every money sensor.
    "forecast_entity": ("sensor.a", "sensor.b", RELOAD),
    "currency": ("EUR", "GBP", RELOAD),
    # Tariff.
    "base_rate": (0.30, 0.31, LIVE),
    "base_rate_name": ("Day", "Standard", LIVE),
    "export_rate": (0.19, 0.20, LIVE),
    "rate_periods": (
        [{"name": "Night", "rate": 0.15, "start": "23:00", "end": "08:00"}],
        [{"name": "Night", "rate": 0.15, "start": "00:00", "end": "07:00"}],
        LIVE,
    ),
    "standing_charge_per_day": (0.8, 0.9, LIVE),
    "pso_levy_per_month": (1.4, 1.5, LIVE),
    "vat_rate": (9.0, 13.5, LIVE),
    "discount_rate": (5.5, 6.0, LIVE),
    "bill_start_day": (1, 16, LIVE),
    "tariff_changes": (
        [],
        [{"effective": "2027-01-01", "base_rate": 0.3, "base_rate_name": "Day",
          "export_rate": 0.2, "rate_periods": []}],
        LIVE,
    ),
    "tariff_reviewed_on": ("2026-01-01", "2026-06-01", LIVE),
    # Battery and charging.
    "battery_capacity_kwh": (9.5, 10.0, LIVE),
    "inverter_max_output_kw": (5.0, 3.6, LIVE),
    "battery_min_soc_pct": (10, 15, LIVE),
    "overnight_charge_target_pct": (80, 90, LIVE),
    "battery_cost_eur": (0.0, 5000.0, LIVE),
    "battery_throughput_budget_kwh": (0.0, 12.5, LIVE),
    "charge_winter_months": ([12, 1, 2], [11, 12, 1, 2], LIVE),
    "charge_shoulder_months": ([3, 4, 10, 11], [3, 4], LIVE),
    "charge_winter_uses_forecast": (False, True, LIVE),
    # Forecast.
    "forecast_provider": ("solcast", "forecast_solar", LIVE),
    "forecast_entity_p10": ("sensor.a", "sensor.b", LIVE),
    "forecast_entity_d2": ("sensor.a", "sensor.b", LIVE),
    "carbon_intensity_entity": ("sensor.a", "sensor.b", LIVE),
    # Hot water and EV.
    "immersion_wattage_w": (3000, 2000, LIVE),
    "immersion_ready_times": (["07:00"], ["07:00", "18:00"], LIVE),
    "immersion_target_temp_c": (55, 60, LIVE),
    "immersion_min_temp_c": (50, 45, LIVE),
    "immersion_hysteresis_c": (5, 8, LIVE),
    "car_efficiency_kwh_per_100km": (15.0, 18.0, LIVE),
    # Controls.
    "dry_run": (False, True, LIVE),
    "verbose_logging": (False, True, LIVE),
    "charge_replan": (False, True, LIVE),
    "surplus_divert_soc_pct": (80, 85, LIVE),
    "surplus_divert_min_power_w": (500, 600, LIVE),
    "cheap_rate_floor_soc": (40, 45, LIVE),
    "skip_charge_soc_threshold_pct": (75, 80, LIVE),
    "forecast_conservatism": (0.35, 0.4, LIVE),
    # The URL path of the dashboard setup found. It is written once, before the update listener
    # exists, and no cycle reads it.
    "dashboard_url_path": ("givenergy", "lovelace", LIVE),
    # Alternative heating. The coordinator reads the label, the unit, the cost and the cost
    # sensor every cycle, so a new value is live while the advice device stays as it is. The
    # device appears and goes with the setting, the cost and the cost sensor: tests below.
    "alt_heat_enabled": (True, False, LIVE),
    "alt_heat_label": ("Oil", "Gas", LIVE),
    "alt_heat_cost_unit": ("litre", "kwh_heat", LIVE),
    "alt_heat_cost": (0.9, 1.1, LIVE),
    "alt_heat_cost_entity": ("sensor.a", "sensor.b", LIVE),
}

# Names in the forms that are not stored under their own key: the checklist, the rate count and
# the tick boxes of the tariff screen, the inverter picker and the entity-source choice, the date
# and cancel box of a dated change, and the fields inside a rate row.
FORM_ONLY_NAMES = {
    "pages",
    "next_step_id",
    "rate_count",
    "discovered_inverter",
    "source",
    "effective_from",
    "cancel_scheduled",
    "name",
    "rate",
    "start",
    "end",
}


def _conf_values() -> set[str]:
    return {value for name, value in vars(const).items() if name.startswith("CONF_")}


def _golden_form_fields() -> set[str]:
    """Every field name in the setup, reconfigure and options forms, sections excluded."""
    golden = json.loads((ROOT / "tests/ha_e2e/golden/config_flow_forms.json").read_text())
    names: set[str] = set()

    def walk(fields: list[dict]) -> None:
        for field in fields:
            if field.get("type") == "expandable":
                walk(field["schema"])
            else:
                names.add(field["name"])

    for form in golden.values():
        walk(form["fields"])
    return names


def test_every_config_key_has_a_row_in_the_table():
    assert set(KEY_TABLE) == _conf_values()


def test_every_stored_form_field_has_a_row_in_the_table():
    assert _golden_form_fields() - FORM_ONLY_NAMES <= set(KEY_TABLE)


@pytest.mark.parametrize("key", sorted(KEY_TABLE))
def test_changing_one_key(key):
    old, new, effect = KEY_TABLE[key]

    assert change_effect({key: old}, {key: new}) is effect
    assert change_effect({key: new}, {key: old}) is effect


@pytest.mark.parametrize("key", sorted(KEY_TABLE))
def test_saving_an_unchanged_key_does_nothing(key):
    old, _new, _effect = KEY_TABLE[key]

    assert change_effect({key: old}, {key: old}) is Effect.NONE


ON = {"alt_heat_enabled": True}
COST = {"alt_heat_cost": 0.95}
SENSOR = {"alt_heat_cost_entity": "sensor.heat_cost"}


class TestTheAdviceDeviceAppearsAndGoes:
    """Alternative heating is a device while it is on and has a cost or a cost sensor."""

    @pytest.mark.parametrize("cost", [COST, SENSOR], ids=["cost", "sensor"])
    def test_turning_it_on_with_a_cost_reloads(self, cost):
        assert change_effect(cost, {**cost, **ON}) is RELOAD
        assert change_effect({**cost, **ON}, cost) is RELOAD
        assert change_effect({**cost, "alt_heat_enabled": False}, {**cost, **ON}) is RELOAD

    @pytest.mark.parametrize(
        ("key", "value"),
        [("alt_heat_cost", 0.95), ("alt_heat_cost_entity", "sensor.heat_cost")],
    )
    def test_setting_or_clearing_the_cost_while_on_reloads(self, key, value):
        assert change_effect(ON, {**ON, key: value}) is RELOAD
        assert change_effect({**ON, key: value}, ON) is RELOAD
        assert change_effect({**ON, key: value}, {**ON, key: ""}) is RELOAD
        assert change_effect({**ON, key: value}, {**ON, key: None}) is RELOAD

    @pytest.mark.parametrize(
        ("key", "value"),
        [("alt_heat_cost", 0.95), ("alt_heat_cost_entity", "sensor.heat_cost")],
    )
    def test_setting_or_clearing_the_cost_while_off_stays_live(self, key, value):
        assert change_effect({}, {key: value}) is LIVE
        assert change_effect({key: value}, {}) is LIVE

    def test_turning_it_on_with_no_cost_is_live(self):
        assert change_effect({}, ON) is LIVE
        assert change_effect(ON, {}) is LIVE

    def test_a_zero_cost_is_not_a_cost(self):
        assert change_effect({**ON, "alt_heat_cost": 0.0}, {**ON, "alt_heat_cost": 0.95}) is RELOAD
        assert change_effect({**ON, "alt_heat_cost": 0.0}, ON) is LIVE

    def test_a_new_cost_while_on_stays_live(self):
        assert change_effect({**ON, **COST}, {**ON, "alt_heat_cost": 1.2}) is LIVE

    def test_swapping_the_cost_for_the_cost_sensor_stays_live(self):
        both = {**COST, **SENSOR}
        assert change_effect({**ON, **COST}, {**ON, **SENSOR}) is LIVE
        assert change_effect({**ON, **COST}, {**ON, **both}) is LIVE
        assert change_effect({**ON, **both}, {**ON, **SENSOR}) is LIVE

    def test_a_new_label_or_unit_while_on_stays_live(self):
        base = {**ON, **COST, "alt_heat_label": "Oil", "alt_heat_cost_unit": "litre"}
        assert change_effect(base, {**base, "alt_heat_label": "Gas"}) is LIVE
        assert change_effect(base, {**base, "alt_heat_cost_unit": "kwh_heat"}) is LIVE

    def test_the_cost_and_the_setting_changing_together_reload_once(self):
        assert change_effect({}, {**ON, **COST}) is RELOAD
        assert change_effect({**ON, **COST}, {}) is RELOAD


def test_a_key_the_policy_does_not_know_reloads():
    assert change_effect({"brand_new_option": 1}, {"brand_new_option": 2}) is RELOAD


def test_an_empty_string_and_a_missing_key_are_the_same_value():
    assert change_effect({}, {"immersion_switch_entity": ""}) is Effect.NONE
    assert change_effect({"immersion_switch_entity": None}, {}) is Effect.NONE


def test_a_whole_number_and_the_same_float_are_the_same_value():
    assert change_effect({"battery_min_soc_pct": 10}, {"battery_min_soc_pct": 10.0}) is Effect.NONE


def test_live_changes_together_stay_live():
    old = {"dry_run": False, "surplus_divert_soc_pct": 80, "base_rate": 0.3}
    new = {"dry_run": True, "surplus_divert_soc_pct": 85, "base_rate": 0.31}

    assert change_effect(old, new) is LIVE


def test_one_reload_key_among_live_changes_reloads():
    old = {"dry_run": False, "immersion_switch_entity": "switch.a"}
    new = {"dry_run": True, "immersion_switch_entity": "switch.b"}

    assert change_effect(old, new) is RELOAD


def test_changed_keys_lists_only_the_keys_that_differ():
    old = {"dry_run": False, "base_rate": 0.3, "removed": 1}
    new = {"dry_run": True, "base_rate": 0.3, "added": 2}

    assert changed_keys(old, new) == {"dry_run", "removed", "added"}
