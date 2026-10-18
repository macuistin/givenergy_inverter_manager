"""
templates.py - the text of the markdown cards that are more than an entity's state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..const import (
    ALT_HEAT_SCHEDULE_MIN_DAYS,
    ATTR_FULL_TEXT,
    CONF_CURRENCY,
    CURRENCIES,
    DEFAULT_ALT_HEAT_LABEL,
    DEFAULT_CURRENCY,
)
from ..core.reporting import PLAN_CHARGE_WORDS, PLAN_SKIP_WORDS
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


def _planned_charge_phrase(with_charge: str | None) -> str:
    """The figure with tonight's planned charge, as a template fragment, while a charge counts."""
    if not with_charge:
        return ""
    added = f"state_attr('{with_charge}', 'charge_added_pct')"
    figure = f"states('{with_charge}')"
    return (
        f"{{% if is_number({added}) and {added} | float(0) > 0 and is_number({figure}) %}}"
        f" With tonight's planned charge it should reach about "
        f"{{{{ states('{with_charge}') | float(0) | round(0) | int }}}}%."
        "{% endif %}"
    )


def survival_template(
    level: str, status: str | None, sunrise: str | None, with_charge: str | None = None
) -> str:
    """The overnight card: the plain outlook, then the explanation attribute or a sentence.

    The outlook attribute holds a phrase such as "Lasts the night". An install that lacks it
    shows the level word instead. The heading above the card already says what it is of.
    The sunrise entity is the figure without a charge. A Warning also gives the figure with
    tonight's planned charge, from the with_charge entity, while that charge adds something.
    """
    status_text = state_ref(status, ATTR_FULL_TEXT) if status else ""
    warning = (
        "The battery should last until solar starts, but only just. "
        f"Without a charge it is expected to reach {_sunrise_phrase(sunrise)}, "
        f"close to your minimum charge.{_planned_charge_phrase(with_charge)} "
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


def setup_checklist_template(progress: str) -> str:
    """The setup checklist: each required item as done or to do, then the optional ones left.

    It reads the `items` attribute of the Setup Progress sensor. Optional items that are done
    are not listed, and the others appear once as available, in smaller text.
    """
    return (
        f"{{% set items = state_attr('{progress}', 'items') or [] %}}"
        "{% for item in items if item.required %}"
        "- {{ 'Done' if item.done else 'To do' }}: {{ item.label }}\n"
        "{% endfor %}"
        "{% set open = items | rejectattr('required') | rejectattr('done')"
        " | map(attribute='label') | list %}"
        "{% if open %}\n<small>Available: {{ open | join(', ') }}</small>{% endif %}"
    )


def alt_heat_schedule_template(source: str) -> str:
    """The suggested alternative heating schedule line, read from the cheapest source sensor.

    The sensor holds alt_schedule_suggestion only while there is a schedule to suggest, and
    alt_schedule_days only from the first week of data. A Lovelace condition cannot test for an
    attribute, so the card says which of the two it is waiting on. The label comes from the
    sensor's alt_label attribute, so a change of label shows without regenerating the dashboard.
    Inside a sentence it is lower case unless it is all capitals (core/alt_heat_label.py).
    """
    return (
        f"{{% set text = state_attr('{source}', 'alt_schedule_suggestion') %}}"
        f"{{% set days = state_attr('{source}', 'alt_schedule_days') %}}"
        f"{{% set label = state_attr('{source}', 'alt_label') or '{DEFAULT_ALT_HEAT_LABEL}' %}}"
        "{% set word = label if label == label | upper else label | lower %}"
        "{% if text -%}\n"
        "{{ text }}\n"
        "{%- elif days -%}\n"
        "No regular {{ word }} schedule would save enough yet, from the last {{ days }} days of "
        "heating.\n"
        "{%- else -%}\n"
        "Still learning when the immersion heats the water at rates above {{ word }}. A "
        "suggested {{ word }} schedule appears after "
        f"{ALT_HEAT_SCHEDULE_MIN_DAYS} days.\n"
        "{%- endif %}"
    )


def alt_heat_banner_template(ready_by: str, low_water: str) -> str:
    """The banner text: one line for each trigger that says start_now.

    Both lines sit in the same card, so the banner reads right when either or both triggers
    are on. The label comes from the sensor's alt_label attribute and is lower case inside a
    sentence unless it is all capitals, as in alt_heat_schedule_template.
    """

    def line(entity: str, reason: str) -> str:
        return (
            f"{{% if is_state('{entity}', 'start_now') %}}"
            f"{{% set label = state_attr('{entity}', 'alt_label') or '{DEFAULT_ALT_HEAT_LABEL}' %}}"
            "{% set word = label if label == label | upper else label | lower %}"
            f"{reason}"
            "{% set run = state_attr('" + entity + "', 'run_minutes') %}"
            "{% if run %} A run takes about {{ run }} minutes.{% endif %}\n\n"
            "{% endif %}"
        )

    return (
        line(
            ready_by,
            "Start the {{ word }} now to have the water ready on time"
            "{% set by = state_attr('" + ready_by + "', 'ready_time') %}"
            "{% if by %} for {{ by }}{% endif %}.",
        )
        + line(
            low_water,
            "The water is close to its lower limit. Start the {{ word }} now so the immersion "
            "does not have to.",
        )
    )


def currency_symbol(cfg: dict) -> str:
    """The symbol of the configured currency, such as € or £."""
    return CURRENCIES.get(cfg.get(CONF_CURRENCY, DEFAULT_CURRENCY), "€")


def tariff_table(tariff: TariffConfig, cfg: dict) -> str:
    """Markdown table of the rates the integration prices energy with."""
    symbol = currency_symbol(cfg)
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
    symbol = currency_symbol(cfg)
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


# ── Story sentences ──────────────────────────────────────────────────────────
# Each page opens with a sentence that says what is happening, so the figures below it only
# have to back it up. They read sensors at view time, so a stored copy stays current.

# Below this many watts a flow counts as nothing, so a few watts of standby do not read as a
# source.
_FLOW_W = 50


def tonight_line_template(plan: str) -> str:
    """One line on tonight: whether the battery charges, with an icon to scan by.

    Reads the words the Tonight's Charge Plan sensor starts with, which come from the plan the
    inverter is written from, not from the held recommendation. That one can still show
    last night's charge while the plan has already skipped it.
    """
    skip = "{% set plan = states('" + plan + "') %}"
    return (
        skip
        + f"{{% if plan.startswith('{PLAN_SKIP_WORDS}') %}}"
        + '<ha-icon icon="mdi:battery-check"></ha-icon> **Tonight:** won\'t charge'
        + f"{{% elif plan.startswith('{PLAN_CHARGE_WORDS}') %}}"
        + '<ha-icon icon="mdi:battery-charging-high"></ha-icon> **Tonight:** will charge to '
        + "{{ plan.split(' ')[1] }}"
        + '{% else %}<ha-icon icon="mdi:battery-clock"></ha-icon> '
        + "**Tonight:** no plan yet{% endif %}"
    )


@dataclass(frozen=True)
class DayTotals:
    """The sensors the Today sentence reads. A missing one leaves its clause out."""

    solar: str
    forecast: str | None
    house: str | None
    self_sufficiency: str | None
    import_cost: str | None
    export_earnings: str | None


def today_story_template(day: DayTotals, symbol: str) -> str:
    """The day so far in one sentence: what solar made, what the house used, what it cost."""
    text = (
        f"{{% set solar = states('{day.solar}') | float(0) %}}"
        "**Solar made {{ solar | round(1) }} kWh**"
    )
    if day.forecast:
        text += (
            f"{{% set fc = states('{day.forecast}') | float(0) %}}"
            "{% if fc > 0 %}, {{ (solar / fc * 100) | round(0) | int }}% of the forecast{% endif %}"
        )
    text += "."
    if day.house:
        text += f" The house used {{{{ states('{day.house}') | float(0) | round(1) }}}} kWh"
        if day.self_sufficiency:
            text += (
                f", {{{{ states('{day.self_sufficiency}') | float(0) | round(0) | int }}}}% "
                "of it without the grid"
            )
        text += "."
    if day.import_cost:
        cost = f"states('{day.import_cost}') | float(0)"
        text += f" You paid {symbol}{{{{ '%.2f' | format({cost}) }}}}"
        if day.export_earnings:
            text += (
                f" and earned {symbol}"
                f"{{{{ '%.2f' | format(states('{day.export_earnings}') | float(0)) }}}} for exports"
            )
        text += "."
    return text


def tonight_headline_template(target: str, plan: str | None) -> str:
    """Whether tonight charges, in a heading, with the plan's own line under it in grey."""
    text = (
        f"{{% set plan = state_attr('{target}', 'plan') %}}"
        "### {{ 'No charge needed tonight' if plan == 'skip' else "
        f"'Charging to ' ~ states('{target}') ~ '% tonight' }}}}"
    )
    if plan:
        text += f"\n<font color='#9e9e9e'>{{{{ states('{plan}') }}}}</font>"
    return text


def tomorrow_story_template(forecast: str, target: str | None, sunrise: str | None) -> str:
    """Tomorrow's solar, the low estimate when the forecast has one, and the battery at dawn."""
    text = (
        f"{{% set kwh = states('{forecast}') | float(0) %}}"
        f"{{% set low = state_attr('{forecast}', 'estimate10') %}}"
        "**About {{ kwh | round(0) | int }} kWh of solar expected**"
        "{% if is_number(low) %}, at least {{ low | float(0) | round(0) | int }} kWh on a dull day"
        "{% endif %}."
    )
    if target and sunrise:
        text += (
            f" {{% set plan = state_attr('{target}', 'plan') %}}"
            "{{ 'No charge is planned tonight' if plan == 'skip' else "
            f"'Tonight charges to ' ~ states('{target}') ~ '%' }}}}, so the battery should start "
            f"the day at about {{{{ states('{sunrise}') | float(0) | round(0) | int }}}}%."
        )
    return text


@dataclass(frozen=True)
class WaterNow:
    """The sensors the Hot water sentence reads."""

    water: str
    target: str | None
    heater: str | None
    reason: str | None


def water_story_template(water: WaterNow) -> str:
    """The water temperature, whether the heater is on and why, without repeating the figure.

    The divert reason starts "Water already at" when the water is at its target, which the
    first sentence already says, so it is left out then.
    """
    text = f"{{% set t = states('{water.water}') | float(0) %}}**Water at {{{{ t | round(1) }}}} °C"
    if water.target:
        text += f"{{% if t >= states('{water.target}') | float(0) %}}, at its target{{% endif %}}"
    text += ".**"
    if water.heater:
        text += (
            f" {{% if states('{water.heater}') | float(0) > 0 %}}Heating now."
            "{% else %}Heater off.{% endif %}"
        )
    if water.reason:
        text += (
            f" {{% set r = state_attr('{water.reason}', 'full_text')"
            f" or states('{water.reason}') %}}"
            "{% if 'already at' not in r %}{{ r }}{% endif %}"
        )
    return text


@dataclass(frozen=True)
class ChargerNow:
    """The sensors the EV charger sentence reads."""

    power: str | None
    state: str | None
    source: str | None
    surplus: str | None
    protection: str | None


def ev_story_template(ev: ChargerNow) -> str:
    """Whether the car is charging, from what, and the battery protection's reason in grey."""
    power = f"states('{ev.power}') | float(0)" if ev.power else "0"
    state = f"{{{{ states('{ev.state}') | lower }}}}" if ev.state else "idle"
    source = f" from {{{{ states('{ev.source}') | lower }}}}" if ev.source else ""
    text = (
        f"{{% set p = {power} %}}"
        f"{{% if p > {_FLOW_W} %}}**Charging at {{{{ (p / 1000) | round(1) }}}} kW**{source}."
        f"{{% else %}}**Not charging.** The charger is {state}.{{% endif %}}"
    )
    if ev.surplus:
        text += f" Spare solar: {{{{ states('{ev.surplus}') | lower }}}}."
    if ev.protection:
        text += (
            "\n\n<font color='#9e9e9e'>"
            f"{{{{ state_attr('{ev.protection}', 'full_text') or states('{ev.protection}') }}}}"
            "</font>"
        )
    return text


def saved_template(paid: str, without: str, symbol: str) -> str:
    """What solar and the battery have taken off this bill so far, as a heading and a line."""
    return (
        f"{{% set paid = states('{paid}') | float(0) %}}"
        f"{{% set wout = states('{without}') | float(0) %}}"
        f"### Saved {symbol}{{{{ '%.2f' | format(wout - paid) }}}} so far\n"
        f"Solar and the battery have taken {symbol}{{{{ '%.2f' | format(wout - paid) }}}} off this "
        f"bill. Without them it would be {symbol}{{{{ '%.2f' | format(wout) }}}}."
    )


def plan_text_template(water: str) -> str:
    """The planned heating for the next ready time, with the cheapest source line under it.

    The planned heating sentence already names the ready time, so it is the whole first line.
    """
    return (
        f"{{% set p = state_attr('{water}', 'planned_heating') %}}"
        "{{ p or 'The planned heating shows once the water temperature is read.' }}"
    )
