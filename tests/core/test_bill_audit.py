"""The bill audit: days listed like a bill, and totals that equal the Bill sensors."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from custom_components.givenergy_inverter_manager.core.bill_audit import (
    AuditPeriod,
    RunningPeriod,
    Totals,
    build_bill_audit,
    current_period_audit,
    figures,
    previous_period_audit,
)
from custom_components.givenergy_inverter_manager.core.bill_days import (
    day_row,
    tariff_snapshot,
    with_day,
)
from custom_components.givenergy_inverter_manager.core.tariff import (
    EnergyAccumulator,
    build_tariff,
)
from tests.conftest import _nightboost_cfg

CFG = _nightboost_cfg()
TARIFF = build_tariff(CFG)
SNAP = tariff_snapshot(CFG)
SYMBOL = "€"


def _acc(imported: float, cost: float, export: float, credit: float, house: float, load: float):
    return EnergyAccumulator(
        import_kwh=imported,
        export_kwh=export,
        house_kwh=house,
        grid_equivalent_load_cost=load,
        export_earnings=credit,
        import_kwh_by_period={"Night": imported * 0.8, "Day": imported * 0.2},
        import_cost_by_period={"Night": cost * 0.6, "Day": cost * 0.4},
        house_kwh_by_period={"Night": house * 0.3, "Day": house * 0.7},
    )


def _days(count: int) -> list[dict]:
    rows: list[dict] = []
    for n in range(count):
        acc = _acc(10.0, 2.0, 1.0, 0.2, 12.0, 4.0)
        rows = with_day(rows, day_row(acc, date(2026, 10, 16 + n)), SNAP)
    return rows


def _month(count: int, today: EnergyAccumulator) -> EnergyAccumulator:
    month = _acc(10.0 * count, 2.0 * count, 1.0 * count, 0.2 * count, 12.0 * count, 4.0 * count)
    month.import_kwh += today.import_kwh
    month.export_kwh += today.export_kwh
    month.house_kwh += today.house_kwh
    month.export_earnings += today.export_earnings
    month.grid_equivalent_load_cost += today.grid_equivalent_load_cost
    month.import_cost_by_period["Day"] += sum(today.import_cost_by_period.values())
    return month


def _running(count: int = 3, *, recorded: int | None = None) -> RunningPeriod:
    today = _acc(5.0, 1.0, 0.5, 0.1, 6.0, 2.0)
    return RunningPeriod(
        days=_days(count if recorded is None else recorded),
        month=_month(count, today),
        today=today,
        today_date=date(2026, 10, 16 + count),
        tariff=TARIFF,
        symbol=SYMBOL,
        days_in=count + 1,
        period_days=30,
    )


class TestTheBillMatchesTheBillSensors:
    def test_the_total_is_calculate_bill_of_the_periods_import_and_export(self):
        running = _running()
        totals = Totals.of_accumulator(running.month)

        fig = figures(TARIFF, totals, running.days_in, running.period_days)
        expected = TARIFF.calculate_bill(
            TARIFF.energy_cost_from_import_cost(running.month.total_import_cost),
            running.days_in,
            running.period_days,
            running.month.export_earnings,
        )

        assert fig.actual == expected

    def test_the_bill_without_solar_has_the_whole_load_and_no_export_credit(self):
        running = _running()
        fig = figures(
            TARIFF, Totals.of_accumulator(running.month), running.days_in, running.period_days
        )

        assert fig.without.export_credit == 0.0
        assert fig.without.energy > fig.actual.energy
        assert fig.saved == pytest.approx(fig.without.total - fig.actual.total)
        assert fig.saved > 0

    def test_the_sensor_state_says_the_bill_the_bill_without_solar_and_the_saving(self):
        state, _ = current_period_audit(_running())

        assert state.startswith("Bill €")
        assert "Without solar or battery €" in state
        assert "Saved €" in state

    def test_the_total_row_is_in_the_html(self):
        _, html = current_period_audit(_running())
        fig = figures(
            TARIFF,
            Totals.of_accumulator(_running().month),
            _running().days_in,
            _running().period_days,
        )

        assert f"€{fig.actual.total:.2f}" in html
        assert f"€{fig.without.total:.2f}" in html


class TestTheDays:
    def test_each_recorded_day_and_today_get_a_row(self):
        _, html = current_period_audit(_running(3))

        for label in ("16 Oct", "17 Oct", "18 Oct"):
            assert label in html
        assert "19 Oct (so far)" in html

    def test_imports_are_listed_by_rate_period(self):
        _, html = current_period_audit(_running())

        assert "<b>10.00</b><br>Night 8.00<br>Day 2.00" in html

    def test_a_day_whose_split_is_short_of_its_import_says_so(self):
        # The per-period kWh began counting part way through the day the integration was updated.
        today = _acc(5.0, 1.0, 0.5, 0.1, 6.0, 2.0)
        today.import_kwh_by_period = {"Day": 1.5}
        running = RunningPeriod(
            days=[],
            month=today,
            today=today,
            today_date=date(2026, 10, 15),
            tariff=TARIFF,
            symbol=SYMBOL,
            days_in=30,
            period_days=30,
        )

        _, html = current_period_audit(running)

        assert "<b>5.00</b><br>Day 1.50<br>not split 3.50" in html

    def test_a_fully_split_day_has_no_not_split_line(self):
        _, html = current_period_audit(_running())

        assert "not split" not in html

    def test_days_that_were_not_recorded_show_as_one_row_that_makes_the_totals_add_up(self):
        _, html = current_period_audit(_running(5, recorded=2))

        assert "Earlier, not itemised" in html
        assert "16 Oct" in html
        assert "21 Oct (so far)" in html

    def test_no_not_itemised_row_when_every_day_is_recorded(self):
        _, html = current_period_audit(_running(3))

        assert "not itemised" not in html

    def test_a_period_with_no_days_yet_says_so_after_the_live_day(self):
        _, html = current_period_audit(_running(0))

        assert "not itemised" not in html
        assert "(so far)" in html


class TestTariffChanges:
    def test_a_change_is_named_with_its_date(self):
        running = _running(3)
        days = list(running.days)
        days[2] = {**days[2], "tariff": {**SNAP, "base_rate": 0.4}}

        _, html = current_period_audit(
            RunningPeriod(
                days,
                running.month,
                running.today,
                running.today_date,
                running.tariff,
                SYMBOL,
                running.days_in,
                running.period_days,
            )
        )

        assert "The tariff changed during this period on 2026-10-18." in html

    def test_no_note_without_a_change(self):
        _, html = current_period_audit(_running())

        assert "tariff changed" not in html


class TestThePreviousPeriod:
    def _snapshot(self) -> dict:
        month = _month(3, EnergyAccumulator())
        from custom_components.givenergy_inverter_manager.accumulation import _acc_to_dict

        return {
            **_acc_to_dict(month),
            "days": _days(3),
            "period_start": datetime(2026, 10, 16).isoformat(),
            "period_end": "2026-10-18",
        }

    def test_it_lists_its_days_and_a_bill_at_the_rates_it_was_billed_at(self):
        state, html = previous_period_audit(self._snapshot(), SNAP, SYMBOL)

        assert state.startswith("Bill €")
        assert "Previous bill period" in html
        assert "16 Oct" in html and "18 Oct" in html
        assert "(so far)" not in html

    def test_it_prices_the_fixed_charges_for_the_days_the_period_ran(self):
        snap = self._snapshot()
        totals = Totals.of_snapshot(snap)

        _, html = previous_period_audit(snap, SNAP, SYMBOL)
        standing = TARIFF.calculate_bill(0.0, 3, 3).standing_charge

        assert f"€{standing:.2f}" in html
        assert totals.import_cost > 0

    def test_a_snapshot_from_before_days_were_kept_is_said_to_have_no_audit(self):
        state, html = previous_period_audit({"import_kwh": 4.0}, SNAP, SYMBOL)

        assert state == "Not recorded"
        assert "no audit" in html

    def test_no_snapshot_is_the_same(self):
        assert previous_period_audit(None, SNAP, SYMBOL)[0] == "Not recorded"


def test_a_period_name_is_escaped():
    period = AuditPeriod("<b>x</b>", [], Totals(), TARIFF, SYMBOL, 1, 30)

    _, html = build_bill_audit(period)

    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
