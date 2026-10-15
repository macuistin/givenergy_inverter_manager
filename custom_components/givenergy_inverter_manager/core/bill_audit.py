"""
bill_audit.py: a bill period laid out day by day, the way a supplier bill reads.

Two tables and a bill. The first lists each day with what it imported in each rate period, what
that cost at the billed rates, what it exported and earned, and what the house used. The second
is the bill: energy, supplier discount, standing charge, PSO levy, VAT, export credit and the
total, set beside the same bill for the same use with no solar and no battery.

The totals come from the period's own accumulator, the one the Bill sensors read, and go through
TariffConfig.calculate_bill, so the audit total is the Bill sensors' total. A day that was not
recorded, for example before this was added, shows as one "not itemised" row that makes the
rows add up to the totals.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from html import escape
from typing import Any

from .bill_days import day_row, tariff_changes, tariff_in_effect
from .reporting import _S, _TD, _TD_RIGHT, _TH
from .tariff import BillBreakdown, EnergyAccumulator, TariffConfig, build_tariff
from .text_state import fit_state

_EPSILON_COST = 0.005
_EPSILON_KWH = 0.05


@dataclass(frozen=True)
class Totals:
    """The six figures of a period that the bill is built from."""

    import_kwh: float = 0.0
    import_cost: float = 0.0
    export_kwh: float = 0.0
    export_credit: float = 0.0
    house_kwh: float = 0.0
    load_cost: float = 0.0

    @classmethod
    def of_accumulator(cls, acc: EnergyAccumulator) -> Totals:
        return cls(
            acc.import_kwh,
            acc.total_import_cost,
            acc.export_kwh,
            acc.export_earnings,
            acc.house_kwh,
            acc.grid_equivalent_load_cost,
        )

    @classmethod
    def of_snapshot(cls, snap: Mapping[str, Any]) -> Totals:
        costs = snap.get("import_cost_by_period", {})
        return cls(
            float(snap.get("import_kwh", 0.0)),
            sum(float(v) for v in costs.values()),
            float(snap.get("export_kwh", 0.0)),
            float(snap.get("export_earnings", 0.0)),
            float(snap.get("house_kwh", 0.0)),
            float(snap.get("grid_equivalent_load_cost", 0.0)),
        )

    @classmethod
    def of_rows(cls, rows: Sequence[Mapping[str, Any]]) -> Totals:
        return cls(
            sum(r.get("import_kwh", 0.0) for r in rows),
            sum(sum(r.get("import_cost_by_period", {}).values()) for r in rows),
            sum(r.get("export_kwh", 0.0) for r in rows),
            sum(r.get("export_credit", 0.0) for r in rows),
            sum(r.get("house_kwh", 0.0) for r in rows),
            sum(r.get("load_cost", 0.0) for r in rows),
        )

    def minus(self, other: Totals) -> Totals:
        return Totals(
            self.import_kwh - other.import_kwh,
            self.import_cost - other.import_cost,
            self.export_kwh - other.export_kwh,
            self.export_credit - other.export_credit,
            self.house_kwh - other.house_kwh,
            self.load_cost - other.load_cost,
        )

    @property
    def is_empty(self) -> bool:
        return (
            abs(self.import_cost) < _EPSILON_COST
            and abs(self.load_cost) < _EPSILON_COST
            and abs(self.export_credit) < _EPSILON_COST
            and abs(self.import_kwh) < _EPSILON_KWH
            and abs(self.house_kwh) < _EPSILON_KWH
            and abs(self.export_kwh) < _EPSILON_KWH
        )


@dataclass(frozen=True)
class AuditPeriod:
    """One bill period to lay out."""

    title: str
    rows: Sequence[Mapping[str, Any]]
    totals: Totals
    tariff: TariffConfig
    symbol: str
    days: int
    period_days: int
    live: Mapping[str, Any] | None = None
    changes: Sequence[str] = ()


@dataclass(frozen=True)
class Figures:
    """The bill as billed, the same use with no solar or battery, and the difference."""

    actual: BillBreakdown
    without: BillBreakdown

    @property
    def saved(self) -> float:
        return self.without.total - self.actual.total


def figures(tariff: TariffConfig, totals: Totals, days: int, period_days: int) -> Figures:
    """Both bills through calculate_bill. The second has the whole load and no export credit."""
    actual = tariff.calculate_bill(
        tariff.energy_cost_from_import_cost(totals.import_cost),
        days,
        period_days,
        totals.export_credit,
    )
    without = tariff.calculate_bill(
        tariff.energy_cost_from_import_cost(totals.load_cost), days, period_days, 0.0
    )
    return Figures(actual, without)


def _money(symbol: str, value: float) -> str:
    sign = "-" if value < -_EPSILON_COST else ""
    return f"{sign}{symbol}{abs(value):.2f}"


def _imported(row: Mapping[str, Any]) -> str:
    """The day's import in kWh, then the part of it by rate period.

    The split began later than the totals on the day the integration was updated, so a day can
    hold more import than its periods add up to. The rest is shown as "not split", so a figure
    is never shown next to a cost that it does not match.
    """
    total = float(row.get("import_kwh", 0.0))
    split = row.get("import_kwh_by_period", {})
    lines = [f"<b>{total:.2f}</b>"]
    lines += [f"{escape(name)} {kwh:.2f}" for name, kwh in split.items()]
    rest = total - sum(split.values())
    if rest > _EPSILON_KWH:
        lines.append(f"not split {rest:.2f}")
    return "<br>".join(lines)


def _label(row: Mapping[str, Any], *, live: bool) -> str:
    try:
        day = date.fromisoformat(str(row["date"]))
        text = f"{day.day} {day:%b}"
    except (KeyError, ValueError):
        text = "-"
    return f"{text} (so far)" if live else text


def _day_cells(row: Mapping[str, Any], symbol: str, label: str) -> list[str]:
    imported = sum(row.get("import_cost_by_period", {}).values())
    return [
        label,
        _imported(row),
        _money(symbol, imported),
        f"{row.get('export_kwh', 0.0):.2f}",
        _money(symbol, row.get("export_credit", 0.0)),
        f"{row.get('house_kwh', 0.0):.2f}",
        _money(symbol, row.get("load_cost", 0.0)),
    ]


def _remainder_cells(rest: Totals, symbol: str) -> list[str]:
    return [
        "Earlier, not itemised",
        f"{rest.import_kwh:.2f}",
        _money(symbol, rest.import_cost),
        f"{rest.export_kwh:.2f}",
        _money(symbol, rest.export_credit),
        f"{rest.house_kwh:.2f}",
        _money(symbol, rest.load_cost),
    ]


def _table(headers: list[str], rows: list[list[str]], *, bold_last: bool = False) -> str:
    head = "".join(
        f'<th style="{_TH}{"" if i == 0 else "text-align:right;"}">{h}</th>'
        for i, h in enumerate(headers)
    )
    body = []
    for n, row in enumerate(rows):
        weight = "font-weight:700;" if bold_last and n == len(rows) - 1 else ""
        cells = "".join(
            f'<td style="{_TD if i == 0 else _TD_RIGHT}{weight}">{cell}</td>'
            for i, cell in enumerate(row)
        )
        body.append(f'<tr style="{_S["tr_mid"]}">{cells}</tr>')
    return f'<table style="{_S["table"]}"><tr>{head}</tr>{"".join(body)}</table>'


def _note(text: str) -> str:
    return f'<div style="{_S["detail"]}">{text}</div>'


def _bill_rows(period: AuditPeriod, fig: Figures) -> list[list[str]]:
    s = period.symbol
    a, w = fig.actual, fig.without
    lines = [
        ("Energy at the rates", a.energy, w.energy),
        ("Supplier discount", -a.supplier_saving, -w.supplier_saving),
        ("Standing charge", a.standing_charge, w.standing_charge),
        ("PSO levy", a.pso_levy, w.pso_levy),
        ("VAT", a.vat, w.vat),
        ("Export credit", -a.export_credit, -w.export_credit),
        ("Total", a.total, w.total),
    ]
    return [
        [name, _money(s, billed), _money(s, none), _money(s, none - billed)]
        for name, billed, none in lines
    ]


def build_bill_audit(period: AuditPeriod) -> tuple[str, str]:
    """The sensor state and the HTML for one bill period."""
    s = period.symbol
    rows = [_day_cells(row, s, _label(row, live=False)) for row in period.rows]
    seen = Totals.of_rows(period.rows)
    if period.live is not None:
        rows.append(_day_cells(period.live, s, _label(period.live, live=True)))
        seen = Totals.of_rows([*period.rows, period.live])
    rest = period.totals.minus(seen)
    if not rest.is_empty:
        rows.insert(0, _remainder_cells(rest, s))
    fig = figures(period.tariff, period.totals, period.days, period.period_days)
    headers = ["Day", "Imported kWh", "Cost", "Exported kWh", "Credit", "House kWh", "Without"]
    parts = [
        f'<div style="{_S["section"]}">{escape(period.title)}</div>',
        _table(headers, rows) if rows else _note("No days recorded yet."),
        f'<div style="{_S["section"]}">Bill</div>',
        _table(
            ["", "As billed", "No solar or battery", "Saved"],
            _bill_rows(period, fig),
            bold_last=True,
        ),
    ]
    if period.changes:
        dates = ", ".join(period.changes)
        parts.append(
            _note(
                f"The tariff changed during this period on {dates}. Each day's cost uses the "
                "rates in force that day. The charges and VAT use the tariff in force now."
            )
        )
    parts.append(
        _note(
            "Without is what the house used would have cost from the grid at the rates in "
            "force when it was used, with no solar and no battery."
        )
    )
    state = fit_state(
        f"Bill {_money(s, fig.actual.total)} · Without solar or battery "
        f"{_money(s, fig.without.total)} · Saved {_money(s, fig.saved)}"
    ).state
    return state, "".join(parts)


def live_row(acc: EnergyAccumulator, day: date) -> dict[str, Any]:
    """Today so far, in the shape of a stored row."""
    return day_row(acc, day)


@dataclass(frozen=True)
class RunningPeriod:
    """What the audit of the running bill period needs from the accumulators."""

    days: Sequence[Mapping[str, Any]]
    month: EnergyAccumulator
    today: EnergyAccumulator
    today_date: date
    tariff: TariffConfig
    symbol: str
    days_in: int
    period_days: int


def current_period_audit(running: RunningPeriod) -> tuple[str, str]:
    """The audit of the bill period that is running."""
    period = AuditPeriod(
        "This bill period",
        rows=running.days,
        totals=Totals.of_accumulator(running.month),
        tariff=running.tariff,
        symbol=running.symbol,
        days=running.days_in,
        period_days=running.period_days,
        live=live_row(running.today, running.today_date),
        changes=tariff_changes(running.days),
    )
    return build_bill_audit(period)


def previous_period_audit(
    snapshot: Mapping[str, Any] | None, fallback: dict[str, Any], symbol: str
) -> tuple[str, str]:
    """The audit of the bill period that ended last, from its archived snapshot.

    A snapshot from before the days were kept has no days and no dates, and is reported as such.
    """
    unavailable = "Not recorded"
    note = _note("The bill before this one was archived before days were kept, so it has no audit.")
    if not snapshot or "days" not in snapshot:
        return unavailable, f'<div style="{_S["section"]}">Previous bill period</div>{note}'
    days = [row for row in snapshot["days"] if isinstance(row, dict)]
    stored = tariff_in_effect(days) or fallback
    try:
        length = (
            date.fromisoformat(str(snapshot["period_end"]))
            - date.fromisoformat(str(snapshot["period_start"])[:10])
        ).days + 1
    except (KeyError, ValueError):
        length = len(days)
    period = AuditPeriod(
        "Previous bill period",
        rows=days,
        totals=Totals.of_snapshot(snapshot),
        tariff=build_tariff(stored),
        symbol=symbol,
        days=max(length, 1),
        period_days=max(length, 1),
        changes=tariff_changes(days),
    )
    return build_bill_audit(period)
