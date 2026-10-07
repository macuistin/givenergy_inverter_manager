"""Unit tests for the pure value functions behind the sensors (sensor_values.py)."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager import sensor_values as values
from custom_components.givenergy_inverter_manager.const import (
    BATTERY_FULL_SOC_PCT,
    BATTERY_RATED_CYCLES,
    NIGHT_SURVIVAL_WARNING_MARGIN_PCT,
)
from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator


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
        data = make_data(charge_window=None)

        assert values.overnight_charge_window(data) is None
        assert values.overnight_charge_window_attributes(data) is None

    def test_state_is_the_written_window(self):
        data = make_data(charge_window=self._window())

        assert values.overnight_charge_window(data) == "02:00 to 06:10"

    def test_attributes_explain_the_window(self):
        data = make_data(charge_window=self._window())

        assert values.overnight_charge_window_attributes(data) == {
            "window_start": "02:00",
            "window_end": "06:10",
            "window_extended": True,
            "expected_kwh": 12.92,
            "expected_finish": "05:36",
        }

    def test_attributes_leave_out_what_is_not_known(self):
        window = self._window(extended=False, expected_kwh=None, finish_time=None)

        attributes = values.overnight_charge_window_attributes(make_data(charge_window=window))

        assert attributes["window_extended"] is False
        assert attributes["expected_kwh"] is None
        assert attributes["expected_finish"] is None


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
        assert attrs["explanation"].startswith("Critical")


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

    def test_actual_vs_forecast(self):
        data = make_data(solar_forecast_kwh_today=10.0)
        data.today.solar_kwh = 7.5
        assert values.solar_actual_vs_forecast_pct(data) == pytest.approx(75.0)

    def test_actual_vs_forecast_none_without_a_forecast(self):
        data = make_data(solar_forecast_kwh_today=0.0)
        data.today.solar_kwh = 7.5
        assert values.solar_actual_vs_forecast_pct(data) is None


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
