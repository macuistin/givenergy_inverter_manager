"""
tomorrow_outlook.py — What the solar day the charge plan is for should cost.

The day is the one the plan simulates (core/rules.py, planned_day), run slot by slot from the
battery level tonight's charge leaves. Each slot's import is priced at the rate in force at the
start of that half hour, with the tariff in force on that day, so a dated tariff change counts.
Export earns the export rate. Tonight's charge is the plan's own cost figure, the one the
Estimated Overnight Charge Cost sensor shows. It is an estimate from the plan's model, not a bill.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from .rules import ChargeDecision, DayFlows, PlannedDay
from .tariff import TariffConfig

# U+2011, a hyphen that does not break from the amount it signs.
_MINUS = "‑"


@dataclass(frozen=True)
class OutlookInputs:
    """The plan's day and decision, and the tariff and battery floor that day has."""

    day: PlannedDay
    decision: ChargeDecision
    tariff: TariffConfig
    on: date
    floor_pct: float


@dataclass(frozen=True)
class TomorrowOutlook:
    """The projection. Money is rounded to cents, so net_cost is the sum of the lines."""

    on: date
    forecast_kwh: float
    import_kwh: float
    export_kwh: float
    import_cost: float
    export_credit: float
    charge_kwh: float
    charge_cost: float
    end_soc_pct: float
    min_soc_pct: float
    basis: str

    @property
    def net_cost(self) -> float:
        return _cents(self.import_cost + self.charge_cost - self.export_credit)


def _cents(value: float) -> float:
    # Adding 0.0 turns a rounded -0.0 into 0.0, so nothing reads as a negative zero.
    return round(value, 2) + 0.0


def _slot_start(on: date, slot: int) -> datetime:
    return datetime.combine(on, time(slot // 2, 30 * (slot % 2)))


def _import_cost(flows: DayFlows, tariff: TariffConfig, on: date) -> float:
    return sum(
        tariff.calculate_import_cost(kwh, _slot_start(on, slot))
        for slot, kwh in enumerate(flows.import_kwh)
        if kwh > 0
    )


def _start_soc_pct(decision: ChargeDecision) -> float:
    """The level after tonight: the target, or the level now when the night is skipped.

    A battery already above the target is not discharged to it, so it starts where it is.
    """
    if decision.skip_charge:
        return decision.current_soc
    return max(decision.current_soc, float(decision.target_soc))


def _charge_kwh(decision: ChargeDecision) -> float:
    if decision.skip_charge:
        return 0.0
    return max(0.0, decision.battery_capacity * (decision.target_soc - decision.current_soc) / 100)


def _basis(day: PlannedDay) -> str:
    source = "seasonal estimate" if day.seasonal_estimate else "forecast integration"
    load = "per-slot load profile" if day.per_slot_load else "flat daily average load"
    return f"Forecast {day.forecast_kwh:.1f} kWh from the {source}, the {load}."


def project_outlook(inputs: OutlookInputs) -> TomorrowOutlook:
    """Run the plan's day from the level tonight's charge leaves, and price it."""
    decision = inputs.decision
    flows = inputs.day.flows(_start_soc_pct(decision), inputs.floor_pct)
    export_kwh = sum(flows.export_kwh)
    return TomorrowOutlook(
        on=inputs.on,
        forecast_kwh=inputs.day.forecast_kwh,
        import_kwh=sum(flows.import_kwh),
        export_kwh=export_kwh,
        import_cost=_cents(_import_cost(flows, inputs.tariff, inputs.on)),
        export_credit=_cents(inputs.tariff.calculate_export_earnings(export_kwh)),
        charge_kwh=_charge_kwh(decision),
        charge_cost=_cents(decision.cost_to_charge),
        end_soc_pct=flows.end_soc_pct,
        min_soc_pct=flows.min_soc_pct,
        basis=_basis(inputs.day),
    )


def _money(amount: float, symbol: str) -> str:
    sign = _MINUS if _cents(amount) < 0 else ""
    return f"{sign}{symbol}{abs(amount):.2f}"


def outlook_table(outlook: TomorrowOutlook, symbol: str) -> str:
    """The projection as a markdown table: energy and cost per line, and the net cost."""
    lines = (
        ("From the grid", outlook.import_kwh, outlook.import_cost),
        ("Charge tonight", outlook.charge_kwh, outlook.charge_cost),
        ("To the grid", outlook.export_kwh, -outlook.export_credit),
    )
    return "\n".join(
        (
            "| | Energy | Cost |",
            "|:--|--:|--:|",
            *(f"| {name} | {kwh:.1f} kWh | {_money(cost, symbol)} |" for name, kwh, cost in lines),
            f"| **Tomorrow** | | **{_money(outlook.net_cost, symbol)}** |",
        )
    )
