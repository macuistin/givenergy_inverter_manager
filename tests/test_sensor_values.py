"""Unit tests for the pure value functions behind the sensors (sensor_values.py)."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager import sensor_values as values
from custom_components.givenergy_inverter_manager.const import (
    BATTERY_EFFICIENCY_MIN_KWH,
    BATTERY_FULL_SOC_PCT,
    BATTERY_RATED_CYCLES,
    NIGHT_SURVIVAL_WARNING_MARGIN_PCT,
)
from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.core.rules import forecast_accuracy
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from custom_components.givenergy_inverter_manager.core.tariff_check import RateMismatch


def make_data(**fields) -> CoordinatorData:
    """Return a snapshot with the given top-level fields set."""
    data = CoordinatorData()
    for name, value in fields.items():
        setattr(data, name, value)
    return data


class TestGridPowerDirection:
    @pytest.mark.parametrize(
        ("grid_w", "expected"),
        [
            (1200.0, values.GRID_IMPORTING),
            (51.0, values.GRID_IMPORTING),
            (50.0, values.GRID_BALANCED),
            (0.0, values.GRID_BALANCED),
            (-50.0, values.GRID_BALANCED),
            (-51.0, values.GRID_EXPORTING),
            (-3000.0, values.GRID_EXPORTING),
        ],
    )
    def test_direction(self, grid_w, expected):
        assert values.grid_power_direction(make_data(grid_power_w=grid_w)) == expected

    def test_state_strings_are_unchanged(self):
        assert (values.GRID_IMPORTING, values.GRID_EXPORTING, values.GRID_BALANCED) == (
            "Importing",
            "Exporting",
            "Balanced",
        )


class TestSolarPowerPctOfMax:
    def test_share_of_the_inverter_limit(self):
        data = make_data(solar_power_w=2500.0, inverter_max_w=5000.0)
        assert values.solar_power_pct_of_max(data) == pytest.approx(50.0)

    def test_none_without_a_limit(self):
        data = make_data(solar_power_w=2500.0, inverter_max_w=0.0)
        assert values.solar_power_pct_of_max(data) is None

    def test_rounds_to_one_place(self):
        data = make_data(solar_power_w=1000.0, inverter_max_w=3000.0)
        assert values.solar_power_pct_of_max(data) == 33.3


class TestBatteryPowerDirection:
    @pytest.mark.parametrize(
        ("power_w", "expected"),
        [
            (2500.0, values.BATTERY_CHARGING),
            (51.0, values.BATTERY_CHARGING),
            (50.0, values.BATTERY_IDLE),
            (0.0, values.BATTERY_IDLE),
            (-50.0, values.BATTERY_IDLE),
            (-51.0, values.BATTERY_DISCHARGING),
            (-1800.0, values.BATTERY_DISCHARGING),
        ],
    )
    def test_direction(self, power_w, expected):
        assert values.battery_power_direction(make_data(battery_power_w=power_w)) == expected


class TestBatteryState:
    @pytest.mark.parametrize(
        ("soc", "power", "expected"),
        [
            (100.0, 0.0, "Full"),
            (99.0, 10.0, "Full"),
            (99.0, 1500.0, "Full"),
            (100.0, -1500.0, "Discharging"),
            (80.0, -1500.0, "Discharging"),
            (80.0, 1500.0, "Charging"),
            (80.0, 20.0, "Idle"),
            (50.0, -50.0, "Idle"),
        ],
    )
    def test_state(self, soc, power, expected):
        assert values.battery_state(make_data(battery_soc=soc, battery_power_w=power)) == expected

    def test_full_threshold_is_the_shared_constant(self):
        just_below = make_data(battery_soc=BATTERY_FULL_SOC_PCT - 0.1, battery_power_w=0.0)
        at_threshold = make_data(battery_soc=BATTERY_FULL_SOC_PCT, battery_power_w=0.0)
        assert values.battery_state(just_below) == "Idle"
        assert values.battery_state(at_threshold) == "Full"


class TestBatteryEnergy:
    def test_kwh_available(self):
        data = make_data(battery_soc=50.0, battery_capacity_kwh=18.6)
        assert values.battery_kwh_available(data) == pytest.approx(9.3)

    def test_kwh_available_none_without_capacity(self):
        assert values.battery_kwh_available(make_data(battery_soc=50.0)) is None

    def test_usable_capacity_scales_with_remaining_life(self):
        stats = BatteryStats(total_cycles=0.0)
        data = make_data(battery_capacity_kwh=10.0, battery_stats=stats)
        assert values.battery_usable_capacity_kwh(data) == pytest.approx(10.0)
        stats.total_cycles = 600.0
        expected = round(10.0 * stats.estimated_remaining_life_pct / 100, 2)
        assert values.battery_usable_capacity_kwh(data) == pytest.approx(expected)

    def test_usable_capacity_none_without_capacity(self):
        assert values.battery_usable_capacity_kwh(make_data()) is None


class TestBatteryLifeConsumed:
    def test_one_full_cycle_uses_one_rated_cycle_share(self):
        data = make_data(battery_capacity_kwh=18.6)
        data.today.battery_throughput_kwh = 37.2  # a full charge plus a full discharge
        assert values.battery_life_consumed_today_pct(data) == pytest.approx(
            100 / BATTERY_RATED_CYCLES, rel=1e-3
        )

    def test_zero_without_capacity(self):
        data = make_data(battery_capacity_kwh=0.0)
        data.today.battery_throughput_kwh = 10.0
        assert values.battery_life_consumed_today_pct(data) == 0.0

    def test_rounds_to_six_places(self):
        data = make_data(battery_capacity_kwh=10.0)
        data.today.battery_throughput_kwh = 3.3333333
        result = values.battery_life_consumed_today_pct(data)
        assert result == round(result, 6)


class TestBatteryOptionalFigures:
    def test_cycle_cost_rounds_to_five_places(self):
        assert values.battery_cycle_cost_per_kwh(
            make_data(battery_cycle_cost_per_kwh=0.0123456)
        ) == pytest.approx(0.01235)

    def test_cycle_cost_none_when_zero(self):
        assert values.battery_cycle_cost_per_kwh(make_data(battery_cycle_cost_per_kwh=0.0)) is None

    def test_years_remaining_rounds_and_handles_none(self):
        assert values.battery_years_remaining(
            make_data(battery_years_remaining=12.345)
        ) == pytest.approx(12.3)
        assert values.battery_years_remaining(make_data(battery_years_remaining=None)) is None

    def test_throughput_budget_rounds_and_handles_none(self):
        assert values.battery_throughput_budget_pct(
            make_data(battery_throughput_budget_pct=83.456)
        ) == pytest.approx(83.5)
        assert (
            values.battery_throughput_budget_pct(make_data(battery_throughput_budget_pct=None))
            is None
        )

    def test_zero_is_reported_not_hidden(self):
        assert values.battery_years_remaining(make_data(battery_years_remaining=0.0)) == 0.0
        assert values.inverter_temperature(make_data(inverter_temperature=0.0)) == 0.0
        assert values.carbon_intensity(make_data(carbon_intensity_gco2=0.0)) == 0.0


class TestRoundtripEfficiency:
    def test_discharge_over_charge(self):
        data = make_data()
        data.today.battery_charge_kwh = 10.0
        data.today.battery_discharge_kwh = 9.2
        assert values.battery_roundtrip_efficiency_today(data) == pytest.approx(92.0)

    def test_none_before_any_charging(self):
        data = make_data()
        data.today.battery_charge_kwh = 0.0
        data.today.battery_discharge_kwh = 1.0
        assert values.battery_roundtrip_efficiency_today(data) is None

    def test_none_early_in_the_day_after_an_overnight_charge(self):
        data = make_data()
        data.today.battery_charge_kwh = 6.0
        data.today.battery_discharge_kwh = 0.8
        assert values.battery_roundtrip_efficiency_today(data) is None

    def test_none_while_the_charge_is_under_the_minimum(self):
        data = make_data()
        data.today.battery_charge_kwh = BATTERY_EFFICIENCY_MIN_KWH - 0.1
        data.today.battery_discharge_kwh = BATTERY_EFFICIENCY_MIN_KWH + 1.0
        assert values.battery_roundtrip_efficiency_today(data) is None

    def test_reported_once_both_directions_reach_the_minimum(self):
        data = make_data()
        data.today.battery_charge_kwh = BATTERY_EFFICIENCY_MIN_KWH
        data.today.battery_discharge_kwh = BATTERY_EFFICIENCY_MIN_KWH
        assert values.battery_roundtrip_efficiency_today(data) == pytest.approx(100.0)


class TestNextCheapRateStart:
    def test_shows_the_start_time_when_known(self):
        data = make_data(next_cheap_rate_start="23:00", hours_to_cheap_rate=9.0)
        assert values.next_cheap_rate_start(data) == "23:00"

    def test_shows_now_when_a_cheap_rate_is_active(self):
        data = make_data(next_cheap_rate_start=None, hours_to_cheap_rate=0.0)
        assert values.next_cheap_rate_start(data) == "Now"

    def test_none_on_a_flat_tariff(self):
        data = make_data(next_cheap_rate_start=None, hours_to_cheap_rate=None)
        assert values.next_cheap_rate_start(data) is None


class TestCheapRateSummary:
    @staticmethod
    def _summary(start, hours, remaining=None):
        data = make_data(
            next_cheap_rate_start=start, hours_to_cheap_rate=hours, cheap_run_remaining_minutes=remaining
        )
        return values.cheap_rate_summary(data)

    @pytest.mark.parametrize(
        ("hours", "expected"),
        [
            (8.93, "23:00 (in 8 h 56 min)"),
            (9.0, "23:00 (in 9 h)"),
            (1.0, "23:00 (in 1 h)"),
            (1.02, "23:00 (in 1 h 1 min)"),
            (0.75, "23:00 (in 45 min)"),
            (0.02, "23:00 (in 1 min)"),
            (59.9 / 60, "23:00 (in 1 h)"),
            (59.4 / 60, "23:00 (in 59 min)"),
            (60 / 60, "23:00 (in 1 h)"),
            (24.0, "23:00 (in 24 h)"),
        ],
    )
    def test_counts_down_to_a_later_start(self, hours, expected):
        assert self._summary("23:00", hours) == expected

    def test_start_alone_when_the_wait_is_unknown(self):
        assert self._summary("23:00", None) == "23:00"

    def test_zero_wait_with_a_start_reads_zero_minutes(self):
        assert self._summary("23:00", 0.0) == "23:00 (in 0 min)"

    @pytest.mark.parametrize(
        ("remaining", "expected"),
        [
            (72.0, "Now (ends in 1 h 12 min)"),
            (71.6, "Now (ends in 1 h 12 min)"),
            (60.0, "Now (ends in 1 h)"),
            (59.9, "Now (ends in 1 h)"),
            (59.4, "Now (ends in 59 min)"),
            (45.0, "Now (ends in 45 min)"),
            (420.0, "Now (ends in 7 h)"),
            (0.0, "Now (ends in 0 min)"),
        ],
    )
    def test_says_when_the_cheap_run_ends(self, remaining, expected):
        assert self._summary(None, 0.0, remaining) == expected

    def test_now_alone_when_the_end_is_unknown(self):
        assert self._summary(None, 0.0, None) == "Now"

    def test_none_on_a_tariff_without_a_cheap_period(self):
        assert self._summary(None, None) is None
        assert self._summary(None, None, 30.0) is None


class TestImmersionReadyAttributes:
    def test_none_without_a_ready_time(self):
        assert values.immersion_ready_attributes(make_data()) is None

    def test_the_plan_and_the_rate_it_used(self):
        from datetime import time

        data = make_data(
            immersion_ready_time=time(19, 0),
            immersion_expected_ready=True,
            immersion_heating_rate_c_per_h=8.6,
            immersion_rate_source="assumed",
        )
        assert values.immersion_ready_attributes(data) == {
            "ready_by": "19:00",
            "expected_ready": True,
            "heating_rate_c_per_h": 8.6,
            "heating_rate_source": "assumed",
        }


class TestImmersionWaterAttributes:
    def test_none_without_a_ready_time_or_a_plan(self):
        assert values.immersion_water_attributes(make_data()) is None

    def test_the_plan_alone_when_no_ready_time_is_set(self):
        data = make_data(immersion_planned_heating="No ready time is set.")
        assert values.immersion_water_attributes(data) == {
            "planned_heating": "No ready time is set."
        }

    def test_the_ready_attributes_stay_and_the_plan_joins_them(self):
        from datetime import time

        data = make_data(
            immersion_ready_time=time(19, 0),
            immersion_expected_ready=True,
            immersion_heating_rate_c_per_h=8.6,
            immersion_rate_source="assumed",
            immersion_planned_heating="No heating planned.",
        )
        attributes = values.immersion_water_attributes(data)
        assert attributes == {
            **values.immersion_ready_attributes(data),
            "planned_heating": "No heating planned.",
        }

    def test_the_ready_attributes_alone_without_a_plan(self):
        from datetime import time

        data = make_data(immersion_ready_time=time(19, 0), immersion_expected_ready=False)
        assert values.immersion_water_attributes(data) == values.immersion_ready_attributes(data)


class TestWaterHeatingAdvice:
    def _data(self):
        from custom_components.givenergy_inverter_manager.core.oil_advice import WaterHeatingAdvice

        advice = WaterHeatingAdvice(
            source="oil",
            suggestion="Oil is cheaper than electricity until 23:00.",
            oil_cost_per_kwh=0.2000004,
            electricity_cost_per_kwh=0.3,
            cheapest_electricity_cost_per_kwh=0.15,
            oil_saving_per_kwh=0.0999996,
            oil_hours=("12:00 to 23:00",),
            horizon="ready_by",
            horizon_ends="07:00",
            cheapest_source_in_horizon="electricity",
        )
        return make_data(water_heating_advice=advice)

    def test_the_state_is_the_cheapest_source(self):
        assert values.water_heating_source(self._data()) == "oil"

    def test_no_state_without_advice(self):
        assert values.water_heating_source(make_data()) is None
        assert values.water_heating_attributes(make_data()) is None

    def test_the_attributes_carry_the_sentence_and_the_figures(self):
        assert values.water_heating_attributes(self._data()) == {
            "suggestion": "Oil is cheaper than electricity until 23:00.",
            "oil_cost_per_kwh": 0.2,
            "electricity_cost_per_kwh": 0.3,
            "cheapest_electricity_cost_per_kwh": 0.15,
            "oil_saving_per_kwh": 0.1,
            "best_hours_for_oil": ["12:00 to 23:00"],
            "horizon": "ready_by",
            "horizon_ends": "07:00",
            "cheapest_source_in_horizon": "electricity",
        }


class TestOilStartAttributes:
    def _data(self, start_by, keep_warm=None):
        from datetime import datetime

        from custom_components.givenergy_inverter_manager.core.oil_advice import WaterHeatingAdvice
        from custom_components.givenergy_inverter_manager.core.oil_start import OilStart

        start = OilStart(
            ready_at=datetime(2026, 12, 15, 19, 0),
            electric_cost_per_kwh=0.3,
            by_solar=False,
            saving_per_kwh=0.1,
            run_minutes=90,
            start_by=start_by,
            late=False,
        )
        advice = WaterHeatingAdvice(
            source="oil",
            suggestion="s",
            oil_cost_per_kwh=0.2,
            electricity_cost_per_kwh=0.3,
            cheapest_electricity_cost_per_kwh=0.3,
            oil_saving_per_kwh=0.1,
            oil_hours=(),
            horizon="ready_by",
            horizon_ends="19:00",
            cheapest_source_in_horizon="oil",
            oil_start=start,
            keep_warm=keep_warm,
        )
        return make_data(water_heating_advice=advice)

    def test_a_start_gives_the_time_the_minutes_and_the_ready_time(self):
        from datetime import datetime

        attrs = values.water_heating_attributes(self._data(datetime(2026, 12, 15, 16, 30)))
        assert attrs["oil_start_by"] == "16:30"
        assert attrs["oil_run_minutes"] == 90
        assert attrs["oil_for_ready_time"] == "19:00"
        assert "oil_keep_warm" not in attrs

    def test_no_start_leaves_the_three_attributes_out(self):
        attrs = values.water_heating_attributes(self._data(None))
        assert not {"oil_start_by", "oil_run_minutes", "oil_for_ready_time"} & set(attrs)

    def test_keep_warm_is_the_sentence_or_absent(self):
        assert values.water_heating_attributes(self._data(None, "Run the oil."))["oil_keep_warm"] == "Run the oil."
        assert "oil_keep_warm" not in values.water_heating_attributes(self._data(None))


class TestOilScheduleAttributes:
    """oil_schedule, oil_schedule_saving, oil_schedule_days and the sentence, apart from suggestion."""

    SENTENCE = "Over the last 10 days the immersion used about 15 kWh. Running the oil from 12:30 to 13:00."

    def _data(self, schedule):
        from custom_components.givenergy_inverter_manager.core.oil_advice import WaterHeatingAdvice

        advice = WaterHeatingAdvice(
            source="oil",
            suggestion="Live suggestion.",
            oil_cost_per_kwh=0.2,
            electricity_cost_per_kwh=0.3,
            cheapest_electricity_cost_per_kwh=0.3,
            oil_saving_per_kwh=0.1,
            oil_hours=(),
            horizon="next_24_hours",
            horizon_ends="12:00",
            cheapest_source_in_horizon="oil",
        )
        return make_data(water_heating_advice=advice, oil_schedule=schedule)

    def _schedule(self, **fields):
        from custom_components.givenergy_inverter_manager.core.oil_schedule import OilSchedule

        defaults = {
            "days": 10,
            "windows": ("12:30 to 13:00", "18:00 to 19:00"),
            "saving": 5.8765,
            "sentence": self.SENTENCE,
        }
        return OilSchedule(**{**defaults, **fields})

    def test_with_a_suggestion_the_four_attributes_are_present(self):
        attrs = values.water_heating_attributes(self._data(self._schedule()))
        assert attrs["oil_schedule"] == ["12:30 to 13:00", "18:00 to 19:00"]
        assert attrs["oil_schedule_saving"] == 5.88
        assert attrs["oil_schedule_days"] == 10
        assert attrs["oil_schedule_suggestion"] == self.SENTENCE

    def test_the_schedule_is_not_mixed_into_the_live_suggestion(self):
        attrs = values.water_heating_attributes(self._data(self._schedule()))
        assert attrs["suggestion"] == "Live suggestion."

    def test_before_a_week_of_data_none_of_them_is_present(self):
        attrs = values.water_heating_attributes(self._data(None))
        assert not {k for k in attrs if k.startswith("oil_schedule")}

    def test_with_a_week_and_nothing_to_suggest_the_list_is_empty_and_there_is_no_sentence(self):
        attrs = values.water_heating_attributes(
            self._data(self._schedule(windows=(), saving=0.0, sentence=None))
        )
        assert attrs["oil_schedule"] == []
        assert attrs["oil_schedule_saving"] == 0
        assert attrs["oil_schedule_days"] == 10
        assert "oil_schedule_suggestion" not in attrs

    def test_no_attributes_at_all_without_advice(self):
        assert values.water_heating_attributes(make_data(oil_schedule=self._schedule())) is None


class TestCheapRateAttributes:
    def test_carries_the_summary(self):
        data = make_data(next_cheap_rate_start="23:00", hours_to_cheap_rate=9.0)
        assert values.cheap_rate_attributes(data) == {"summary": "23:00 (in 9 h)"}

    def test_absent_on_a_tariff_without_a_cheap_period(self):
        data = make_data(next_cheap_rate_start=None, hours_to_cheap_rate=None)
        assert values.cheap_rate_attributes(data) is None


class TestDryRunAttributes:
    """The dashboard tile reads On or Off. The state stays True or False."""

    def test_on(self):
        assert values.dry_run_attributes(make_data(dry_run=True)) == {"summary": "On"}

    def test_off(self):
        assert values.dry_run_attributes(make_data(dry_run=False)) == {"summary": "Off"}


class TestGivTCPRateAttributes:
    def test_lists_each_rate_that_differs(self):
        mismatch = RateMismatch("Day rate", 0.3334, 0.395)
        data = make_data(givtcp_rate_mismatches=(mismatch,))
        assert values.givtcp_rate_attributes(data) == {
            "givtcp_rates_differ": True,
            "givtcp_rate_differences": ["Day rate: 0.3334 here, 0.395 in GivTCP"],
        }

    def test_false_and_empty_when_the_rates_agree(self):
        data = make_data(givtcp_rate_mismatches=())
        assert values.givtcp_rate_attributes(data) == {
            "givtcp_rates_differ": False,
            "givtcp_rate_differences": [],
        }

    def test_absent_when_no_givtcp_rate_is_readable(self):
        assert values.givtcp_rate_attributes(make_data()) is None


class TestImportFigures:
    @staticmethod
    def _accumulator(import_kwh, cost=0.0, cheap_kwh=0.0) -> EnergyAccumulator:
        acc = EnergyAccumulator()
        acc.import_kwh = import_kwh
        acc.import_kwh_cheap = cheap_kwh
        acc.import_cost_by_period = {"Day": cost}
        return acc

    def test_average_rate_is_cost_over_kwh(self):
        assert values.average_import_rate(self._accumulator(10.0, cost=3.0)) == pytest.approx(0.3)

    def test_average_rate_none_without_imports(self):
        assert values.average_import_rate(self._accumulator(0.0, cost=3.0)) is None

    def test_cheap_percentage(self):
        acc = self._accumulator(8.0, cheap_kwh=5.0)
        assert values.cheap_import_percentage(acc) == pytest.approx(62.5)

    def test_cheap_percentage_none_without_imports(self):
        assert values.cheap_import_percentage(self._accumulator(0.0)) is None


class TestPublishedChargeRecommendation:
    """The target and reason sensors read the held copy, never the fresh decision."""

    @staticmethod
    def _decision(target_soc, reason):
        class Decision:
            pass

        decision = Decision()
        decision.target_soc = target_soc
        decision.reason = reason
        return decision

    def test_none_before_the_first_decision(self):
        data = make_data(charge_decision=self._decision(90, "fresh"))
        assert values.overnight_charge_target(data) is None
        assert values.overnight_charge_reason(data) is None

    def test_target_and_reason_come_from_the_published_decision(self):
        data = make_data(
            charge_decision=self._decision(90, "fresh"),
            published_charge_decision=self._decision(87, "held"),
        )
        assert values.overnight_charge_target(data) == 87
        assert values.overnight_charge_reason(data) == "held"

    def test_cost_comes_from_the_published_decision(self):
        fresh, held = self._decision(90, "fresh"), self._decision(87, "held")
        fresh.cost_to_charge, held.cost_to_charge = 2.0, 1.0
        data = make_data(charge_decision=fresh, published_charge_decision=held)
        assert values.overnight_charge_cost(data) == pytest.approx(1.0)


class TestOvernightChargeCost:
    def test_none_before_the_first_decision(self):
        assert values.overnight_charge_cost(make_data(published_charge_decision=None)) is None

    def test_rounds_to_three_places(self):
        class Decision:
            cost_to_charge = 1.23456

        data = make_data(published_charge_decision=Decision())
        assert values.overnight_charge_cost(data) == pytest.approx(1.235)


class TestOvernightChargeWindow:
    @staticmethod
    def _window(**fields):
        from datetime import time

        from custom_components.givenergy_inverter_manager.core.charge_window import ChargeWindow

        defaults = {
            "start": time(2, 0),
            "end": time(6, 10),
            "extended": True,
            "expected_kwh": 12.92,
            "finish_time": time(5, 36),
        }
        return ChargeWindow(**{**defaults, **fields})

    def test_none_without_a_window(self):
        data = make_data(published_charge_window=None)

        assert values.overnight_charge_window(data) is None
        assert values.overnight_charge_window_attributes(data) is None

    def test_state_is_the_written_window(self):
        data = make_data(published_charge_window=self._window())

        assert values.overnight_charge_window(data) == "02:00 to 06:10"

    def test_attributes_explain_the_window(self):
        data = make_data(published_charge_window=self._window())

        assert values.overnight_charge_window_attributes(data) == {
            "window_start": "02:00",
            "window_end": "06:10",
            "window_extended": True,
            "expected_kwh": 12.92,
            "expected_finish": "05:36",
        }

    def test_state_and_attributes_come_from_the_published_window_not_the_planned_one(self):
        from datetime import time

        data = make_data(
            charge_window=self._window(end=time(6, 40)),
            published_charge_window=self._window(end=time(6, 10)),
        )

        assert values.overnight_charge_window(data) == "02:00 to 06:10"
        assert values.overnight_charge_window_attributes(data)["window_end"] == "06:10"

    def test_attributes_leave_out_what_is_not_known(self):
        window = self._window(extended=False, expected_kwh=None, finish_time=None)

        attributes = values.overnight_charge_window_attributes(
            make_data(published_charge_window=window)
        )

        assert attributes["window_extended"] is False
        assert attributes["expected_kwh"] is None
        assert attributes["expected_finish"] is None


class TestForecastAccuracyAttributes:
    def test_none_before_the_first_cycle(self):
        assert values.forecast_accuracy_attributes(make_data()) is None

    def test_waiting_for_data(self):
        accuracy = forecast_accuracy([{"forecast": 10.0, "actual": 7.0, "clipped": False}] * 3)

        attributes = values.forecast_accuracy_attributes(make_data(forecast_accuracy=accuracy))

        assert attributes == {
            "accuracy_status": "Waiting for data: 3 of 5 days",
            "accuracy_applied": False,
            "accuracy_measured_factor": 0.7,
            "accuracy_applied_factor": None,
            "accuracy_usable_days": 3,
            "accuracy_days_needed": 5,
            "accuracy_days_stored": 3,
        }

    def test_applied(self):
        accuracy = forecast_accuracy([{"forecast": 10.0, "actual": 8.0, "clipped": False}] * 7)

        attributes = values.forecast_accuracy_attributes(make_data(forecast_accuracy=accuracy))

        assert attributes["accuracy_applied"] is True
        assert attributes["accuracy_applied_factor"] == 0.8
        assert attributes["accuracy_status"] == "Applied: x0.80 from 7 usable days"

    def test_the_reason_sensor_publishes_them(self):
        from custom_components.givenergy_inverter_manager.sensor_descriptions.decisions import (
            DESCRIPTIONS,
        )

        reason = next(d for d in DESCRIPTIONS if d.key == "overnight_charge_reason")

        assert reason.attrs_fn is values.forecast_accuracy_attributes


class TestNightSurvivalConfidence:
    @staticmethod
    def _night(reason="ok", survive=True, sunrise_soc=50.0, min_soc=10):
        return make_data(
            survival_reason=reason,
            will_survive_night=survive,
            estimated_soc_at_sunrise=sunrise_soc,
            battery_min_soc=min_soc,
        )

    def test_unknown_before_first_cycle(self):
        assert values.night_survival_confidence(self._night(reason="")) is None

    def test_critical_when_the_battery_runs_out(self):
        data = self._night(survive=False, sunrise_soc=10.0)
        assert values.night_survival_confidence(data) == "Critical"

    def test_warning_near_min_soc(self):
        data = self._night(sunrise_soc=12.0, min_soc=10)
        assert values.night_survival_confidence(data) == "Warning"

    def test_warning_fires_with_a_high_min_soc(self):
        data = self._night(sunrise_soc=22.0, min_soc=20)
        assert values.night_survival_confidence(data) == "Warning"

    def test_safe_with_headroom(self):
        data = self._night(sunrise_soc=40.0, min_soc=10)
        assert values.night_survival_confidence(data) == "Safe"

    def test_warning_margin_boundary(self):
        edge = 10 + NIGHT_SURVIVAL_WARNING_MARGIN_PCT
        assert values.night_survival_confidence(self._night(sunrise_soc=edge - 0.1)) == "Warning"
        assert values.night_survival_confidence(self._night(sunrise_soc=edge)) == "Safe"

    def test_attributes_none_before_first_cycle(self):
        assert values.night_survival_attributes(self._night(reason="")) is None

    def test_attributes_explain_the_level(self):
        attrs = values.night_survival_attributes(self._night(survive=False, reason="Runs out"))
        assert attrs["explanation"] == "Runs out"
        assert attrs["outlook"] == "May run low"


class TestRegisterWriteAttributes:
    def test_recent_writes_are_listed_newest_first(self):
        log = [
            {"time": "t1", "entity_id": "number.t", "value": "55", "reason": "charge target"},
            {"time": "t2", "entity_id": "number.t", "value": "60", "reason": "external"},
        ]
        attrs = values.register_write_attributes(make_data(register_write_log=log))
        assert [w["time"] for w in attrs["recent_writes"]] == ["t2", "t1"]

    def test_an_empty_log_gives_an_empty_list(self):
        assert values.register_write_attributes(make_data()) == {"recent_writes": []}


class TestInverterAndCarbon:
    def test_temperature_rounds_and_handles_none(self):
        assert values.inverter_temperature(make_data(inverter_temperature=41.26)) == 41.3
        assert values.inverter_temperature(make_data(inverter_temperature=None)) is None

    def test_carbon_intensity_rounds_and_handles_none(self):
        assert values.carbon_intensity(make_data(carbon_intensity_gco2=180.46)) == 180.5
        assert values.carbon_intensity(make_data(carbon_intensity_gco2=None)) is None

    def test_carbon_status_needs_a_known_intensity(self):
        known = make_data(carbon_intensity_gco2=120.0, carbon_intensity_status="Low")
        unknown = make_data(carbon_intensity_gco2=None, carbon_intensity_status="Low")
        assert values.carbon_intensity_status(known) == "Low"
        assert values.carbon_intensity_status(unknown) is None


class TestSolarFigures:
    @staticmethod
    def _solar(solar_kwh, missed_kwh) -> CoordinatorData:
        data = make_data()
        data.today.solar_kwh = solar_kwh
        data.today.missed_solar_kwh = missed_kwh
        return data

    def test_capture_excludes_missed_solar_once(self):
        assert values.solar_capture_efficiency_today(self._solar(20.0, 5.0)) == pytest.approx(75.0)

    def test_capture_full_when_nothing_missed(self):
        assert values.solar_capture_efficiency_today(self._solar(12.0, 0.0)) == pytest.approx(100.0)

    def test_capture_never_negative(self):
        assert values.solar_capture_efficiency_today(self._solar(4.0, 6.0)) == pytest.approx(0.0)

    def test_capture_none_without_solar(self):
        assert values.solar_capture_efficiency_today(self._solar(0.0, 0.0)) is None

    def _forecasts(self, raw: float | None, plan: float, solar: float) -> CoordinatorData:
        data = make_data(solar_forecast_raw_kwh_today=raw, solar_forecast_kwh_today=plan)
        data.today.solar_kwh = solar
        return data

    def test_actual_vs_forecast_uses_the_provider_forecast(self):
        data = self._forecasts(raw=10.0, plan=4.0, solar=7.5)
        assert values.solar_actual_vs_forecast_pct(data) == pytest.approx(75.0)

    def test_actual_vs_forecast_ignores_the_blended_charge_plan_forecast(self):
        """Live case: the plan held 31.5 kWh against the provider's 38.96, which flattered the day."""
        data = self._forecasts(raw=38.96, plan=31.5, solar=20.0)
        assert values.solar_actual_vs_forecast_pct(data) == pytest.approx(51.3)

    def test_actual_vs_forecast_passes_100_when_the_day_beats_the_forecast(self):
        data = self._forecasts(raw=38.96, plan=31.5, solar=45.0)
        assert values.solar_actual_vs_forecast_pct(data) == pytest.approx(115.5)

    def test_actual_vs_forecast_is_zero_before_any_solar(self):
        data = self._forecasts(raw=38.96, plan=31.5, solar=0.0)
        assert values.solar_actual_vs_forecast_pct(data) == 0.0

    def test_actual_vs_forecast_none_without_a_provider_forecast(self):
        """A plan forecast alone, such as the seasonal estimate, is not a provider forecast."""
        data = self._forecasts(raw=None, plan=31.5, solar=7.5)
        assert values.solar_actual_vs_forecast_pct(data) is None

    def test_actual_vs_forecast_none_for_a_zero_forecast(self):
        data = self._forecasts(raw=0.0, plan=31.5, solar=7.5)
        assert values.solar_actual_vs_forecast_pct(data) is None

    def test_forecast_raw_today_reports_the_provider_figure(self):
        data = self._forecasts(raw=38.9649, plan=31.5, solar=0.0)
        assert values.solar_forecast_raw_today(data) == 38.965

    def test_forecast_raw_today_none_when_none_was_seen(self):
        assert values.solar_forecast_raw_today(self._forecasts(None, 31.5, 0.0)) is None


def test_yes_and_no_strings_are_unchanged():
    assert (values.YES, values.NO) == ("yes", "no")


class TestSelfSufficiencyAttributes:
    """The kWh behind a self-sufficiency percentage, so it can be checked by hand."""

    @staticmethod
    def _live_day() -> EnergyAccumulator:
        return EnergyAccumulator(house_kwh=11.3, import_kwh=12.1, grid_to_battery_kwh=7.5)

    def test_the_live_day_is_broken_down_into_its_sources(self):
        data = make_data(today=self._live_day(), grid_to_battery_counter_available=True)
        assert values.self_sufficiency_attributes_today(data) == {
            "house_load_kwh": 11.3,
            "from_grid_kwh": 4.6,
            "grid_to_battery_kwh": 7.5,
            "from_solar_and_battery_kwh": 6.7,
            "basis": values.SUFFICIENCY_BASIS_AC_CHARGE,
        }

    def test_the_sources_add_up_to_the_house_load(self):
        attrs = values.self_sufficiency_attributes_today(make_data(today=self._live_day()))
        assert attrs["from_grid_kwh"] + attrs["from_solar_and_battery_kwh"] == pytest.approx(
            attrs["house_load_kwh"]
        )

    def test_the_basis_is_the_counter_while_it_is_readable(self):
        data = make_data(
            today=EnergyAccumulator(house_kwh=5.0, import_kwh=1.0),
            grid_to_battery_counter_available=True,
        )
        assert values.self_sufficiency_attributes_today(data)["basis"] == "ac_charge_counter"

    def test_the_basis_is_import_only_without_the_counter(self):
        data = make_data(
            today=EnergyAccumulator(house_kwh=11.3, import_kwh=12.1),
            grid_to_battery_counter_available=False,
        )
        attrs = values.self_sufficiency_attributes_today(data)
        assert attrs["basis"] == "import_only"
        assert attrs["from_grid_kwh"] == pytest.approx(12.1)
        assert attrs["grid_to_battery_kwh"] == 0.0

    def test_a_week_that_holds_counter_energy_keeps_the_counter_basis_through_an_outage(self):
        data = make_data(week=self._live_day(), grid_to_battery_counter_available=False)
        assert values.self_sufficiency_attributes_week(data)["basis"] == "ac_charge_counter"

    @pytest.mark.parametrize(
        ("period", "function"),
        [
            ("yesterday", values.self_sufficiency_attributes_yesterday),
            ("week", values.self_sufficiency_attributes_week),
            ("month", values.self_sufficiency_attributes_month),
        ],
    )
    def test_each_period_reads_its_own_accumulator(self, period, function):
        data = make_data(**{period: self._live_day()}, grid_to_battery_counter_available=True)
        assert function(data)["from_grid_kwh"] == pytest.approx(4.6)
