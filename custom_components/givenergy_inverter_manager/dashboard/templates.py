"""
templates.py - the text of the markdown cards that are more than an entity's state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from html import escape
from typing import Any

from ..const import (
    ALT_HEAT_SCHEDULE_MIN_DAYS,
    ATTR_FULL_TEXT,
    CONF_CURRENCY,
    CURRENCIES,
    DEFAULT_ALT_HEAT_LABEL,
    DEFAULT_CURRENCY,
)
from ..core.html_table import folded, html_table, unbroken
from ..core.overnight_phase import PLAN_DONE_WORDS, PLAN_WAITING_WORDS
from ..core.pictures import bar, rate_colours, rate_strip, swatch
from ..core.reporting import PLAN_CHARGE_WORDS, PLAN_SKIP_WORDS
from ..core.tariff import TariffChange, TariffConfig, build_tariff
from .cards import SAVING_HEX, state_ref


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


RUN_LIMIT_BANNER_TEXT = (
    "A scheduled run of the immersion was stopped because it reached the longest run, so the "
    "water may not have reached its target. Raise Longest immersion run in the hot water "
    "settings, or set it to 0 for no limit. This clears when the run's window closes or the "
    "water is warm enough."
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


def currency_symbol(cfg: dict[str, Any]) -> str:
    """The symbol of the configured currency, such as € or £."""
    return CURRENCIES.get(cfg.get(CONF_CURRENCY, DEFAULT_CURRENCY), "€")


def tariff_table(tariff: TariffConfig, cfg: dict[str, Any]) -> str:
    """The rates as a strip of the day over the table, with the other charges folded away."""
    return f"{rate_strip(tariff)}\n\n{tariff_rates(tariff, cfg)}"


def tariff_rates(tariff: TariffConfig, cfg: dict[str, Any]) -> str:
    """The rates table, how a billed rate is reached, and the other charges folded away."""
    symbol = currency_symbol(cfg)
    billed = (1 - tariff.discount_rate / 100) * (1 + tariff.vat_rate / 100)
    colours = rate_colours(tariff)
    rows = [(tariff.base_rate_name, "all other times", tariff.base_rate)]
    rows += [(p.name, f"{p.start:%H:%M} to {p.end:%H:%M}", p.rate) for p in tariff.rate_periods]
    rates = html_table(
        ["Period", "Window", "Rate per kWh", "Billed per kWh"],
        [
            [
                f"{swatch(colours[name])}\u00a0{escape(name)}",
                unbroken(window),
                f"{symbol}{rate:.4f}",
                f"{symbol}{rate * billed:.4f}",
            ]
            for name, window, rate in rows
        ],
        text_columns=2,
    )
    other = html_table(
        ["Other charge", "Value"],
        [
            ["Export rate", f"{symbol}{tariff.export_rate:.4f} per kWh"],
            ["Standing charge", f"{symbol}{tariff.standing_charge:.4f} per day"],
            ["PSO levy", f"{symbol}{tariff.pso_levy:.2f} per bill period"],
            ["Bill starts on day", str(tariff.bill_start_day)],
        ],
    )
    note = (
        f"Billed per kWh is the rate less the {tariff.discount_rate:g}% discount, "
        f"plus {tariff.vat_rate:g}% VAT. Where periods overlap, the cheapest applies."
    )
    return "\n\n".join([rates, note, folded("Other charges", other)])


def _day(day: date) -> str:
    """A date in words, such as 1 Nov 2026."""
    return f"{day.day} {day:%b %Y}"


def _change_row(change: TariffChange, cfg: dict[str, Any]) -> str:
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
    changes: list[TariffChange], cfg: dict[str, Any], reviewed: date | None
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
        + f"{{% elif plan.startswith('{PLAN_DONE_WORDS}') %}}"
        + '<ha-icon icon="mdi:battery-check"></ha-icon> **Overnight charge complete.** '
        + "Tonight's plan will be ready around {{ plan.split(' ')[-1] }}"
        + f'{{% elif plan.startswith("{PLAN_WAITING_WORDS}") %}}'
        + '<ha-icon icon="mdi:battery-clock"></ha-icon> '
        + "**Tonight:** the plan will be ready around {{ plan.split(' ')[-1] }}"
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
            f"{{% if has_value('{target}') and has_value('{sunrise}') %}}"
            f" {{% set plan = state_attr('{target}', 'plan') %}}"
            "{{ 'No charge is planned tonight' if plan == 'skip' else "
            f"'Tonight charges to ' ~ states('{target}') ~ '%' }}}}, so the battery should start "
            f"the day at about {{{{ states('{sunrise}') | float(0) | round(0) | int }}}}%."
            "{% endif %}"
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


OFFLINE_SENTENCE = (
    "**Charger not responding.** It may have no power or have lost its connection. "
    "Check its supply and its network."
)
# card-mod template: a red card while the charger state sensor reads offline.
OFFLINE_CARD_CSS = (
    "ha-card {{% if is_state('{entity}', 'offline') %}}"
    "background: var(--error-color); --primary-text-color: white; color: white;"
    "{{% endif %}} }}"
)


@dataclass(frozen=True)
class ChargerNow:
    """The sensors the EV charger sentence reads."""

    power: str | None
    state: str | None
    source: str | None
    surplus: str | None
    protection: str | None
    charge_now: str | None = None


def ev_story_template(ev: ChargerNow) -> str:
    """Whether the car is charging, from what, and the battery protection's reason in grey.

    A car that is not plugged in is called disconnected. Spare solar then reads as what the car
    would have had, and there is no hint to charge or pause it.
    """
    power = f"states('{ev.power}') | float(0)" if ev.power else "0"
    state = f"{{{{ states('{ev.state}') | lower }}}}" if ev.state else "idle"
    source = f" from {{{{ states('{ev.source}') | lower }}}}" if ev.source else ""
    plugged = (
        f"states('{ev.state}') | lower not in ['disconnected', 'unknown', 'unavailable']"
        if ev.state
        else "true"
    )
    offline = f"states('{ev.state}') | lower == 'offline'" if ev.state else "false"
    text = (
        f"{{% set p = {power} %}}{{% set plugged = {plugged} %}}{{% set offline = {offline} %}}"
        f"{{% if offline %}}{OFFLINE_SENTENCE}"
        f"{{% elif p > {_FLOW_W} %}}**Charging at {{{{ (p / 1000) | round(1) }}}} kW**{source}."
        "{% elif not plugged %}**Not charging.** The car is disconnected."
        f"{{% else %}}**Not charging.** The charger is {state}.{{% endif %}}"
    )
    if ev.surplus:
        text += (
            "{% if offline %}"
            f"{{% elif plugged %}} Spare solar: {{{{ states('{ev.surplus}') | lower }}}}."
            f"{{% elif is_state('{ev.surplus}', 'Available') %}} Spare solar is available and "
            "would go to the car once it is plugged in."
            "{% else %} There is no spare solar for it right now.{% endif %}"
        )
    if ev.protection:
        text += (
            "\n\n<font color='#9e9e9e'>"
            f"{{{{ state_attr('{ev.protection}', 'full_text') or states('{ev.protection}') }}}}"
            "</font>"
        )
    if ev.charge_now:
        text += (
            f"{{% if plugged and not offline and is_state('{ev.charge_now}', 'off')"
            f" and p <= {_FLOW_W} %}}"
            "\n\nTo charge anyway, turn on **Charge now** below; **Pause** stops it."
            "{% endif %}"
        )
    return text


@dataclass(frozen=True)
class BillNow:
    """The sensors of the bill period that the opening card reads. Only two are needed."""

    paid: str
    without: str
    projected: str | None = None
    days_left: str | None = None


# The purple of the bill and the amber of solar, as the bars of the opening card draw them.
_PAID_BAR = "#7e57c2"
_WITHOUT_BAR = "#ffa000"
_DEARER_BAR = "#9e9e9e"


def _heading_for(bill: BillNow, symbol: str) -> str:
    """Where the bill is heading and how long is left, as one small line. Empty without both."""
    parts = []
    if bill.projected:
        parts.append(
            f"heading for {symbol}{{{{ '%.2f' | format(states('{bill.projected}') | float(0)) }}}}"
        )
    if bill.days_left:
        parts.append(
            f"{{{{ states('{bill.days_left}') | int(0) }}}} days left in this bill period"
        )
    if not parts:
        return ""
    line = ", ".join(parts)
    return f"<font color='grey'>{line[0].upper()}{line[1:]}.</font>\n\n"


def _big(amount: str) -> str:
    """An amount in large type, the figure a card is about."""
    return f"<font size='6'><b>{amount}</b></font>"


def bill_now_template(bill: BillNow, symbol: str) -> str:
    """The bill so far in large type and the saving, over the bill with and without solar.

    Both bars share one scale, so the gap between them is the saving, read before any figure.
    """
    return (
        f"{{% set paid = states('{bill.paid}') | float(0) %}}"
        f"{{% set wout = states('{bill.without}') | float(0) %}}"
        "{% set top = [paid, wout, 0.01] | max %}"
        f"{_big(_money(symbol, 'paid'))} &nbsp;<font color='grey'>so far</font>\n\n"
        f"{_heading_for(bill, symbol)}"
        f"<font color='{SAVING_HEX}'><b>{_money(symbol, 'wout - paid')} saved</b></font> "
        "by solar and the battery so far\n\n"
        "{% set pct = (100 * paid / top) | round(1) %}"
        f"With them {_money(symbol, 'paid')}\n{bar('{{ pct }}', _PAID_BAR)}\n\n"
        "{% set pct = (100 * wout / top) | round(1) %}"
        f"Without them {_money(symbol, 'wout')}\n{bar('{{ pct }}', _WITHOUT_BAR)}"
    )


def plan_text_template(water: str) -> str:
    """The planned heating for the next ready time, with the cheapest source line under it.

    The planned heating sentence already names the ready time, so it is the whole first line.
    """
    return (
        f"{{% set p = state_attr('{water}', 'planned_heating') %}}"
        "{{ p or 'The planned heating shows once the water temperature is read.' }}"
    )


# ── Shadow tariffs ───────────────────────────────────────────────────────────
# Every figure is the same measured usage priced under another tariff. The words say less or
# more, because a bare signed figure does not say which of the two tariffs is the dearer.


@dataclass(frozen=True)
class ShadowRow:
    """One shadow tariff as the dashboard shows it: its name and its two sensors."""

    name: str
    bill: str
    difference: str | None


def _money(symbol: str, value: str) -> str:
    """A template that prints the number *value* as money."""
    return f"{symbol}{{{{ '%.2f' | format({value}) }}}}"


def _compared(row: ShadowRow, symbol: str, than: str = "") -> str:
    """The difference from the active tariff in words: less in green, more, or the same."""
    if not row.difference:
        return ""
    return (
        f"{{% set d = states('{row.difference}') | float(0) %}}"
        f"{{% if not has_value('{row.difference}') %}}not known yet"
        f"{{% elif d < 0 %}}<font color='{SAVING_HEX}'>{_money(symbol, '-d')} less{than}</font>"
        f"{{% elif d > 0 %}}{_money(symbol, 'd')} more{than}"
        "{% else %}the same{% endif %}"
    )


def shadow_verdict_template(rows: list[ShadowRow], symbol: str) -> str:
    """The answer first: which shadow tariff would have cost least, or that none would."""
    pairs = ", ".join(
        f"({json.dumps(row.name)}, states('{row.difference}') | float(0))"
        for row in rows
        if row.difference
    )
    return (
        "{% set ns = namespace(best=0, name='') %}"
        f"{{% for name, d in [{pairs}] %}}"
        "{% if d < ns.best %}{% set ns.best = d %}{% set ns.name = name %}{% endif %}"
        "{% endfor %}"
        f"### {{% if ns.name %}}{{{{ ns.name }}}} would have cost {_money(symbol, '-ns.best')} "
        "less so far{% else %}Your tariff is the cheapest so far{% endif %}\n"
        "The same measured usage, priced under each tariff. These are not bills."
    )


def _ranked_row(row: ShadowRow, symbol: str) -> str:
    """One shadow tariff as a dictionary literal the ranking template sorts by its bill."""
    known = f"has_value('{row.bill}')"
    return (
        f"{{'name': {json.dumps(escape(row.name))}, 'bill': states('{row.bill}') | float(0), "
        f"'known': {known}, 'yours': false, 'said': '{_said_key(row)}'}}"
    )


def _said_key(row: ShadowRow) -> str:
    return row.bill.rsplit(".", 1)[-1]


def _ranking_bar(symbol: str, said: dict[str, str]) -> str:
    """The name, the bill and how it compares, over a bar on the scale of the dearest."""
    words = "".join(
        f"{{% elif r.said == '{key}' %}}{text}" for key, text in said.items()
    )
    return (
        "{% if r.yours %}<b>{{ r.name }}</b> "
        f"{_money(symbol, 'r.bill')}\n{bar('{{ pct }}', _PAID_BAR)}"
        "{% elif not r.known %}<b>{{ r.name }}</b> <font color='grey'>not known yet</font>"
        "{% else %}<b>{{ r.name }}</b> "
        f"{_money(symbol, 'r.bill')} &nbsp;"
        f"{{% if false %}}{words}{{% endif %}}\n"
        f"{{% if r.bill < yours %}}{bar('{{ pct }}', SAVING_HEX)}"
        f"{{% else %}}{bar('{{ pct }}', _DEARER_BAR)}{{% endif %}}"
        "{% endif %}"
    )


def shadow_ranking_template(rows: list[ShadowRow], symbol: str) -> str:
    """Your tariff and each shadow tariff from the cheapest, each a bar on one scale."""
    first = rows[0].bill
    said = {_said_key(row): _compared(row, symbol) for row in rows}
    entries = ", ".join(_ranked_row(row, symbol) for row in rows)
    return (
        f"{{% set yours = state_attr('{first}', 'active_tariff_total') | float(0) %}}"
        "{% set rows = [{'name': 'Your tariff', 'bill': yours, 'known': true, "
        f"'yours': true, 'said': ''}}, {entries}] %}}"
        "{% set top = [rows | map(attribute='bill') | max, 0.01] | max %}"
        "{% for r in (rows | selectattr('known') | sort(attribute='bill'))"
        " + (rows | rejectattr('known') | list) %}"
        "{% set pct = (100 * r.bill / top) | round(1) %}"
        f"{_ranking_bar(symbol, said)}\n\n"
        "{% endfor %}"
    )


def shadow_coverage_template(bill: str) -> str:
    """From which day the usage was measured, and how much of the bill period that covers."""
    return (
        f"{{% set start = state_attr('{bill}', 'data_from') %}}"
        "Measured usage starts on "
        "{% if start %}{% set day = as_datetime(start) %}"
        "{{ day.day }} {{ day.strftime('%b %Y') }}{% else %}a day not known yet{% endif %}: "
        f"{{{{ state_attr('{bill}', 'days_with_data') }}}} of "
        f"{{{{ state_attr('{bill}', 'days_in_bill_period') }}}} days of this bill period are "
        "recorded. The figures are complete only when all of them are."
    )


def shadow_figure_template(row: ShadowRow, symbol: str) -> str:
    """One shadow tariff in a heading and a line: its bill so far and how it compares."""
    compared = _compared(row, symbol, " than your tariff")
    figure = _big(_money(symbol, f"states('{row.bill}') | float(0)"))
    return f"{figure} &nbsp;<font color='grey'>so far</font>\n\n{compared}"
