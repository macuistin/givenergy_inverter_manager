"""The bill audit as markdown tables, for the markdown card that strips the HTML's styles."""

from __future__ import annotations

from datetime import date

from custom_components.givenergy_inverter_manager.core.bill_audit import (
    AuditPeriod,
    RunningPeriod,
    Totals,
    archived_period,
    bill_table,
    build_bill_audit,
    days_table,
    previous_period_audit,
    previous_period_summary,
    running_period,
    summary_table,
)
from custom_components.givenergy_inverter_manager.core.bill_days import tariff_snapshot
from custom_components.givenergy_inverter_manager.core.tariff import (
    EnergyAccumulator,
    build_tariff,
)

MINUS = "‑"
# Round numbers so every figure below can be worked out by hand: 10% discount, 10% VAT, a
# standing charge of 0.50 a day and a PSO levy of 3.00 a month.
CFG = {
    "base_rate": 0.3,
    "rate_periods": [],
    "export_rate": 0.2,
    "standing_charge_per_day": 0.5,
    "pso_levy_per_month": 3.0,
    "vat_rate": 10.0,
    "discount_rate": 10.0,
    "bill_start_day": 1,
}
TARIFF = build_tariff(CFG)

# Energy 2.00 as billed and 6.00 with no solar or battery, after the 10% discount and 10% VAT.
BILL_TOTALS = Totals(import_kwh=6.0, import_cost=1.98, export_credit=0.5, load_cost=5.94)

FIRST = {
    "date": "2031-10-01",
    "import_kwh": 3.04,
    "import_cost_by_period": {"Day": 0.99},
    "export_kwh": 1.0,
    "export_credit": 0.25,
    "house_kwh": 8.0,
    "load_cost": 2.97,
}
SUNNY = {
    "date": "2031-10-02",
    "import_kwh": 0.5,
    "import_cost_by_period": {"Day": 0.10},
    "export_kwh": 2.5,
    "export_credit": 0.50,
    "house_kwh": 4.0,
    "load_cost": 1.00,
}
LIVE = {
    "date": "2031-10-03",
    "import_kwh": 5.0,
    "import_cost_by_period": {"Night": 0.5, "Day": 0.49},
    "export_kwh": 1.0,
    "export_credit": 0.25,
    "house_kwh": 9.0,
    "load_cost": 2.97,
}


def _period(totals: Totals, rows=(), live=None, days: int = 2) -> AuditPeriod:
    return AuditPeriod("This bill period", list(rows), totals, TARIFF, "€", days, 30, live=live)


def _with_earlier(rows, live) -> Totals:
    """The recorded days plus 2.0 kWh that cost 1.10, earned 0.10 and would have cost 3.30."""
    seen = Totals.of_rows([*rows, live])
    return Totals(
        seen.import_kwh + 2.0,
        seen.import_cost + 1.10,
        seen.export_kwh + 0.5,
        seen.export_credit + 0.10,
        seen.house_kwh + 6.0,
        seen.load_cost + 3.30,
    )


class TestTheBillTable:
    def test_the_exact_table(self):
        assert bill_table(_period(BILL_TOTALS)) == (
            "| | You paid | Would have paid | Saved |\n"
            "|:--|--:|--:|--:|\n"
            "| Energy at the rates | €2.00 | €6.00 | €4.00 |\n"
            f"| Supplier discount | {MINUS}€0.20 | {MINUS}€0.60 | {MINUS}€0.40 |\n"
            "| Standing charge | €1.00 | €1.00 | €0.00 |\n"
            "| PSO levy | €0.20 | €0.20 | €0.00 |\n"
            "| VAT | €0.30 | €0.66 | €0.36 |\n"
            f"| Export credit | {MINUS}€0.50 | | €0.50 |\n"
            "| **Total** | **€2.80** | **€7.26** | **€4.46** |\n"
            "\n"
            "*Would have paid* is the same use with no solar or battery."
        )

    def test_a_negative_amount_uses_a_non_breaking_hyphen_and_no_ascii_minus(self):
        table = bill_table(_period(BILL_TOTALS))

        assert f"{MINUS}€0.50" in table
        assert "-€" not in table

    def test_the_export_credit_has_nothing_in_the_would_have_paid_column(self):
        [line] = [
            line
            for line in bill_table(_period(BILL_TOTALS)).splitlines()
            if line.startswith("| Export credit")
        ]

        assert line.split("|")[3] == " "

    def test_it_names_the_same_lines_as_the_html_bill(self):
        period = _period(BILL_TOTALS)
        _, html = build_bill_audit(period)
        names = [
            line.split("|")[1].strip().strip("*")
            for line in bill_table(period).splitlines()[2:]
            if line.startswith("|")
        ]

        assert len(names) == 7
        assert all(f">{name}<" in html for name in names)

    def test_its_total_is_the_total_in_the_sensor_state(self):
        state, _ = build_bill_audit(_period(BILL_TOTALS))

        assert state.startswith("Bill €2.80")
        assert "| **Total** | **€2.80** |" in bill_table(_period(BILL_TOTALS))


class TestTheDaysTable:
    def test_the_exact_table_newest_first_with_today_and_the_days_before_records(self):
        rows = [FIRST, SUNNY]
        period = _period(_with_earlier(rows, LIVE), rows, LIVE)

        assert days_table(period) == (
            "| Day | Imported | You paid | Would have paid | Saved |\n"
            "|:--|--:|--:|--:|--:|\n"
            "| 3 Oct (today) | 5.0 kWh | €0.74 | €2.97 | €2.23 |\n"
            f"| 2 Oct | 0.5 kWh | {MINUS}€0.40 | €1.00 | €1.40 |\n"
            "| 1 Oct | 3.0 kWh | €0.74 | €2.97 | €2.23 |\n"
            "| Before daily records | 2.0 kWh | €1.00 | €3.30 | €2.30 |\n"
            "\n"
            "You paid is the import cost less the export credit."
        )

    def test_no_before_daily_records_row_when_every_day_is_recorded(self):
        rows = [FIRST, SUNNY]
        period = _period(Totals.of_rows([*rows, LIVE]), rows, LIVE)

        assert "Before daily records" not in days_table(period)

    def test_the_running_period_labels_today(self):
        today = EnergyAccumulator(import_kwh=4.0, import_cost_by_period={"Day": 1.2})
        running = RunningPeriod([], today, today, date(2031, 10, 5), TARIFF, "€", 5, 30)

        table = days_table(running_period(running))

        assert "| 5 Oct (today) | 4.0 kWh | €1.20 |" in table
        assert "(so far)" not in table

    def test_a_period_with_no_days_is_a_sentence(self):
        assert days_table(_period(Totals())) == "No days recorded yet."


class TestThePreviousPeriod:
    def _snapshot(self) -> dict:
        return {
            "import_kwh": 6.0,
            "import_cost_by_period": {"Day": 1.98},
            "export_earnings": 0.5,
            "grid_equivalent_load_cost": 5.94,
            "days": [{**FIRST, "tariff": tariff_snapshot(CFG)}],
            "period_start": "2031-09-16T00:00:00",
            "period_end": "2031-10-15",
        }

    def test_the_exact_summary(self):
        assert summary_table(_period(BILL_TOTALS)) == (
            "| | |\n"
            "|:--|--:|\n"
            "| You paid | €2.80 |\n"
            "| Would have paid | €7.26 |\n"
            "| **Saved** | **€4.46** |\n"
            "\n"
            "*Would have paid* is the same use with no solar or battery."
        )

    def test_the_summary_and_the_period_of_an_archived_period(self):
        snap = self._snapshot()

        table, period = previous_period_summary(snap, tariff_snapshot(CFG), "€")

        assert period == "16 Sep to 15 Oct"
        assert table == summary_table(archived_period(snap, tariff_snapshot(CFG), "€"))

    def test_the_summary_matches_the_previous_bill_state(self):
        snap = self._snapshot()
        state, _ = previous_period_audit(snap, tariff_snapshot(CFG), "€")

        table, _ = previous_period_summary(snap, tariff_snapshot(CFG), "€")

        paid = state.split(" · ")[0].removeprefix("Bill ")
        assert f"| You paid | {paid} |" in table

    def test_a_snapshot_without_dates_has_a_summary_and_no_period(self):
        snap = {k: v for k, v in self._snapshot().items() if k != "period_end"}

        table, period = previous_period_summary(snap, tariff_snapshot(CFG), "€")

        assert table.startswith("| | |")
        assert period == ""

    def test_no_snapshot_is_a_sentence_and_no_period(self):
        table, period = previous_period_summary(None, tariff_snapshot(CFG), "€")

        assert table == "No audit of the last bill period was recorded."
        assert period == ""

    def test_a_snapshot_from_before_days_were_kept_is_the_same(self):
        assert previous_period_summary({"import_kwh": 4.0}, tariff_snapshot(CFG), "€") == (
            "No audit of the last bill period was recorded.",
            "",
        )
