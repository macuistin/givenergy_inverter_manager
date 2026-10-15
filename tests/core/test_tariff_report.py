"""The Tariff in use report: the rates in force, built from the options each cycle."""

from __future__ import annotations

from datetime import date

from custom_components.givenergy_inverter_manager.const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_CURRENCY,
    CONF_EXPORT_RATE,
    CONF_RATE_PERIODS,
    CONF_TARIFF_CHANGES,
    CONF_TARIFF_REVIEWED_ON,
)
from custom_components.givenergy_inverter_manager.core.reporting import (
    build_tariff_html,
    build_tariff_state,
)

TODAY = date(2026, 10, 15)
CFG = {
    CONF_BASE_RATE: 0.365,
    CONF_BASE_RATE_NAME: "Day",
    CONF_RATE_PERIODS: [
        {"name": "Night", "rate": 0.18, "start": "23:00", "end": "08:00"},
        {"name": "Nightboost", "rate": 0.1056, "start": "02:00", "end": "04:00"},
    ],
    CONF_EXPORT_RATE: 0.195,
    "standing_charge_per_day": 0.8259,
    "pso_levy_per_month": 1.46,
    "vat_rate": 9.0,
    "discount_rate": 5.5,
    "bill_start_day": 16,
}


def _change(effective: str, base: float) -> dict:
    return {
        "effective": effective,
        CONF_BASE_RATE: base,
        CONF_BASE_RATE_NAME: "Day",
        CONF_RATE_PERIODS: [{"name": "Night", "rate": 0.2, "start": "23:00", "end": "08:00"}],
        CONF_EXPORT_RATE: 0.21,
    }


def test_the_state_lists_each_rate_in_force():
    assert build_tariff_state(CFG, TODAY) == "Day €0.3650 · Night €0.1800 · Nightboost €0.1056"


def test_the_html_has_every_rate_window_and_charge():
    html = build_tariff_html(CFG, TODAY)

    for text in ("Day", "all other times", "Night", "23:00 to 08:00", "Nightboost", "02:00 to 04:00"):
        assert text in html
    assert "€0.3650" in html
    assert "€0.8259 per day" in html
    assert "€1.46 per bill period" in html
    assert "Bill starts on day" in html


def test_billed_per_kwh_takes_off_the_discount_and_adds_vat():
    html = build_tariff_html(CFG, TODAY)

    assert f"€{0.365 * (1 - 0.055) * 1.09:.4f}" in html


def test_a_change_that_has_started_replaces_the_rates_in_force():
    cfg = {**CFG, CONF_TARIFF_CHANGES: [_change("2026-10-01", 0.40)]}

    assert build_tariff_state(cfg, TODAY).startswith("Day €0.4000")
    assert "Scheduled rate changes" not in build_tariff_html(cfg, TODAY)


def test_a_change_ahead_is_listed_and_does_not_change_the_rates_in_force():
    cfg = {**CFG, CONF_TARIFF_CHANGES: [_change("2026-12-01", 0.40)]}

    html = build_tariff_html(cfg, TODAY)

    assert build_tariff_state(cfg, TODAY).startswith("Day €0.3650")
    assert "Scheduled rate changes" in html
    assert "1 Dec 2026" in html
    assert "Day €0.4000" in html


def test_the_review_date_is_shown_when_there_is_one():
    cfg = {**CFG, CONF_TARIFF_REVIEWED_ON: "2026-03-09"}

    assert "Tariff last reviewed on 9 Mar 2026." in build_tariff_html(cfg, TODAY)
    assert "reviewed" not in build_tariff_html(CFG, TODAY)


def test_the_currency_symbol_follows_the_tariff():
    html = build_tariff_html({**CFG, CONF_CURRENCY: "GBP"}, TODAY)

    assert "£0.3650" in html
    assert "€" not in html


def test_a_period_name_is_escaped():
    cfg = {**CFG, CONF_RATE_PERIODS: [{"name": "<b>x</b>", "rate": 0.1, "start": "01:00", "end": "02:00"}]}

    html = build_tariff_html(cfg, TODAY)

    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
