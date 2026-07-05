"""
reporting.py — HTML report generators for GivEnergy Inverter Manager.

Each function takes a CoordinatorData snapshot and returns an HTML string
intended for a sensor's `html` attribute.

HTML uses only inline styles — no <style> blocks — so it renders correctly
in HA's built-in Markdown card (which strips <style> tags but preserves
inline styles, including CSS custom properties like var(--primary-text-color)).

Works without modification in:
  - type: markdown  content: "{{ state_attr('sensor…', 'html') }}"
  - custom:html-template-card  (HACS, full HTML support)
  - custom:button-card  description template

The sensor state (≤255 chars) is independently useful in automations and
notification triggers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import CoordinatorData


# ── Style constants — inline, HA-CSS-variable-aware ──────────────────────────

_S = {
    "table": (
        "width:100%;border-collapse:collapse;"
        "font-family:var(--primary-font-family,sans-serif);"
        "font-size:14px;"
    ),
    "tr_mid": "border-bottom:1px solid var(--divider-color,#e0e0e0);",
    "label": (
        "padding:5px 8px;"
        "color:var(--secondary-text-color);"
        "font-weight:500;width:38%;vertical-align:top;"
    ),
    "value": "padding:5px 8px;font-weight:600;width:30%;vertical-align:top;",
    "detail": (
        "padding:5px 8px;color:var(--secondary-text-color);font-size:12px;vertical-align:top;"
    ),
    "section": (
        "padding:8px 8px 2px;"
        "font-size:11px;font-weight:700;"
        "text-transform:uppercase;"
        "letter-spacing:0.08em;"
        "color:var(--secondary-text-color);"
    ),
    "positive": "color:var(--success-color,#4caf50);",
    "negative": "color:var(--error-color,#f44336);",
    "highlight": "color:var(--info-color,#03a9f4);",
    "normal": "color:var(--primary-text-color);",
}


def _row(label: str, value: str, detail: str = "", value_style: str = "") -> str:
    val_style = _S["value"] + (value_style or _S["normal"])
    detail_td = (
        f'<td style="{_S["detail"]}">{detail}</td>'
        if detail
        else f'<td style="{_S["detail"]}"></td>'
    )
    return (
        f'<tr style="{_S["tr_mid"]}">'
        + f'<td style="{_S["label"]}">{label}</td>'
        + f'<td style="{val_style}">{value}</td>'
        + detail_td
        + "</tr>"
    )


def _section(title: str) -> str:
    return f'<tr><td colspan="3" style="{_S["section"]}">{title}</td></tr>'


# ── Daily summary ─────────────────────────────────────────────────────────────


def build_today_summary_html(data: "CoordinatorData") -> str:
    """
    Inline-styled HTML summary of today's energy flows, costs, and savings.

    Renders in HA Markdown card, html-template-card, and button-card.
    """
    t = data.today
    sym = data.currency_symbol or "€"

    accuracy_str = ""
    if data.solar_forecast_kwh_today > 0:
        pct = min(200.0, t.solar_kwh / data.solar_forecast_kwh_today * 100)
        accuracy_str = f"Forecast: {data.solar_forecast_kwh_today:.1f}kWh ({pct:.0f}%)"

    peak_frac = f"{t.peak_import_fraction * 100:.0f}% at peak rate" if t.import_kwh > 0 else ""

    net = t.export_earnings - t.total_import_cost
    net_style = _S["positive"] if net >= 0 else _S["negative"]
    net_str = f"{sym}{abs(net):.2f} {'earned' if net >= 0 else 'net cost'}"

    rows = [
        _section("⚡ Today's Energy"),
        _row("☀️ Solar", f"{t.solar_kwh:.2f} kWh", accuracy_str, _S["highlight"]),
        _row("⬇️ Import", f"{t.import_kwh:.2f} kWh", peak_frac),
        _row("⬆️ Export", f"{t.export_kwh:.2f} kWh", f"{sym}{t.export_earnings:.2f} earned"),
        _row(
            "🔋 Battery",
            f"{data.battery_soc:.0f}% SoC",
            f"↕ {t.battery_throughput_kwh:.1f} kWh cycled",
        ),
        _section("💰 Today's Costs"),
        _row(
            "Import cost",
            f"{sym}{t.total_import_cost:.2f}",
            f"Cheap {sym}{t.import_cost_cheap:.2f} · Peak {sym}{t.import_cost_peak:.2f}",
        ),
        _row("Export earnings", f"{sym}{t.export_earnings:.2f}", "", _S["positive"]),
        _row("Net position", net_str, "", net_style),
        _section("💡 Integration Savings"),
        _row(
            "Immersion divert",
            f"{sym}{t.immersion_savings:.2f}" if t.immersion_savings > 0 else "—",
            f"{t.immersion_solar_kwh:.2f} kWh solar diverted" if t.immersion_solar_kwh > 0 else "",
            _S["positive"] if t.immersion_savings > 0 else _S["normal"],
        ),
        _row("Self-sufficiency", f"{t.self_sufficiency_pct:.1f}%", "", _S["highlight"]),
        _row(
            "Accrued bill",
            f"{sym}{data.accrued_bill:.2f}",
            f"Projected: {sym}{data.projected_bill:.2f}",
        ),
    ]

    return f'<table style="{_S["table"]}">' + "".join(rows) + "</table>"


def build_today_summary_state(data: "CoordinatorData") -> str:
    """Short sensor state string (≤255 chars) — useful in automations."""
    sym = data.currency_symbol or "€"
    t = data.today
    return (
        f"Solar {t.solar_kwh:.1f} kWh · "
        f"Import {sym}{t.total_import_cost:.2f} · "
        f"Saved {sym}{t.immersion_savings:.2f} · "
        f"Self-suff {t.self_sufficiency_pct:.0f}%"
    )[:255]


# ── Charge plan ───────────────────────────────────────────────────────────────


def build_charge_plan_html(data: "CoordinatorData") -> str:
    """
    Inline-styled HTML card showing tonight's charge decision and reasoning.
    """
    sym = data.currency_symbol or "€"
    cd = data.charge_decision

    if cd is None:
        return (
            f'<table style="{_S["table"]}">'
            + _section("🔋 Tonight's Charge Plan")
            + _row("Status", "No charge decision yet", "Calculated before cheap rate window opens")
            + "</table>"
        )

    decision_str = (
        "✅ Skip charge — solar will cover demand"
        if cd.skip_charge
        else f"🔌 Charge to {cd.target_soc}%"
    )
    soc_delta = max(0, cd.target_soc - cd.current_soc)

    rows = [
        _section("🔋 Tonight's Charge Plan"),
        _row("Decision", decision_str, "", _S["highlight"]),
        _row("Current SoC", f"{cd.current_soc:.0f}%"),
        _row(
            "Target SoC",
            f"{cd.target_soc}%" if not cd.skip_charge else "—",
            f"Add {soc_delta:.0f}% ({soc_delta / 100 * cd.battery_capacity:.1f} kWh)"
            if not cd.skip_charge
            else "Skipping overnight charge",
        ),
        _row("Solar forecast", f"{cd.forecast_kwh:.1f} kWh"),
        _row("Battery", f"{cd.battery_capacity:.1f} kWh capacity"),
        _row("EV plugged in", "Yes" if cd.car_plugged_in else "No"),
        _row(
            "Charge cost",
            f"{sym}{cd.cost_to_charge:.2f}" if not cd.skip_charge else "—",
            "",
            _S["positive"] if cd.skip_charge else _S["normal"],
        ),
        _section("📋 Reason"),
        _row("", cd.reason),
    ]

    return f'<table style="{_S["table"]}">' + "".join(rows) + "</table>"


def build_charge_plan_state(data: "CoordinatorData") -> str:
    """Short sensor state string (≤255 chars)."""
    cd = data.charge_decision
    sym = data.currency_symbol or "€"
    if cd is None:
        return "No charge decision yet"
    if cd.skip_charge:
        return f"Skip charge · Forecast {cd.forecast_kwh:.1f} kWh · SoC {cd.current_soc:.0f}%"
    return (
        f"Target {cd.target_soc}% · "
        f"Add {max(0, cd.target_soc - cd.current_soc):.0f}% · "
        f"Cost {sym}{cd.cost_to_charge:.2f}"
    )[:255]


# ── Weekly summary ────────────────────────────────────────────────────────────


def build_week_summary_html(data: "CoordinatorData") -> str:
    """
    Inline-styled HTML comparing this week's totals against yesterday,
    with forecast accuracy if available.
    """
    sym = data.currency_symbol or "€"
    w = data.week
    y = data.yesterday

    def _delta(today_val: float, yday_val: float) -> str:
        if yday_val == 0:
            return ""
        d = today_val - yday_val
        return f"({'+' if d > 0 else ''}{d:.1f} vs yday)"

    peak_style = _S["negative"] if w.import_kwh_peak > 2 else _S["normal"]

    rows = [
        _section("📅 This Week"),
        _row(
            "☀️ Solar",
            f"{w.solar_kwh:.1f} kWh",
            _delta(data.today.solar_kwh, y.solar_kwh),
            _S["highlight"],
        ),
        _row("⬇️ Import", f"{w.import_kwh:.1f} kWh", _delta(data.today.import_kwh, y.import_kwh)),
        _row("⬆️ Export", f"{w.export_kwh:.1f} kWh", f"{sym}{w.export_earnings:.2f} earned"),
        _row(
            "Cheap import",
            f"{w.import_kwh_cheap:.1f} kWh",
            f"{w.cheap_import_fraction * 100:.0f}% of total import",
        ),
        _row(
            "Peak import",
            f"{w.import_kwh_peak:.1f} kWh",
            f"{sym}{w.import_cost_peak:.2f} at peak rate",
            peak_style,
        ),
        _row("Import cost", f"{sym}{w.total_import_cost:.2f}"),
        _row(
            "Immersion saved",
            f"{sym}{w.immersion_savings:.2f}",
            f"{w.immersion_solar_kwh:.1f} kWh diverted",
            _S["positive"],
        ),
        _row("Self-sufficiency", f"{w.self_sufficiency_pct:.1f}%", "", _S["highlight"]),
        _section("📆 Yesterday"),
        _row("Solar", f"{y.solar_kwh:.2f} kWh"),
        _row(
            "Import",
            f"{y.import_kwh:.2f} kWh",
            f"Cheap {y.import_kwh_cheap:.2f} · Peak {y.import_kwh_peak:.2f} kWh",
        ),
        _row("Net cost", f"{sym}{max(0, y.total_import_cost - y.export_earnings):.2f}"),
    ]

    if data.yesterday_forecast_accuracy_pct > 0:
        pct = data.yesterday_forecast_accuracy_pct
        acc_style = _S["positive"] if 80 <= pct <= 120 else _S["negative"]
        rows.append(
            _row(
                "Forecast accuracy",
                f"{pct:.0f}%",
                "Within 20% = good" if 80 <= pct <= 120 else "Outside ±20%",
                acc_style,
            )
        )
    if data.forecast_accuracy_7day_avg_pct > 0:
        rows.append(_row("7-day avg accuracy", f"{data.forecast_accuracy_7day_avg_pct:.0f}%"))

    return f'<table style="{_S["table"]}">' + "".join(rows) + "</table>"


def build_week_summary_state(data: "CoordinatorData") -> str:
    """Short sensor state string (≤255 chars)."""
    sym = data.currency_symbol or "€"
    w = data.week
    return (
        f"Solar {w.solar_kwh:.1f} kWh · "
        f"Import {sym}{w.total_import_cost:.2f} · "
        f"Self-suff {w.self_sufficiency_pct:.0f}%"
    )[:255]
