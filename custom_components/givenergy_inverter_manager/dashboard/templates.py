"""
templates.py - the text of the markdown cards that are more than an entity's state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..const import (
    CONF_CURRENCY,
    CURRENCIES,
    DEFAULT_CURRENCY,
    IMMERSION_SWITCH_COOLDOWN_MINUTES,
    OIL_SCHEDULE_MIN_DAYS,
)
from ..core.tariff import TariffChange, TariffConfig, build_tariff
from .cards import state_ref


def _sunrise_phrase(sunrise: str | None) -> str:
    """Where the battery is expected to be at sunrise, as a template fragment."""
    if not sunrise:
        return "the minimum at sunrise"
    return (
        f"{{% if has_value('{sunrise}') %}}about "
        f"{{{{ states('{sunrise}') | float(0) | round(0) | int }}}}% at sunrise"
        "{% else %}the minimum at sunrise{% endif %}"
    )


def survival_template(level: str, status: str | None, sunrise: str | None) -> str:
    """The overnight card: the plain outlook, then the explanation attribute or a sentence.

    The outlook attribute holds a phrase such as "Lasts the night". An install that lacks it
    shows the level word instead. The heading above the card already says what it is of.
    """
    status_text = state_ref(status) if status else ""
    warning = (
        "The battery should last until solar starts, but only just. "
        f"It is expected to reach {_sunrise_phrase(sunrise)}, close to your minimum charge. "
        "A warning shows when the estimate is within 5 points of the minimum."
    )
    return (
        f"{{% set level = states('{level}') %}}"
        f"**{{{{ state_attr('{level}', 'outlook') or level }}}}**\n\n"
        f"{{% if state_attr('{level}', 'explanation') -%}}\n"
        f"{{{{ state_attr('{level}', 'explanation') }}}}\n"
        "{%- elif level | lower == 'warning' -%}\n"
        f"{warning}\n"
        "{%- else -%}\n"
        f"{status_text}\n"
        "{%- endif %}"
    )


def ready_by_template(sensor: str) -> str:
    """The card for the next hot water ready time, read from the water temperature sensor.

    The sensor holds ready_by, expected_ready and heating_rate_c_per_h only while ready times
    are set and scheduled heating is on. A Lovelace condition cannot test for an attribute, so
    the card itself says when there is no ready time.
    """
    return (
        f"{{% set sensor = '{sensor}' %}}"
        "{% set ready = state_attr(sensor, 'ready_by') %}"
        "{% set expected = state_attr(sensor, 'expected_ready') %}"
        "{% set rate = state_attr(sensor, 'heating_rate_c_per_h') %}"
        "{% if ready -%}\n"
        "**Next ready time {{ ready }}**\n\n"
        "{% if expected is true %}The water is expected to be at the target by then."
        "{% elif expected is false %}The water is not expected to reach the target by then."
        "{% else %}Whether the water will be ready in time is not known yet.{% endif %}"
        "{% if is_number(rate) %} Heating at about {{ rate | float(0) | round(1) }} °C an hour."
        "{% endif %}\n"
        "{%- else -%}\n"
        "No hot water ready time is set. Add one under Hot water ready by in the immersion options."
        "\n{%- endif %}"
    )


def planned_heating_template(sensor: str) -> str:
    """The planned heating sentence, read from the water temperature sensor.

    The sensor holds planned_heating only while scheduled heating is on and the water
    temperature is read. A Lovelace condition cannot test for an attribute, so the card says
    what it is waiting for.
    """
    return (
        f"{{% set text = state_attr('{sensor}', 'planned_heating') %}}"
        "{% if text -%}\n"
        "{{ text }}\n"
        "{%- else -%}\n"
        "The planned heating shows once the water temperature is read.\n"
        "{%- endif %}"
    )


def oil_schedule_template(source: str) -> str:
    """The suggested oil schedule line, read from the cheapest source sensor.

    The sensor holds oil_schedule_suggestion only while there is a schedule to suggest, and
    oil_schedule_days only from the first week of data. A Lovelace condition cannot test for an
    attribute, so the card says which of the two it is waiting on.
    """
    return (
        f"{{% set text = state_attr('{source}', 'oil_schedule_suggestion') %}}"
        f"{{% set days = state_attr('{source}', 'oil_schedule_days') %}}"
        "{% if text -%}\n"
        "{{ text }}\n"
        "{%- elif days -%}\n"
        "No regular oil schedule would save enough yet, from the last {{ days }} days of "
        "heating.\n"
        "{%- else -%}\n"
        "Still learning when the immersion heats the water at rates above oil. A suggested oil "
        f"schedule appears after {OIL_SCHEDULE_MIN_DAYS} days.\n"
        "{%- endif %}"
    )


# What two immersion settings do, in words. Their names say little on their own.
MANAGED_HELP = (
    "**Managed**: turn it on to force a heating run until the water reaches the target. "
    f"Turn it off to hold the heater off for {IMMERSION_SWITCH_COOLDOWN_MINUTES} minutes."
)
RESTART_GAP_HELP = (
    "**Restart gap**: how far the water must fall below the target before a new heating run "
    "starts."
)


def _currency_symbol(cfg: dict) -> str:
    return CURRENCIES.get(cfg.get(CONF_CURRENCY, DEFAULT_CURRENCY), "€")


def tariff_table(tariff: TariffConfig, cfg: dict) -> str:
    """Markdown table of the rates the integration prices energy with."""
    symbol = _currency_symbol(cfg)
    billed = (1 - tariff.discount_rate / 100) * (1 + tariff.vat_rate / 100)
    rows = [(tariff.base_rate_name, "all other times", tariff.base_rate)]
    rows += [(p.name, f"{p.start:%H:%M} to {p.end:%H:%M}", p.rate) for p in tariff.rate_periods]
    lines = [
        "| Period | Window | Rate per kWh | Billed per kWh |",
        "|---|---|---:|---:|",
        *(f"| {n} | {w} | {symbol}{r:.4f} | {symbol}{r * billed:.4f} |" for n, w, r in rows),
        "",
        f"Billed per kWh is the rate less the {tariff.discount_rate:g}% discount, "
        f"plus {tariff.vat_rate:g}% VAT. Where periods overlap, the cheapest applies.",
        "",
        "| Other charge | Value |",
        "|---|---:|",
        f"| Export rate | {symbol}{tariff.export_rate:.4f} per kWh |",
        f"| Standing charge | {symbol}{tariff.standing_charge:.4f} per day |",
        f"| PSO levy | {symbol}{tariff.pso_levy:.2f} per bill period |",
        f"| Bill starts on day | {tariff.bill_start_day} |",
    ]
    return "\n".join(lines)


def _day(day: date) -> str:
    """A date in words, such as 1 Nov 2026."""
    return f"{day.day} {day:%b %Y}"


def _change_row(change: TariffChange, cfg: dict) -> str:
    """One row: the date, then the base rate, the timed rates and the export rate from it."""
    symbol = _currency_symbol(cfg)
    rates = build_tariff({**cfg, **change.rates})
    windows = (
        f"{p.name} {p.start:%H:%M} to {p.end:%H:%M} {symbol}{p.rate:.4f}"
        for p in rates.rate_periods
    )
    timed = "<br>".join(windows) or "none"
    base = f"{rates.base_rate_name} {symbol}{rates.base_rate:.4f}"
    export = f"{symbol}{rates.export_rate:.4f}"
    return f"| {_day(change.effective)} | {base} | {timed} | {export} |"


def tariff_changes_table(
    changes: list[TariffChange], cfg: dict, reviewed: date | None
) -> str | None:
    """Markdown table of the rate changes that have not started, with the last review date.

    None when no change is scheduled, so a tariff with nothing coming shows no table.
    """
    if not changes:
        return None
    lines = [
        "| From | Base rate | Timed rates | Export rate per kWh |",
        "|---|---|---|---:|",
        *(_change_row(change, cfg) for change in changes),
        "",
        "A change replaces the base rate, the timed rates and the export rate from its date. "
        "The other charges stay as in the table above.",
    ]
    if reviewed is not None:
        lines += ["", f"Tariff last reviewed on {_day(reviewed)}."]
    return "\n".join(lines)


# ── Where today's energy came from ───────────────────────────────────────────


@dataclass(frozen=True)
class EnergySources:
    """The entities the "where today's energy came from" card reads.

    The self-sufficiency sensor carries the breakdown as attributes. A card that finds one
    missing falls back to the house and import totals, so it still reads on a build that
    does not set them. battery_discharge is None while the user has disabled that sensor, and
    the card then shows solar and battery as one figure.
    """

    self_sufficiency: str
    house: str
    imported: str
    battery_discharge: str | None = None


# The house line: solar and battery are split when the battery's discharge is known.
_HOUSE_LINE = (
    "House used **{{ house | round(1) }} kWh**: "
    "{% if battery_known %}solar {{ (stored - battery) | round(1) }} "
    "+ battery {{ battery | round(1) }}"
    "{% else %}solar and battery {{ stored | round(1) }}{% endif %} "
    "+ grid {{ from_grid | round(1) }}."
)
# The grid line: split into house and battery when the AC charge counter was read.
_GRID_LINE = (
    "{% if state_attr(card, 'basis') == 'ac_charge_counter' %}"
    "Grid import **{{ imported | round(1) }} kWh**: {{ from_grid | round(1) }} for the house "
    "+ {{ to_battery | round(1) }} into the battery."
    "{% else %}Grid import **{{ imported | round(1) }} kWh**. How much of it went into the "
    "battery is not known, so it all counts as used by the house.{% endif %}"
)
_MEANING = (
    "**Self-sufficiency{% if is_number(states(card)) %} {{ states(card) | float(0) | round(0) "
    "| int }}%{% endif %}** is the share of what the house used that did not come from the grid."
)

def _statements(*lines: str) -> str:
    """Template statements, one to a line, that leave no blank lines in the card."""
    return "".join(f"{{%- {line} -%}}\n" for line in lines)


# Each value is the attribute when it holds a number, else the total the card falls back to.
_SETUP = _statements(
    "set house = state_attr(card, 'house_load_kwh')",
    "set house = house if is_number(house) else states(house_entity)",
    "set imported = states(import_entity)",
    "set to_battery = state_attr(card, 'grid_to_battery_kwh')",
    "set to_battery = to_battery | float(0) if is_number(to_battery) else 0",
    "set from_grid = state_attr(card, 'from_grid_kwh')",
    "set from_grid = from_grid if is_number(from_grid) else imported",
)
_FIGURES = _statements(
    "if is_number(house) and is_number(imported)",
    "set house = house | float(0)",
    "set imported = imported | float(0)",
    "set from_grid = [from_grid | float(0), house] | min",
    "set stored = [house - from_grid, 0] | max",
    "set battery_known = battery_entity and is_number(states(battery_entity))",
    "set battery = [[states(battery_entity) | float(0), stored] | min, 0] | max",
)
_BODY = (
    f"{_SETUP}{_FIGURES}{_HOUSE_LINE}\n\n{_GRID_LINE}\n\n{_MEANING}"
    "{%- else -%}\nWaiting for today's energy totals.\n{%- endif %}"
)


def energy_sources_template(sources: EnergySources) -> str:
    """The card that says where today's energy came from, in kWh and plain words.

    House used is solar plus battery plus grid, and grid import is grid for the house plus
    grid into the battery. Energy the battery gave back counts as the battery's, whether solar
    or the grid filled it. The EV and immersion are part of the house use, so a separate card
    lists them (see energy_devices_template).
    """
    names = {
        "card": sources.self_sufficiency,
        "house_entity": sources.house,
        "import_entity": sources.imported,
        "battery_entity": sources.battery_discharge or "",
    }
    header = _statements(*(f"set {name} = '{value}'" for name, value in names.items()))
    return header + _BODY


def energy_devices_template(ev: str | None, immersion: str | None) -> str | None:
    """A line on how much of the house use went to the EV and the immersion. None with neither."""
    parts = [
        f"the {name} took {{{{ states('{entity}') | float(0) | round(1) }}}} kWh"
        for name, entity in (("EV", ev), ("immersion", immersion))
        if entity
    ]
    if not parts:
        return None
    return "Of the house use, " + " and ".join(parts) + "."
