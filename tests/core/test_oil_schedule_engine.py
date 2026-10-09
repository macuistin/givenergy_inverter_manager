"""The oil schedule through the engine: what is recorded each cycle and when it is suggested.

The tariff is 0.30 by day and 0.15 from 23:00 to 08:00. The heater is 3 kW. A cycle is 30
seconds after the last, so a heater that ran all of it used 0.025 kWh.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.givenergy_inverter_manager.const import (
    OIL_BOILER_EFFICIENCY_PCT,
    OIL_KWH_PER_LITRE,
)
from custom_components.givenergy_inverter_manager.core.oil_schedule import ImmersionHeatLog
from tests.conftest import _raw, _run

CFG = {
    "base_rate": 0.30,
    "export_rate": 0.15,
    "vat_rate": 0,
    "discount_rate": 0,
    "rate_periods": [{"name": "Night", "rate": 0.15, "start": "23:00", "end": "08:00"}],
}
CYCLE = timedelta(seconds=30)
FULL_CYCLE_KWH = 3.0 * 30 / 3600
NOON = datetime(2026, 12, 15, 12, 0, 0)


def price_for(cost_per_kwh: float) -> float:
    """The price of a litre that costs this much per kWh of heat."""
    return cost_per_kwh * OIL_KWH_PER_LITRE * OIL_BOILER_EFFICIENCY_PCT / 100


OIL_PRICE = price_for(0.20)


def cycle(log, now=NOON, cfg=CFG, price=OIL_PRICE, last=True, **raw):
    """One engine cycle with the immersion on and heating from the grid, unless overridden."""
    fields = {
        "solar_power_w": 0.0,
        "battery_soc": 20.0,
        "battery_power_w": 0.0,
        "house_load_w": 3400.0,
        "grid_power_w": 3400.0,
        "immersion_on": True,
        "oil_price_per_litre": price,
    }
    fields.update(raw)
    return _run(
        raw=_raw(**fields),
        cfg=cfg,
        now=now,
        last_update_time=now - CYCLE if last else None,
        heat_log=log,
    )[0]


def fill(log: ImmersionHeatLog, days: range, hour: int = 13, kwh: float = 1.5) -> None:
    for day in days:
        log.add(datetime(2026, 12, day, hour, 30), kwh, kwh * 0.30)


class TestWhatIsRecorded:
    def test_grid_heating_is_added_to_the_local_hour_with_its_cost(self):
        log = ImmersionHeatLog()
        cycle(log, now=datetime(2026, 12, 15, 13, 10))
        (day,) = log.days
        assert day.date == "2026-12-15"
        assert day.kwh[13] == pytest.approx(FULL_CYCLE_KWH)
        assert day.cost[13] == pytest.approx(FULL_CYCLE_KWH * 0.30)

    def test_the_cost_is_the_rate_in_force_after_discount_and_vat(self):
        log = ImmersionHeatLog()
        taxed = {**CFG, "vat_rate": 10, "discount_rate": 5}
        cycle(log, cfg=taxed)
        assert log.days[0].cost[12] == pytest.approx(FULL_CYCLE_KWH * 0.30 * 0.95 * 1.10)

    def test_the_cheap_slot_rate_is_what_is_recorded_at_night(self):
        log = ImmersionHeatLog()
        cycle(log, now=datetime(2026, 12, 15, 3, 0))
        assert log.days[0].cost[3] == pytest.approx(FULL_CYCLE_KWH * 0.15)

    def test_solar_surplus_that_covers_the_heater_records_no_grid_energy(self):
        log = ImmersionHeatLog()
        cycle(log, solar_power_w=4500.0, grid_power_w=-500.0)
        assert sum(log.days[0].kwh) == pytest.approx(0.0)

    def test_only_the_part_the_surplus_did_not_cover_is_recorded(self):
        """1.5 kW of solar less the 0.4 kW the rest of the house uses leaves 1.1 of 3 kW."""
        log = ImmersionHeatLog()
        cycle(log, solar_power_w=1500.0, grid_power_w=1900.0)
        assert log.days[0].kwh[12] == pytest.approx(1.9 * 30 / 3600)

    def test_a_cycle_with_the_heater_off_still_notes_the_day(self):
        log = ImmersionHeatLog()
        cycle(log, immersion_on=False, grid_power_w=400.0, house_load_w=400.0)
        assert [d.date for d in log.days] == ["2026-12-15"]
        assert sum(log.days[0].kwh) == 0.0

    def test_energy_adds_up_across_cycles(self):
        log = ImmersionHeatLog()
        for seconds in (0, 30, 60):
            cycle(log, now=NOON + timedelta(seconds=seconds))
        assert log.days[0].kwh[12] == pytest.approx(3 * FULL_CYCLE_KWH)

    def test_the_first_cycle_has_no_interval_so_nothing_is_recorded(self):
        log = ImmersionHeatLog()
        cycle(log, last=False)
        assert log.days == []

    def test_a_gap_over_an_hour_is_not_recorded(self):
        """Home Assistant was down: the energy of the gap is not known."""
        log = ImmersionHeatLog()
        _run(
            raw=_raw(immersion_on=True, oil_price_per_litre=price_for(0.20)),
            cfg=CFG,
            now=NOON,
            last_update_time=NOON - timedelta(hours=2),
            heat_log=log,
        )
        assert log.days == []

    def test_the_record_rolls_over_at_midnight(self):
        log = ImmersionHeatLog()
        cycle(log, now=datetime(2026, 12, 14, 23, 59, 50))
        cycle(log, now=datetime(2026, 12, 15, 0, 0, 10))
        first, second = log.days
        assert (first.date, second.date) == ("2026-12-14", "2026-12-15")
        assert first.kwh[23] == pytest.approx(FULL_CYCLE_KWH)
        assert second.kwh[0] > 0.0
        assert second.kwh[23] == 0.0


class TestWithNoOilPrice:
    def test_nothing_is_recorded(self):
        log = ImmersionHeatLog()
        cycle(log, price=None)
        assert log.days == []

    def test_nothing_is_suggested_even_with_a_record(self):
        log = ImmersionHeatLog()
        fill(log, range(5, 15))
        assert cycle(log, price=None).oil_schedule is None
        assert log.days[-1].date == "2026-12-14"

    def test_without_a_record_the_engine_still_runs(self):
        data = cycle(None)
        assert data.oil_schedule is None
        assert data.water_heating_advice is not None


class TestTheSuggestion:
    def test_a_week_of_midday_top_ups_gives_a_window_before_them(self):
        log = ImmersionHeatLog()
        fill(log, range(8, 15))
        data = cycle(log)
        assert data.oil_schedule.days == 7
        assert data.oil_schedule.windows == ("12:30 to 13:00",)
        assert data.oil_schedule.saving == pytest.approx(7 * 1.5 * 0.10)

    def test_six_days_is_not_enough(self):
        log = ImmersionHeatLog()
        fill(log, range(9, 15))
        assert cycle(log).oil_schedule is None

    def test_today_in_progress_is_not_one_of_the_days(self):
        log = ImmersionHeatLog()
        fill(log, range(9, 15))
        data = cycle(log)
        assert data.oil_schedule is None
        assert log.days[-1].date == "2026-12-15"

    def test_heating_in_the_cheap_slot_gives_no_windows(self):
        log = ImmersionHeatLog()
        for day in range(5, 15):
            log.add(datetime(2026, 12, day, 3, 30), 1.5, 1.5 * 0.15)
        data = cycle(log)
        assert data.oil_schedule.days == 10
        assert data.oil_schedule.windows == ()
        assert data.oil_schedule.sentence is None

    def test_dearer_oil_gives_no_windows_for_the_whole_record_at_once(self):
        log = ImmersionHeatLog()
        fill(log, range(5, 15))
        assert cycle(log).oil_schedule.windows != ()
        assert cycle(log, price=price_for(0.40)).oil_schedule.windows == ()

    def test_the_live_suggestion_is_not_mixed_with_the_schedule(self):
        log = ImmersionHeatLog()
        fill(log, range(5, 15))
        data = cycle(log)
        assert data.oil_schedule.sentence is not None
        assert data.oil_schedule.sentence not in data.water_heating_advice.suggestion
        assert "Over the last" not in data.water_heating_advice.suggestion

    def test_the_sentence_uses_the_configured_currency(self):
        log = ImmersionHeatLog()
        fill(log, range(5, 15))
        sentence = cycle(log, cfg={**CFG, "currency": "GBP"}).oil_schedule.sentence
        assert "would have saved about £1.50 over those days" in sentence

    def test_the_days_are_counted_up_to_the_cycle_date(self):
        log = ImmersionHeatLog()
        fill(log, range(5, 15))
        assert cycle(log, now=datetime(2026, 12, 19, 12)).oil_schedule.days == 10

    def test_days_older_than_the_record_are_not_read(self):
        log = ImmersionHeatLog()
        fill(log, range(5, 15))
        assert cycle(log, now=datetime(2026, 12, 30, 12)).oil_schedule is None
