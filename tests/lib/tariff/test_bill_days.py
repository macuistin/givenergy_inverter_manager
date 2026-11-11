# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""The stored rows of a bill period: what a day holds and when the tariff is recorded."""

from __future__ import annotations

from datetime import date

from custom_components.givenergy_inverter_manager.lib.tariff import EnergyAccumulator
from custom_components.givenergy_inverter_manager.lib.tariff.bill_days import (
    day_row,
    tariff_changes,
    tariff_for_day,
    tariff_in_effect,
    with_day,
)

# What a tariff snapshot holds: the fields that price a bill. Round figures, no supplier's.
OLD = {
    "base_rate": 0.3334,
    "base_rate_name": "Day",
    "rate_periods": [{"name": "Night", "rate": 0.16, "start": "23:00", "end": "08:00"}],
    "export_rate": 0.195,
    "standing_charge_per_day": 0.8,
    "vat_rate": 9.0,
    "bill_start_day": 16,
}
NEW = {**OLD, "base_rate": 0.40}


def _acc(**fields) -> EnergyAccumulator:
    acc = EnergyAccumulator(**fields)
    return acc


def _row(day: int) -> dict:
    return day_row(_acc(import_kwh=1.0), date(2026, 10, day))


class TestDayRow:
    def test_a_row_holds_the_day_by_rate_period(self):
        acc = _acc(
            import_kwh=10.0,
            export_kwh=2.5,
            solar_kwh=7.0,
            house_kwh=12.0,
            battery_charge_kwh=4.0,
            battery_discharge_kwh=3.0,
            grid_equivalent_load_cost=3.21,
            export_earnings=0.49,
            import_kwh_by_period={"Night": 8.0, "Day": 2.0},
            import_cost_by_period={"Night": 1.7, "Day": 0.8},
            house_kwh_by_period={"Night": 3.0, "Day": 9.0},
        )

        row = day_row(acc, date(2026, 10, 13))

        assert row == {
            "date": "2026-10-13",
            "import_kwh": 10.0,
            "export_kwh": 2.5,
            "solar_kwh": 7.0,
            "house_kwh": 12.0,
            "battery_charge_kwh": 4.0,
            "battery_discharge_kwh": 3.0,
            "import_kwh_by_period": {"Night": 8.0, "Day": 2.0},
            "import_cost_by_period": {"Night": 1.7, "Day": 0.8},
            "house_kwh_by_period": {"Night": 3.0, "Day": 9.0},
            "load_cost": 3.21,
            "export_credit": 0.49,
        }

    def test_a_period_with_nothing_in_it_is_left_out(self):
        acc = _acc(import_kwh_by_period={"Night": 0.0, "Day": 2.0})

        assert day_row(acc, date(2026, 10, 13))["import_kwh_by_period"] == {"Day": 2.0}

    def test_a_row_is_plain_json_data(self):
        import json

        json.dumps(day_row(_acc(import_kwh_by_period={"Night": 1.234567891}), date(2026, 10, 1)))


class TestRecordingTheTariff:
    def test_the_first_row_of_a_period_carries_the_tariff(self):
        days = with_day([], _row(16), OLD)

        assert days[0]["tariff"] == OLD

    def test_a_day_with_the_same_tariff_carries_none(self):
        days = with_day(with_day([], _row(16), OLD), _row(17), OLD)

        assert "tariff" not in days[1]

    def test_a_change_is_recorded_on_the_day_it_happens(self):
        days = []
        for day, tariff in ((16, OLD), (17, OLD), (18, NEW), (19, NEW)):
            days = with_day(days, _row(day), tariff)

        assert ["tariff" in row for row in days] == [True, False, True, False]
        assert tariff_changes(days) == ["2026-10-18"]

    def test_each_day_reads_the_tariff_recorded_at_or_before_it(self):
        days = []
        for day, tariff in ((16, OLD), (17, OLD), (18, NEW), (19, NEW)):
            days = with_day(days, _row(day), tariff)

        assert [tariff_for_day(days, i)["base_rate"] for i in range(4)] == [0.3334] * 2 + [0.4] * 2

    def test_a_change_back_is_recorded_too(self):
        days = []
        for day, tariff in ((16, OLD), (17, NEW), (18, OLD)):
            days = with_day(days, _row(day), tariff)

        assert tariff_changes(days) == ["2026-10-17", "2026-10-18"]

    def test_with_no_tariff_recorded_nothing_is_in_effect(self):
        assert tariff_in_effect([]) is None
        assert tariff_in_effect([_row(16)]) is None

    def test_adding_a_day_does_not_change_the_list_it_was_given(self):
        before = [_row(16)]

        with_day(before, _row(17), OLD)

        assert len(before) == 1
