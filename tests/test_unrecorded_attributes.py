"""Volatile and bulky attributes stay visible live but are not written to the recorder.

Home Assistant stores a new set of attributes, and fires state_changed, whenever one attribute
changes, even when the state did not. The attributes below move every few cycles or hold lists
and sentences, so they are listed in GivEnergyManagerSensor._unrecorded_attributes. The table
is written out here from the 0.18 plan and the attributes the sensors really publish, not read
from the sensor module, so a name added to a sensor fails a test until it is placed on purpose.

tests/ha_e2e/test_unrecorded_attributes_e2e.py proves the recorder side against a real one.
"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from custom_components.givenergy_inverter_manager.core.alt_heat_advice import WaterHeatingAdvice
from custom_components.givenergy_inverter_manager.core.alt_heat_schedule import AltHeatSchedule
from custom_components.givenergy_inverter_manager.core.alt_heat_start import AltHeatStart
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.core.setup_progress import SetupItem
from custom_components.givenergy_inverter_manager.core.tomorrow_outlook import TomorrowOutlook
from custom_components.givenergy_inverter_manager.sensor import GivEnergyManagerSensor
from custom_components.givenergy_inverter_manager.sensor_descriptions import SENSOR_DESCRIPTIONS

SELF_SUFFICIENCY = {
    "self_sufficiency",
    "self_sufficiency_yesterday",
    "self_sufficiency_this_week",
    "self_sufficiency_this_month",
}

# The sensors that publish each unrecorded attribute: attribute -> sensor keys.
UNRECORDED: dict[str, set[str]] = {
    "html": set(),  # report sensors, through html_fn
    "full_text": set(),  # any sentence sensor whose state was cut
    "bill_table": {"bill_audit"},
    "days_table": {"bill_audit"},
    "summary_table": {"previous_bill_audit"},
    "period": {"previous_bill_audit"},
    "recent_writes": {"register_write_count"},
    "battery_soc": {"night_survival_confidence"},
    "estimated_soc_at_sunrise": {"night_survival_confidence"},
    "minimum_soc": {"night_survival_confidence"},
    "warning_below_soc": {"night_survival_confidence"},
    "house_load_kwh": SELF_SUFFICIENCY,
    "from_grid_kwh": SELF_SUFFICIENCY,
    "grid_to_battery_kwh": SELF_SUFFICIENCY,
    "from_solar_and_battery_kwh": SELF_SUFFICIENCY,
    "ready_by": {"immersion_water_temperature"},
    "expected_ready": {"immersion_water_temperature"},
    "heating_rate_c_per_h": {"immersion_water_temperature"},
    "heating_rate_source": {"immersion_water_temperature"},
    "planned_heating": {"immersion_water_temperature"},
    "alt_cost_per_kwh": {"water_heating_cheapest_source"},
    "electricity_cost_per_kwh": {"water_heating_cheapest_source"},
    "cheapest_electricity_cost_per_kwh": {"water_heating_cheapest_source"},
    "alt_saving_per_kwh": {"water_heating_cheapest_source"},
    "best_hours_for_alt": {"water_heating_cheapest_source"},
    "horizon_ends": {"water_heating_cheapest_source"},
    "alt_start_by": {"water_heating_cheapest_source"},
    "alt_run_minutes": {"water_heating_cheapest_source"},
    "alt_for_ready_time": {"water_heating_cheapest_source"},
    "alt_keep_warm": {"water_heating_cheapest_source"},
    "alt_schedule": {"water_heating_cheapest_source"},
    "alt_schedule_saving": {"water_heating_cheapest_source"},
    "alt_schedule_days": {"water_heating_cheapest_source"},
    "alt_schedule_suggestion": {"water_heating_cheapest_source"},
    "import_kwh": {"tomorrow_outlook"},
    "export_kwh": {"tomorrow_outlook"},
    "import_cost": {"tomorrow_outlook"},
    "export_credit": {"tomorrow_outlook"},
    "charge_kwh": {"tomorrow_outlook"},
    "charge_cost": {"tomorrow_outlook"},
    "net_cost": {"tomorrow_outlook"},
    "end_soc_pct": {"tomorrow_outlook"},
    "min_soc_pct": {"tomorrow_outlook"},
    "forecast_kwh": {"tomorrow_outlook"},
    "table": {"tomorrow_outlook"},
}

# Attributes that explain a state and change rarely, or are the only record of why. They stay
# recorded, so a history graph or a logbook can still show them.
RECORDED = {
    "suggestion",
    "alt_label",
    "horizon",
    "cheapest_source_in_horizon",
    "outlook",
    "summary",
    "explanation",
    "basis",
    "changes",  # Charge Target Conflict: changes only when the suspicion does
    "last_seen",
    "target_entity",
    "stored_energy_value",
    "items",  # the setup checklist: it changes when a setup step is done, and rarely otherwise
    "day",  # Tomorrow Outlook: the date it projects, which changes once a day
}


def _everything() -> CoordinatorData:
    """A snapshot that makes every attribute function publish every attribute it can."""
    data = CoordinatorData()
    data.survival_reason = "Battery lasts the night."
    data.will_survive_night = True
    data.register_write_log = [{"at": "2026-12-15T12:00:00", "what": "target 80"}]
    data.immersion_ready_time = time(19, 0)
    data.immersion_expected_ready = True
    data.immersion_heating_rate_c_per_h = 10.0
    data.immersion_rate_source = "learned"
    data.immersion_planned_heating = "Heat from 15:00."
    start = AltHeatStart(
        ready_at=datetime(2026, 12, 15, 19),
        electric_cost_per_kwh=0.3,
        by_solar=False,
        saving_per_kwh=0.1,
        run_minutes=90,
        start_by=datetime(2026, 12, 15, 17),
        late=False,
    )
    data.water_heating_advice = WaterHeatingAdvice(
        source="alternative",
        suggestion="Oil is cheaper.",
        alt_cost_per_kwh=0.2,
        electricity_cost_per_kwh=0.3,
        cheapest_electricity_cost_per_kwh=0.15,
        alt_saving_per_kwh=0.1,
        alt_hours=("12:00 to 23:00",),
        horizon="ready_by",
        horizon_ends="19:00",
        cheapest_source_in_horizon="electricity",
        alt_start=start,
        keep_warm="Run it.",
    )
    data.alt_heat_schedule = AltHeatSchedule(10, ("12:30 to 13:00",), 5.0, "A sentence.")
    data.setup_items = (SetupItem("tariff", "Tariff set", True, True),)
    data.tomorrow_outlook = TomorrowOutlook(
        on=date(2026, 12, 16),
        forecast_kwh=5.0,
        import_kwh=3.0,
        export_kwh=0.0,
        import_cost=0.6,
        export_credit=0.0,
        charge_kwh=4.0,
        charge_cost=0.4,
        end_soc_pct=20.0,
        min_soc_pct=10.0,
        basis="Forecast 5.0 kWh from the forecast integration, the per-slot load profile.",
    )
    return data


def _published() -> dict[str, set[str]]:
    """Every attribute a sensor's attrs_fn publishes for the full snapshot, with its sensors."""
    data = _everything()
    published: dict[str, set[str]] = {}
    for description in SENSOR_DESCRIPTIONS:
        if description.attrs_fn is None:
            continue
        for name in description.attrs_fn(data) or {}:
            published.setdefault(name, set()).add(description.key)
    return published


class TestTheList:
    @pytest.mark.parametrize("name", sorted(UNRECORDED))
    def test_every_attribute_in_the_table_is_unrecorded(self, name):
        assert name in GivEnergyManagerSensor._unrecorded_attributes

    def test_nothing_else_is_unrecorded(self):
        assert GivEnergyManagerSensor._unrecorded_attributes == frozenset(UNRECORDED)

    @pytest.mark.parametrize(
        "name", sorted(n for n, sensors in UNRECORDED.items() if sensors)
    )
    def test_every_name_is_really_published_by_the_sensor_the_table_names(self, name):
        """A misspelt name would hide nothing and pass the test above."""
        assert UNRECORDED[name] <= _published().get(name, set())

    @pytest.mark.parametrize("name", sorted(RECORDED))
    def test_the_explaining_attributes_stay_recorded(self, name):
        assert name not in GivEnergyManagerSensor._unrecorded_attributes

    @pytest.mark.parametrize("name", sorted(RECORDED))
    def test_those_attributes_are_published_somewhere(self, name):
        assert name in _published()
