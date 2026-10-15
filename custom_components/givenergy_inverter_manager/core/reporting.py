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

The sensor state (at most 255 chars) is independently useful in automations and
notification triggers.
"""

from __future__ import annotations

from datetime import date
from html import escape
from typing import TYPE_CHECKING, Any

from ..const import CONF_CURRENCY, CURRENCIES, DEFAULT_CURRENCY, DEFAULT_CURRENCY_SYMBOL
from .tariff import (
    TariffChange,
    TariffConfig,
    build_tariff,
    last_tariff_review,
    scheduled_tariff_changes,
    tariff_in_force,
)
from .text_state import fit_state

if TYPE_CHECKING:
    from .engine import CoordinatorData
    from .rules import ChargeDecision


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


def _table(rows: list[str]) -> str:
    return f'<table style="{_S["table"]}">' + "".join(rows) + "</table>"


def _provider_forecast_detail(data: "CoordinatorData") -> str:
    """Today's solar against the provider's own forecast, or nothing without one.

    This is the figure of the Solar forecast today (provider) and Solar vs provider forecast
    sensors. The charge plan's forecast is blended toward the pessimistic estimate and scaled
    by the accuracy correction, so it is not the figure to judge the day against.
    """
    forecast = data.solar_forecast_raw_kwh_today
    if forecast is None or forecast <= 0:
        return ""
    pct = data.today.solar_kwh / forecast * 100
    return f"Forecast: {forecast:.1f}kWh ({pct:.0f}%)"


def _today_energy_rows(data: "CoordinatorData") -> list[str]:
    t = data.today
    sym = data.currency_symbol
    peak_frac = f"{t.peak_import_fraction * 100:.0f}% at peak rate" if t.import_kwh > 0 else ""
    return [
        _section("⚡ Today's Energy"),
        _row("☀️ Solar", f"{t.solar_kwh:.2f} kWh", _provider_forecast_detail(data), _S["highlight"]),
        _row("⬇️ Import", f"{t.import_kwh:.2f} kWh", peak_frac),
        _row("⬆️ Export", f"{t.export_kwh:.2f} kWh", f"{sym}{t.export_earnings:.2f} earned"),
        _row(
            "🔋 Battery",
            f"{data.battery_soc:.0f}% SoC",
            f"↕ {t.battery_throughput_kwh:.1f} kWh cycled",
        ),
    ]


def _today_cost_rows(data: "CoordinatorData") -> list[str]:
    t = data.today
    sym = data.currency_symbol
    net = t.export_earnings - t.total_import_cost
    net_style = _S["positive"] if net >= 0 else _S["negative"]
    net_str = f"{sym}{abs(net):.2f} {'earned' if net >= 0 else 'net cost'}"
    return [
        _section("💰 Today's Costs"),
        _row(
            "Import cost",
            f"{sym}{t.total_import_cost:.2f}",
            f"Cheap {sym}{t.import_cost_cheap:.2f} · Peak {sym}{t.import_cost_peak:.2f}",
        ),
        _row("Export earnings", f"{sym}{t.export_earnings:.2f}", "", _S["positive"]),
        _row("Net position", net_str, "", net_style),
    ]


def _immersion_divert_today_row(data: "CoordinatorData") -> list[str]:
    """The immersion saving row, or nothing when there is no immersion switch."""
    if not data.immersion_configured:
        return []
    t = data.today
    sym = data.currency_symbol
    return [
        _row(
            "Immersion divert",
            f"{sym}{t.immersion_savings:.2f}" if t.immersion_savings > 0 else "—",
            f"{t.immersion_solar_kwh:.2f} kWh solar diverted" if t.immersion_solar_kwh > 0 else "",
            _S["positive"] if t.immersion_savings > 0 else _S["normal"],
        )
    ]


def _today_savings_rows(data: "CoordinatorData") -> list[str]:
    t = data.today
    sym = data.currency_symbol
    return [
        _section("💡 Integration Savings"),
        *_immersion_divert_today_row(data),
        _row("Self-sufficiency", f"{t.self_sufficiency_pct:.1f}%", "", _S["highlight"]),
        _row(
            "Accrued bill",
            f"{sym}{data.accrued_bill:.2f}",
            f"Projected: {sym}{data.projected_bill:.2f}",
        ),
    ]


def build_today_summary_html(data: "CoordinatorData") -> str:
    """
    Inline-styled HTML summary of today's energy flows, costs, and savings.

    Renders in HA Markdown card, html-template-card, and button-card.
    """
    return _table(
        _today_energy_rows(data) + _today_cost_rows(data) + _today_savings_rows(data)
    )


def build_today_summary_state(data: "CoordinatorData") -> str:
    """Short sensor state string (at most 255 chars) — useful in automations."""
    sym = data.currency_symbol
    t = data.today
    saved = f"Saved {sym}{t.immersion_savings:.2f} · " if data.immersion_configured else ""
    return fit_state(
        f"Solar {t.solar_kwh:.1f} kWh · "
        f"Import {sym}{t.total_import_cost:.2f} · "
        f"{saved}"
        f"Self-suff {t.self_sufficiency_pct:.0f}%"
    ).state


# ── Charge plan ───────────────────────────────────────────────────────────────


def _no_decision_rows() -> list[str]:
    return [
        _section("🔋 Tonight's Charge Plan"),
        _row("Status", "No charge decision yet", "Calculated before cheap rate window opens"),
    ]


def _plan_target_row(cd: "ChargeDecision") -> str:
    soc_delta = max(0, cd.target_soc - cd.current_soc)
    return _row(
        "Target SoC",
        f"{cd.target_soc}%" if not cd.skip_charge else "—",
        f"Add {soc_delta:.0f}% ({soc_delta / 100 * cd.battery_capacity:.1f} kWh)"
        if not cd.skip_charge
        else "Skipping overnight charge",
    )


def _plan_rows(cd: "ChargeDecision", sym: str, window_text: str | None = None) -> list[str]:
    decision_str = (
        "✅ Skip charge — solar will cover demand"
        if cd.skip_charge
        else f"🔌 Charge to {cd.target_soc}%"
    )
    return [
        _section("🔋 Tonight's Charge Plan"),
        _row("Decision", decision_str, "", _S["highlight"]),
        _row("Current SoC", f"{cd.current_soc:.0f}%"),
        _plan_target_row(cd),
        *([_row("Charge window", window_text)] if window_text and not cd.skip_charge else []),
        _row("Plan forecast", f"{cd.forecast_kwh:.1f} kWh"),
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


def build_charge_plan_html(data: "CoordinatorData") -> str:
    """
    Inline-styled HTML card showing tonight's charge decision and reasoning.
    """
    cd = data.charge_decision
    if cd is None:
        return _table(_no_decision_rows())
    window = data.published_charge_window
    return _table(_plan_rows(cd, data.currency_symbol, window.text if window else None))


def build_charge_plan_state(data: "CoordinatorData") -> str:
    """Short sensor state string (at most 255 chars)."""
    cd = data.charge_decision
    sym = data.currency_symbol
    if cd is None:
        return "No charge decision yet"
    if cd.skip_charge:
        return f"Skip charge · Plan forecast {cd.forecast_kwh:.1f} kWh · SoC {cd.current_soc:.0f}%"
    window = data.published_charge_window
    when = f"{window.text} · " if window is not None else ""
    return fit_state(
        f"Target {cd.target_soc}% · "
        f"{when}"
        f"Add {max(0, cd.target_soc - cd.current_soc):.0f}% · "
        f"Cost {sym}{cd.cost_to_charge:.2f}"
    ).state


# ── Tariff in use ─────────────────────────────────────────────────────────────

_TD = "padding:5px 8px;vertical-align:top;"
_TD_RIGHT = _TD + "text-align:right;font-weight:600;"
_TH = (
    "padding:5px 8px;text-align:left;font-size:11px;font-weight:700;"
    "text-transform:uppercase;letter-spacing:0.08em;color:var(--secondary-text-color);"
)


def _symbol(cfg: dict[str, Any]) -> str:
    return CURRENCIES.get(cfg.get(CONF_CURRENCY, DEFAULT_CURRENCY), DEFAULT_CURRENCY_SYMBOL)


def _day_in_words(day: date) -> str:
    return f"{day.day} {day:%b %Y}"


def _grid(headers: list[str], rows: list[list[str]]) -> str:
    """A table whose last columns are right-aligned numbers."""
    last = len(headers) - 1
    head = "".join(
        f'<th style="{_TH}{"text-align:right;" if i >= last - 1 and last > 1 else ""}">{h}</th>'
        for i, h in enumerate(headers)
    )
    body = "".join(
        f'<tr style="{_S["tr_mid"]}">'
        + "".join(
            f'<td style="{_TD_RIGHT if i >= last - 1 and last > 1 else _TD}">{cell}</td>'
            for i, cell in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    return f'<table style="{_S["table"]}"><tr>{head}</tr>{body}</table>'


def _rate_rows(tariff: TariffConfig, symbol: str) -> list[list[str]]:
    billed = (1 - tariff.discount_rate / 100) * (1 + tariff.vat_rate / 100)
    rows = [[escape(tariff.base_rate_name), "all other times", tariff.base_rate]]
    rows += [
        [escape(p.name), f"{p.start:%H:%M} to {p.end:%H:%M}", p.rate] for p in tariff.rate_periods
    ]
    return [[n, w, f"{symbol}{r:.4f}", f"{symbol}{r * billed:.4f}"] for n, w, r in rows]


def _other_charge_rows(tariff: TariffConfig, symbol: str) -> list[list[str]]:
    return [
        ["Export rate", f"{symbol}{tariff.export_rate:.4f} per kWh"],
        ["Standing charge", f"{symbol}{tariff.standing_charge:.4f} per day"],
        ["PSO levy", f"{symbol}{tariff.pso_levy:.2f} per bill period"],
        ["Bill starts on day", str(tariff.bill_start_day)],
    ]


def _change_row(change: TariffChange, cfg: dict[str, Any], symbol: str) -> list[str]:
    rates = build_tariff({**cfg, **change.rates})
    timed = "<br>".join(
        f"{escape(p.name)} {p.start:%H:%M} to {p.end:%H:%M} {symbol}{p.rate:.4f}"
        for p in rates.rate_periods
    )
    base = f"{escape(rates.base_rate_name)} {symbol}{rates.base_rate:.4f}"
    export = f"{symbol}{rates.export_rate:.4f}"
    return [_day_in_words(change.effective), base, timed or "none", export]


def build_tariff_html(cfg: dict[str, Any], today: date) -> str:
    """The tariff in force today, the other charges and the rate changes still to come.

    Built from the saved options each cycle, so a card that shows it follows a tariff change
    with no rebuild of the dashboard.
    """
    symbol = _symbol(cfg)
    tariff = build_tariff(tariff_in_force(cfg, today))
    parts = [
        f'<div style="{_S["section"]}">Tariff in use</div>',
        _grid(["Period", "Window", "Rate per kWh", "Billed per kWh"], _rate_rows(tariff, symbol)),
        f'<div style="{_S["detail"]}">Billed per kWh is the rate less the '
        f"{tariff.discount_rate:g}% discount, plus {tariff.vat_rate:g}% VAT. "
        "Where periods overlap, the cheapest applies.</div>",
        _grid(["Other charge", "Value"], _other_charge_rows(tariff, symbol)),
    ]
    if changes := scheduled_tariff_changes(cfg, today):
        parts += [
            f'<div style="{_S["section"]}">Scheduled rate changes</div>',
            _grid(
                ["From", "Base rate", "Timed rates", "Export rate per kWh"],
                [_change_row(change, cfg, symbol) for change in changes],
            ),
            f'<div style="{_S["detail"]}">A change replaces the base rate, the timed rates '
            "and the export rate from its date. The other charges stay as above.</div>",
        ]
    if reviewed := last_tariff_review(cfg):
        when = _day_in_words(reviewed)
        parts.append(f'<div style="{_S["detail"]}">Tariff last reviewed on {when}.</div>')
    return "".join(parts)


def build_tariff_state(cfg: dict[str, Any], today: date) -> str:
    """The rates in force in one line, such as `Day 0.3650 · Night 0.1800`."""
    symbol = _symbol(cfg)
    tariff = build_tariff(tariff_in_force(cfg, today))
    rates = [(tariff.base_rate_name, tariff.base_rate)]
    rates += [(p.name, p.rate) for p in tariff.rate_periods]
    return fit_state(" · ".join(f"{name} {symbol}{rate:.4f}" for name, rate in rates)).state


# ── Weekly summary ────────────────────────────────────────────────────────────


def _delta(today_val: float, yday_val: float) -> str:
    """How today compares with yesterday, or nothing when yesterday has no figure."""
    if yday_val == 0:
        return ""
    d = today_val - yday_val
    return f"({'+' if d > 0 else ''}{d:.1f} vs yday)"


def _immersion_saved_week_row(data: "CoordinatorData") -> list[str]:
    """The immersion saving row, or nothing when there is no immersion switch."""
    if not data.immersion_configured:
        return []
    sym = data.currency_symbol
    w = data.week
    return [
        _row(
            "Immersion saved",
            f"{sym}{w.immersion_savings:.2f}",
            f"{w.immersion_solar_kwh:.1f} kWh diverted",
            _S["positive"],
        )
    ]


def _week_rows(data: "CoordinatorData") -> list[str]:
    sym = data.currency_symbol
    w = data.week
    y = data.yesterday
    peak_style = _S["negative"] if w.import_kwh_peak > 2 else _S["normal"]
    return [
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
        *_immersion_saved_week_row(data),
        _row("Self-sufficiency", f"{w.self_sufficiency_pct:.1f}%", "", _S["highlight"]),
    ]


def _yesterday_rows(data: "CoordinatorData") -> list[str]:
    sym = data.currency_symbol
    y = data.yesterday
    return [
        _section("📆 Yesterday"),
        _row("Solar", f"{y.solar_kwh:.2f} kWh"),
        _row(
            "Import",
            f"{y.import_kwh:.2f} kWh",
            f"Cheap {y.import_kwh_cheap:.2f} · Peak {y.import_kwh_peak:.2f} kWh",
        ),
        _row("Net cost", f"{sym}{max(0, y.total_import_cost - y.export_earnings):.2f}"),
    ]


def _forecast_accuracy_rows(data: "CoordinatorData") -> list[str]:
    rows = []
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
    return rows


def build_week_summary_html(data: "CoordinatorData") -> str:
    """
    Inline-styled HTML comparing this week's totals against yesterday,
    with forecast accuracy if available.
    """
    return _table(_week_rows(data) + _yesterday_rows(data) + _forecast_accuracy_rows(data))


def build_week_summary_state(data: "CoordinatorData") -> str:
    """Short sensor state string (at most 255 chars)."""
    sym = data.currency_symbol
    w = data.week
    return fit_state(
        f"Solar {w.solar_kwh:.1f} kWh · "
        f"Import {sym}{w.total_import_cost:.2f} · "
        f"Self-suff {w.self_sufficiency_pct:.0f}%"
    ).state
