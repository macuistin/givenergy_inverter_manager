"""
wizard_tariff.py - the tariff pages of the wizards: rates, timed rate rows and bill details.

The tariff is the only page with more than one screen. The first screen asks for the base rate,
the export rate and how many time-of-day rates there are besides the base rate. That count
decides how many rows the next screen has, so the add, edit and remove loop of 0.17 is gone.
Bill details (currency, base rate name, bill start day, standing charge, levy, VAT, discount)
and a dated rate change are their own screens in the options wizard.

Everything here works on plain values: the rows as the form submits them, the values stored in
the config, and text for the confirm step. It never reads the clock or a state.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from ..const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_BILL_START_DAY,
    CONF_CURRENCY,
    CONF_DISCOUNT_RATE,
    CONF_EXPORT_RATE,
    CONF_PSO_LEVY,
    CONF_RATE_PERIODS,
    CONF_STANDING_CHARGE,
    CONF_VAT_RATE,
    DEFAULT_BASE_RATE_NAME,
    DEFAULT_CURRENCY,
    TARIFF_RATE_KEYS,
)
from .tariff import TariffSubmission, build_tariff, scheduled_tariff_changes
from .wizard_model import KEY_DEFAULTS, Validation, changed_values, same_value

# The form cap. The engine has no limit, but five rows is as many as anyone enters by hand.
MAX_RATE_PERIODS = 5

# When a cheap night rate usually runs, by country, for the first row of a new tariff. A hint to
# edit, not a statement of any one tariff: suppliers differ inside one country.
NIGHT_WINDOWS: dict[str, tuple[str, str]] = {
    "IE": ("23:00", "08:00"),
    "GB": ("00:30", "07:30"),
}
DEFAULT_NIGHT_WINDOW = ("23:00", "07:00")
# Windows for rows after the first night row, so no two new rows start equal to their end.
_ROW_WINDOWS = (("17:00", "19:00"), ("11:00", "14:00"), ("14:00", "17:00"), ("19:00", "22:00"))
_ROW_NAMES = ("Night", "Peak")


def night_window(country: str | None) -> tuple[str, str]:
    """The usual cheap night window for *country* (an ISO code), else a generic one."""
    return NIGHT_WINDOWS.get((country or "").upper(), DEFAULT_NIGHT_WINDOW)


def _hhmmss(value: str) -> str:
    """HH:MM as the time selector wants it, HH:MM:SS."""
    return value if len(value) > 5 else f"{value}:00"


def rate_count(periods: Any) -> int:
    """How many time-of-day rates the saved periods hold, at most the form cap."""
    return min(len(periods), MAX_RATE_PERIODS) if isinstance(periods, list) else 0


def count_from_input(user_input: Mapping[str, Any]) -> int:
    """The rate count a tariff form was submitted with. The select sends it as text."""
    try:
        return max(0, int(user_input.get("rate_count", 0)))
    except (TypeError, ValueError):
        return 0


def default_rate_rows(
    count: int, saved: list[dict], window: tuple[str, str]
) -> list[dict[str, Any]]:
    """The rows to show: the saved ones first, then new ones with a name and a window.

    Raising the count adds blank rows (no rate, so the user has to type one). Lowering it drops
    the last ones. Times are HH:MM:SS, as the time selector wants them.
    """
    rows: list[dict[str, Any]] = []
    for index in range(count):
        if index < len(saved):
            row = saved[index]
            rows.append(
                {
                    "name": row["name"],
                    "rate": float(row["rate"]),
                    "start": _hhmmss(row["start"]),
                    "end": _hhmmss(row["end"]),
                }
            )
            continue
        rows.append(_new_row(index, window))
    return rows


def _new_row(index: int, window: tuple[str, str]) -> dict[str, Any]:
    name = _ROW_NAMES[index] if index < len(_ROW_NAMES) else f"Rate {index + 1}"
    start, end = window if index == 0 else _ROW_WINDOWS[(index - 1) % len(_ROW_WINDOWS)]
    return {"name": name, "rate": None, "start": _hhmmss(start), "end": _hhmmss(end)}


def rows_from_sections(user_input: Mapping[str, Any], count: int) -> list[dict[str, Any]]:
    """The submitted rate rows as stored periods: name, rate, start and end as HH:MM.

    A row a client left out is skipped, so a partial submission never invents one.
    """
    rows = []
    for index in range(1, count + 1):
        slot = user_input.get(f"rate_period_{index}")
        if not slot:
            continue
        rows.append(
            {
                "name": str(slot.get("name") or "").strip(),
                "rate": float(slot.get("rate") or 0.0),
                "start": str(slot.get("start") or "00:00:00")[:5],
                "end": str(slot.get("end") or "00:00:00")[:5],
            }
        )
    return rows


def rate_period_errors(periods: list[dict], base_rate_name: str = "") -> dict[str, str]:
    """Form errors for rate periods that cannot work, or an empty dict."""
    if len(periods) > MAX_RATE_PERIODS:
        return {"base": "too_many_periods"}
    if any(not p["name"] for p in periods):
        return {"base": "rate_period_name_missing"}
    if any(p["start"] == p["end"] for p in periods):
        return {"base": "rate_period_zero_length"}
    names = [p["name"].casefold() for p in periods]
    base = (base_rate_name or "").strip().casefold()
    if base:
        names.append(base)
    if len(names) != len(set(names)):
        return {"base": "rate_period_duplicate_name"}
    return {}


def validate_tariff(values: Mapping[str, Any]) -> Validation:
    """The base rate has to be above zero when there is no timed rate to cover the day."""
    if float(values.get(CONF_BASE_RATE) or 0) <= 0 and count_from_input(values) == 0:
        return Validation(errors={"base": "base_rate_required"})
    if count_from_input(values) > MAX_RATE_PERIODS:
        return Validation(errors={"base": "too_many_periods"})
    return Validation()


def validate_rates(rows: list[dict], base_rate_name: str) -> Validation:
    """Zero-length rows, a blank or repeated name, or too many rows."""
    return Validation(errors=rate_period_errors(rows, base_rate_name))


def validate_bill(values: Mapping[str, Any], periods: list[dict]) -> Validation:
    """The base rate name has to be filled in and differ from every timed rate name."""
    name = str(values.get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)).strip()
    if not name:
        return Validation(errors={"base": "base_rate_name_missing"})
    return Validation(errors=rate_period_errors(periods, name) if periods else {})


def validate_change_date(effective: date | None, today: date) -> Validation:
    """A rate change cannot start in the past: costs already recorded are not recalculated."""
    if effective is not None and effective < today:
        return Validation(errors={"base": "tariff_change_date_in_past"})
    return Validation()


def clean_tariff(values: Mapping[str, Any]) -> dict[str, Any]:
    """The rates a tariff form stores."""
    return {
        CONF_BASE_RATE: float(values[CONF_BASE_RATE]),
        CONF_EXPORT_RATE: float(values[CONF_EXPORT_RATE]),
    }


def clean_bill(values: Mapping[str, Any]) -> dict[str, Any]:
    """The bill details a form stores. A field the form did not send is left out."""
    cleaned: dict[str, Any] = {}
    if CONF_BASE_RATE_NAME in values:
        cleaned[CONF_BASE_RATE_NAME] = str(values[CONF_BASE_RATE_NAME]).strip()
    for key in (CONF_STANDING_CHARGE, CONF_PSO_LEVY, CONF_VAT_RATE, CONF_DISCOUNT_RATE):
        if key in values:
            cleaned[key] = float(values[key])
    if CONF_BILL_START_DAY in values:
        cleaned[CONF_BILL_START_DAY] = int(values[CONF_BILL_START_DAY])
    if CONF_CURRENCY in values:
        cleaned[CONF_CURRENCY] = values[CONF_CURRENCY]
    return cleaned


def tariff_submission(
    values: Mapping[str, Any],
    saved: Mapping[str, Any],
    in_force: Mapping[str, Any],
    dated: tuple[date | None, bool],
) -> TariffSubmission:
    """What the pages entered, as the request core/tariff.options_after_tariff_save takes.

    *values* is everything the tariff screens collected. Only what differs from the rates in
    force goes in. A dated change needs the complete set of unit rates, so those are filled in
    from what is in force. The same holds while a started dated change is in force and saving
    now supersedes it: the saved rates become the ones in force, so they are all written.
    """
    effective, cancel = dated
    updates = changed_values(values, in_force)
    superseding = effective is None and any(
        not same_value(in_force.get(key), saved.get(key, KEY_DEFAULTS.get(key)))
        for key in TARIFF_RATE_KEYS
    )
    if effective is not None or (updates and superseding):
        complete = {
            key: values.get(key, in_force.get(key, KEY_DEFAULTS.get(key)))
            for key in TARIFF_RATE_KEYS
        }
        updates = {**updates, **complete}
    return TariffSubmission(updates=updates, effective=effective, cancel_scheduled=cancel)


# ── Text ──────────────────────────────────────────────────────────────────────


def ordinal(day: int) -> str:
    """Return 1 as '1st', 16 as '16th'."""
    suffix = "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def periods_text(periods: list[dict]) -> str:
    """The timed rates as one line, such as Night 0.1644 (23:00 to 08:00)."""
    return ", ".join(
        f"{p['name']} {float(p['rate']):.4f} ({p['start']} to {p['end']})" for p in periods
    )


def tariff_summary(cfg: Mapping[str, Any]) -> str:
    """One paragraph stating the cheapest rate and the billing period for *cfg*."""
    try:
        tariff = build_tariff(dict(cfg))
    except (TypeError, ValueError):
        return ""
    cheapest = tariff.get_cheapest_rate()
    if any(cheapest is p for p in tariff.rate_periods):
        window = f"{cheapest.start:%H:%M} to {cheapest.end:%H:%M}"
    else:
        window = "all day"
    code = cfg.get(CONF_CURRENCY) or DEFAULT_CURRENCY
    start = tariff.bill_start_day
    if start == 1:
        bill = "Your bill runs from the 1st to the last day of the month."
    else:
        bill = f"Your bill runs from the {ordinal(start)} to the {ordinal(start - 1)}."
    return (
        f"Cheapest rate in your saved tariff: {cheapest.name} at {cheapest.rate:.4f} "
        f"{code}/kWh, {window}. {bill}"
    )


def scheduled_changes_summary(cfg: Mapping[str, Any], today: date) -> str:
    """One line for each rate change that has not started yet, or an empty string."""
    code = cfg.get(CONF_CURRENCY) or DEFAULT_CURRENCY
    lines = []
    for change in scheduled_tariff_changes(dict(cfg), today):
        rates = change.rates
        lines.append(
            f"From {change.effective.isoformat()}: {rates[CONF_BASE_RATE_NAME]} "
            f"{float(rates[CONF_BASE_RATE]):.4f}, export {float(rates[CONF_EXPORT_RATE]):.4f} "
            f"{code}/kWh, timed rates: {periods_text(rates[CONF_RATE_PERIODS]) or 'none'}."
        )
    if not lines:
        return ""
    return "Scheduled rate changes:\n" + "\n".join(f"- {line}" for line in lines)


def tariff_page_summary(cfg: Mapping[str, Any]) -> str:
    """The tariff on one line, for the options checklist and the setup confirm step."""
    if CONF_BASE_RATE not in cfg:
        return "not set yet"
    code = cfg.get(CONF_CURRENCY) or DEFAULT_CURRENCY
    timed = rate_count(cfg.get(CONF_RATE_PERIODS))
    extra = f", {timed} time-of-day rate{'s' if timed != 1 else ''}" if timed else ""
    return (
        f"{cfg.get(CONF_BASE_RATE_NAME, DEFAULT_BASE_RATE_NAME)} "
        f"{float(cfg[CONF_BASE_RATE]):.4f} {code}/kWh, export "
        f"{float(cfg.get(CONF_EXPORT_RATE, 0)):.4f}{extra}"
    )
