"""The wizard page table: which keys a page owns, and what counts as a change."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager import const
from custom_components.givenergy_inverter_manager.core.wizard_model import (
    KEY_DEFAULTS,
    OPTION_PAGES,
    PAGE_KEYS,
    PAGE_STEPS,
    PAGE_WRITES,
    SETUP_PAGES,
    changed_values,
    same_value,
)

# The tuning controls and the immersion temperatures own their keys, so no page may ask for
# them: a setting has one home. Written out here, not read from controls.py, so a control that
# is added without a line here is noticed when the page table is next changed.
CONTROL_KEYS = {
    "dry_run",
    "verbose_logging",
    "charge_replan",
    "surplus_divert_soc_pct",
    "surplus_divert_min_power_w",
    "cheap_rate_floor_soc",
    "skip_charge_soc_threshold_pct",
    "forecast_conservatism",
    "immersion_target_temp_c",
    "immersion_min_temp_c",
    "immersion_hysteresis_c",
}
# Stored by an earlier version and never read, so no form offers it.
RETIRED_KEYS = {"forecast_provider", "oil_price_per_litre", "oil_price_entity"}


def _conf_values() -> set[str]:
    return {value for name, value in vars(const).items() if name.startswith("CONF_")}


def test_every_page_key_is_a_config_key():
    owned = {key for keys in PAGE_KEYS.values() for key in keys}

    assert owned <= _conf_values()


def test_no_key_is_owned_by_two_pages():
    owned = [key for keys in PAGE_KEYS.values() for key in keys]

    assert len(owned) == len(set(owned))


def test_no_page_owns_a_control_or_a_retired_key():
    owned = {key for keys in PAGE_KEYS.values() for key in keys}

    assert not owned & CONTROL_KEYS
    assert not owned & RETIRED_KEYS


def test_the_checklists_name_only_pages_that_exist():
    assert set(SETUP_PAGES) <= set(PAGE_KEYS)
    assert set(OPTION_PAGES) <= set(PAGE_KEYS)
    assert SETUP_PAGES == ("tariff", "forecast", "hot_water")
    assert OPTION_PAGES == ("tariff", "battery", "charge_planning", "hot_water", "ev")


def test_the_tariff_page_runs_four_steps_charge_planning_two_and_the_others_one():
    assert PAGE_STEPS["tariff"] == ("tariff", "tariff_rates", "bill", "schedule_change")
    assert PAGE_STEPS["charge_planning"] == ("charge_planning", "forecast")
    assert set(PAGE_STEPS) == {"tariff", "charge_planning"}


def test_a_page_may_write_its_own_keys_and_the_tariff_may_write_the_review_date():
    assert PAGE_WRITES["battery"] == set(PAGE_KEYS["battery"])
    # Charge planning runs two screens, so it may write the keys of both.
    assert PAGE_WRITES["charge_planning"] == set(PAGE_KEYS["charge_planning"]) | set(
        PAGE_KEYS["forecast"]
    )
    assert not set(PAGE_KEYS["battery"]) & set(PAGE_KEYS["charge_planning"])
    assert const.CONF_TARIFF_REVIEWED_ON in PAGE_WRITES["tariff"]
    assert const.CONF_TARIFF_CHANGES in PAGE_WRITES["tariff"]
    assert const.CONF_TARIFF_REVIEWED_ON not in PAGE_WRITES["hot_water"]


@pytest.mark.parametrize(
    ("left", "right", "same"),
    [
        (None, "", True),
        ("", None, True),
        (0, "", False),
        (0.3, 0.3, True),
        (5, 5.0, True),
        ("a", "b", False),
        ([], [], True),
        ([], None, True),
        ([], "", True),
        ([], [{"name": "Night"}], False),
    ],
)
def test_same_value(left, right, same):
    assert same_value(left, right) is same


def test_a_value_equal_to_what_is_in_force_is_not_a_change():
    current = {"battery_min_soc_pct": 12}

    assert changed_values({"battery_min_soc_pct": 12}, current) == {}
    assert changed_values({"battery_min_soc_pct": 15}, current) == {"battery_min_soc_pct": 15}


def test_a_key_that_is_unset_counts_as_the_value_the_engine_uses():
    unset_default = KEY_DEFAULTS["alt_heat_label"]

    assert changed_values({"alt_heat_label": unset_default}, {}) == {}
    assert changed_values({"alt_heat_label": "Gas"}, {}) == {"alt_heat_label": "Gas"}


def test_a_cleared_entity_changes_only_when_one_was_set():
    assert changed_values({"forecast_entity": ""}, {}) == {}
    assert changed_values({"forecast_entity": ""}, {"forecast_entity": "sensor.f"}) == {
        "forecast_entity": ""
    }
