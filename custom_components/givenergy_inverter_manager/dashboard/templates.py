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
    IMMERSION_SWITCH_COOLDOWN_MINUTES,
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


def cheapest_source_template(source: str) -> str:
    """The cheapest way to heat the water, with the name the user gave the alternative.

    The sensor's state is `electricity`, `solar` or `alternative`, which never changes with the
    label so automations keep working. The card swaps `alternative` for the sensor's alt_label
    attribute, so it reads Oil, Gas or whatever was entered, and a new label shows at once.
    """
    return (
        f"{{% set state = states('{source}') %}}"
        f"{{% set label = state_attr('{source}', 'alt_label') or '{DEFAULT_ALT_HEAT_LABEL}' %}}"
        "**Cheapest source**\n\n"
        "{% if state == 'alternative' %}{{ label }}{% else %}{{ state | capitalize }}{% endif %}"
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


# What two immersion settings do, in words. Their names say little on their own.
MANAGED_HELP = (
    "**Heat now**: turn it on to force a heating run until the water reaches the target. "
    f"Turn it off to hold the heater off for {IMMERSION_SWITCH_COOLDOWN_MINUTES} minutes."
)
PLAN_FORECAST_CAPTION = (
    "**Plan forecast** is the forecast the charge plan uses: blended toward the low estimate "
    "and corrected by past accuracy."
)
RESTART_GAP_HELP = (
    "**Restart drop**: how far the water must fall below the target before a new heating run "
    "starts."
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


# ── Story sentences ──────────────────────────────────────────────────────────
# Each page opens with a sentence that says what is happening, so the figures below it only
# have to back it up. They read sensors at view time, so a stored copy stays current.

# Below this many watts a flow counts as nothing, so a few watts of standby do not read as a
# source.
_FLOW_W = 50


@dataclass(frozen=True)
class PowerNow:
    """The live power sensors the Right now sentence reads."""

    solar: str
    house: str
    battery: str
    grid: str


def now_story_template(power: PowerNow, target: str | None, outlook: str | None) -> str:
    """What the house runs on now and what tonight holds, in two short sentences.

    Battery power is positive while charging and grid power positive while importing, the
    integration's own convention.
    """
    text = (
        f"{{% set solar = states('{power.solar}') | float(0) %}}"
        f"{{% set house = states('{power.house}') | float(0) %}}"
        f"{{% set batt = states('{power.battery}') | float(0) %}}"
        f"{{% set grid = states('{power.grid}') | float(0) %}}"
        "{% set src = [] %}"
        f"{{% if solar > {_FLOW_W} %}}{{% set src = src + ['solar'] %}}{{% endif %}}"
        f"{{% if batt < -{_FLOW_W} %}}{{% set src = src + ['the battery'] %}}{{% endif %}}"
        f"{{% if grid > {_FLOW_W} %}}{{% set src = src + ['the grid'] %}}{{% endif %}}"
        "**{% if src %}Running on {{ src | join(' and ') }}{% else %}Nothing running{% endif %}.** "
        "House {{ (house / 1000) | round(1) }} kW"
        f"{{% if batt > {_FLOW_W} %}}, battery charging "
        "{{ (batt / 1000) | round(1) }} kW{% endif %}"
        f"{{% if grid < -{_FLOW_W} %}}, exporting "
        "{{ (-grid / 1000) | round(1) }} kW{% endif %}."
    )
    if target:
        text += (
            f" {{% set plan = state_attr('{target}', 'plan') %}}Tonight: "
            "{{ 'no charge needed' if plan == 'skip' else "
            f"'charging to ' ~ states('{target}') ~ '%' }}}}"
        )
        if outlook:
            text += (
                f", {{{{ (state_attr('{outlook}', 'outlook') or states('{outlook}')) | lower }}}}"
            )
        text += "."
    return text


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
        text += (
            f"{{% if t >= states('{water.target}') | float(0) %}}, at its target{{% endif %}}"
        )
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
