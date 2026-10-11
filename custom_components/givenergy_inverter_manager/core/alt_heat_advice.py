"""
alt_heat_advice.py: when to heat the water with the alternative system instead of the immersion.

Some homes heat the same cylinder another way too: an oil or gas boiler, a heat pump or solid
fuel, through a second coil. This module compares what a kWh of heat costs from each source and
says which is cheapest, so the owner can run the cheaper one. It is advice only. The integration
does not control the alternative system. The sentences call it by the user's label ("Oil",
"Gas", "Heat pump"), see alt_heat_label.py.

The sources, each as a cost per kWh of heat in the configured currency:

  * Alternative: the cost the user set, as a kWh of heat (alt_heat_cost.py). For a litre of oil
    that is the price of a litre over the heat a litre gives.
  * Electricity from the grid: the unit rate in force, after the supplier discount and VAT as the
    cost sensors apply them. The immersion turns all of it into heat, so a kWh of electricity is
    a kWh of heat.
  * Solar surplus: what the surplus would have earned if exported, the export rate. It is a
    source only while there is surplus the immersion could divert.

The cheapest source is worked out now, and over the horizon: up to the next hot water ready time
when one is set, else the next 24 hours. The hours in the next 24 when the alternative beats the
grid are listed, so the owner sees when to prefer it.

With a water temperature reading the suggestion also says what to do about the water
(alt_heat_start.py): nothing when it is at the target, when to start the alternative for the next
ready time while scheduled heating is on (the immersion then only tops up), or a short run to keep
cooling water from reaching the minimum temperature. The order is: the ready-by start, then the
keep-warm run, then the ready-by verdict when electricity or solar is cheaper, then the plain
sentence.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from ..const import (
    ALT_HEAT_ADVICE_HORIZON_HOURS,
    DEFAULT_ALT_HEAT_LABEL,
    DEFAULT_CURRENCY_SYMBOL,
)
from .alt_heat_label import LabelForms, clean_label, label_forms
from .alt_heat_start import (
    AltHeatStart,
    StartQuery,
    WaterReading,
    keep_warm_minutes,
    suggest_alt_heat_start,
)
from .immersion_ready import next_ready_at, rate_segments
from .tariff import TariffConfig
from .timeutil import elapsed_seconds, shift_real

SOURCE_ELECTRICITY = "electricity"
SOURCE_SOLAR = "solar"
SOURCE_ALTERNATIVE = "alternative"

ALL_DAY = "all day"
HORIZON_READY_BY = "ready_by"
HORIZON_NEXT_DAY = "next_24_hours"

_HORIZON = timedelta(hours=ALT_HEAT_ADVICE_HORIZON_HOURS)


@dataclass(frozen=True)
class AdviceInputs:
    """What the advice reads. alt_cost_per_kwh comes from heat_cost_per_kwh (alt_heat_cost.py).

    label is the user's word for the alternative heating, as the sentences say it. solar_surplus
    is True while there is surplus the immersion could divert. water is None when the
    temperature cannot be read. scheduled_heating is True while the immersion plans its heating
    for the ready times, which is what makes it the backstop the alternative start relies on.
    """

    tariff: TariffConfig
    now: datetime
    alt_cost_per_kwh: float
    ready_times: tuple[time, ...] = ()
    solar_surplus: bool = False
    currency_symbol: str = DEFAULT_CURRENCY_SYMBOL
    water: WaterReading | None = None
    scheduled_heating: bool = False
    label: str = DEFAULT_ALT_HEAT_LABEL


@dataclass(frozen=True)
class WaterHeatingAdvice:
    """The cheapest source now and over the horizon, with the figures behind it.

    Costs are per kWh of heat. alt_saving_per_kwh is what the alternative saves against the
    cheapest electric source now (solar surplus if there is some, else the grid), negative when
    it is dearer. alt_hours are the stretches of the next 24 hours when it beats the grid.
    alt_start is the run for the next ready time, None without one. keep_warm is the sentence
    for a short run to keep the water from cooling to the minimum, None without one. label is the
    cleaned label the sentences use.
    """

    source: str
    suggestion: str
    alt_cost_per_kwh: float
    electricity_cost_per_kwh: float
    cheapest_electricity_cost_per_kwh: float
    alt_saving_per_kwh: float
    alt_hours: tuple[str, ...]
    horizon: str
    horizon_ends: str
    cheapest_source_in_horizon: str
    alt_start: AltHeatStart | None = None
    keep_warm: str | None = None
    label: str = DEFAULT_ALT_HEAT_LABEL


@dataclass(frozen=True)
class _Span:
    """A stretch of time with one grid cost per kWh of heat."""

    start: datetime
    end: datetime
    cost: float


@dataclass(frozen=True)
class _AltRange:
    """A stretch when the alternative beats the grid, and the most it saves per kWh in it."""

    start: datetime
    end: datetime
    saving: float


@dataclass(frozen=True)
class _Picture:
    """Everything the sentence is written from."""

    inputs: AdviceInputs
    day_end: datetime
    ranges: list[_AltRange]
    source: str
    grid_now: float
    best_electric_now: float
    cheapest_stretch: _Span
    horizon_end: datetime
    horizon: str
    names: LabelForms
    start: AltHeatStart | None = None
    keep_warm: str | None = None
    ready_without_heating: datetime | None = None

    @property
    def at_target(self) -> bool:
        water = self.inputs.water
        return water is not None and water.at_target

    @property
    def symbol(self) -> str:
        return self.inputs.currency_symbol

    @property
    def alt(self) -> float:
        return self.inputs.alt_cost_per_kwh

    @property
    def start_name(self) -> str:
        """The label for the start of a sentence."""
        return self.names.start

    @property
    def inside_name(self) -> str:
        """The label inside a sentence."""
        return self.names.inside


def _day_end(now: datetime) -> datetime:
    """The instant 24 real hours on, in the clock of *now*."""
    return shift_real(now, _HORIZON)


def _spans(tariff: TariffConfig, now: datetime, end: datetime) -> list[_Span]:
    return [
        _Span(s.start, s.end, tariff.effective_import_rate(s.rate))
        for s in rate_segments(tariff, now, end)
    ]


def _horizon_end(inputs: AdviceInputs, day_end: datetime) -> tuple[datetime, str]:
    ready = next_ready_at(inputs.now, inputs.ready_times)
    if ready is None or elapsed_seconds(ready, day_end) <= 0:
        return day_end, HORIZON_NEXT_DAY
    return ready, HORIZON_READY_BY


def _clip(spans: list[_Span], end: datetime) -> list[_Span]:
    """The spans up to *end*, the last one cut short."""
    clipped = []
    for span in spans:
        if elapsed_seconds(span.start, end) <= 0:
            break
        stop = end if elapsed_seconds(end, span.end) > 0 else span.end
        clipped.append(_Span(span.start, stop, span.cost))
    return clipped


def _cheapest(grid: float, alt: float, solar: float | None) -> str:
    """The cheapest source. A tie goes to solar, then the grid: the alternative needs a saving."""
    options = [(SOURCE_ELECTRICITY, grid), (SOURCE_ALTERNATIVE, alt)]
    if solar is not None:
        options.insert(0, (SOURCE_SOLAR, solar))
    return min(options, key=lambda option: option[1])[0]


def _alt_ranges(spans: list[_Span], alt: float) -> list[_AltRange]:
    """The stretches when the alternative is cheaper than the grid, adjacent spans joined."""
    ranges: list[_AltRange] = []
    for span in spans:
        if span.cost <= alt:
            continue
        saving = span.cost - alt
        if ranges and ranges[-1].end == span.start:
            last = ranges[-1]
            ranges[-1] = _AltRange(last.start, span.end, max(last.saving, saving))
        else:
            ranges.append(_AltRange(span.start, span.end, saving))
    return ranges


def _cheapest_stretch(spans: list[_Span]) -> _Span:
    """The first stretch at the lowest grid cost, joined with the spans after it at that cost."""
    lowest = min(span.cost for span in spans)
    first = next(i for i, span in enumerate(spans) if span.cost == lowest)
    end = spans[first].end
    for span in spans[first + 1 :]:
        if span.cost != lowest or span.start != end:
            break
        end = span.end
    return _Span(spans[first].start, end, lowest)


def _alt_hours(ranges: list[_AltRange], now: datetime, day_end: datetime) -> tuple[str, ...]:
    if len(ranges) == 1 and ranges[0].start == now and ranges[0].end == day_end:
        return (ALL_DAY,)
    return tuple(f"{r.start:%H:%M} to {r.end:%H:%M}" for r in ranges)


def _money(symbol: str, value: float) -> str:
    """A figure per kWh to two places, to three when two would show a real saving as nothing."""
    text = f"{value:.2f}"
    if value > 0 and text == "0.00":
        text = f"{value:.3f}"
    return f"{symbol}{text}"


_AT_TARGET = "The water is already at the target, so there is nothing to heat."


def _action(picture: _Picture, text: str) -> str:
    """What to do with the water: nothing when it is already at the target."""
    return _AT_TARGET if picture.at_target else text


def _alt_sentence(picture: _Picture) -> str:
    current = picture.ranges[0]
    ends_later = elapsed_seconds(current.end, picture.day_end) > 0
    until = f"until {current.end:%H:%M}" if ends_later else "for the next 24 hours"
    saving = _money(picture.symbol, picture.best_electric_now - picture.alt)
    sentence = (
        f"{picture.start_name} is cheaper than electricity {until} "
        f"(saves about {saving} per kWh of heat). "
        + _action(picture, f"Heat the water with the {picture.inside_name} system now.")
    )
    stretch = picture.cheapest_stretch
    if stretch.cost < picture.alt and not picture.at_target:
        cost = _money(picture.symbol, stretch.cost)
        sentence += (
            f" If the water can wait, electricity is cheapest from {stretch.start:%H:%M} "
            f"to {stretch.end:%H:%M} ({cost} per kWh of heat)."
        )
    return sentence


def _solar_sentence(picture: _Picture) -> str:
    export = _money(picture.symbol, picture.inputs.tariff.export_rate)
    return (
        f"Solar surplus is the cheapest source now, at the export rate of {export} per kWh "
        "of heat. " + _action(picture, "Heat the water with the immersion.")
    )


def _electricity_sentence(picture: _Picture) -> str:
    if not picture.ranges:
        return f"Electricity is cheaper than {picture.inside_name} for the next 24 hours. " + (
            _action(picture, "Heat the water with the immersion.")
        )
    first = picture.ranges[0]
    saving = _money(picture.symbol, first.saving)
    return (
        "Electricity is the cheapest source now. "
        f"{picture.start_name} is cheaper than electricity from "
        f"{first.start:%H:%M} to {first.end:%H:%M} "
        f"(saves up to {saving} per kWh of heat)."
    )


_SENTENCES = {
    SOURCE_ALTERNATIVE: _alt_sentence,
    SOURCE_SOLAR: _solar_sentence,
    SOURCE_ELECTRICITY: _electricity_sentence,
}


def _on_the_day(moment: datetime, now: datetime) -> str:
    return f"{moment:%H:%M}" + ("" if moment.date() == now.date() else " tomorrow")


def _ready_prefix(ready_at: datetime, now: datetime) -> str:
    if ready_at.date() == now.date():
        return f"For the {ready_at:%H:%M} ready time"
    return f"For tomorrow's {ready_at:%H:%M} ready time"


def _start_sentence(picture: _Picture, start: AltHeatStart) -> str:
    """The start for the ready time. start.start_by is set."""
    now = picture.inputs.now
    saving = _money(picture.symbol, start.saving_per_kwh)
    run = f"(about {start.run_minutes} minutes)"
    if start.late:
        return (
            f"{_ready_prefix(start.ready_at, now)}: turn the {picture.inside_name} water heating "
            f"on now {run}. It is too late for the {picture.inside_name} to finish before the "
            f"immersion has to start, so the immersion will also run. "
            f"Saves up to {saving} per kWh of heat."
        )
    when = _on_the_day(start.start_by, now)
    return (
        f"{_ready_prefix(start.ready_at, now)}: turn the {picture.inside_name} water heating "
        f"on at {when} {run}. The immersion will only top up. "
        f"Saves about {saving} per kWh of heat."
    )


def _cheaper_than_alt_sentence(picture: _Picture, start: AltHeatStart) -> str:
    name = "solar surplus" if start.by_solar else "electricity"
    return (
        f"{_ready_prefix(start.ready_at, picture.inputs.now)}: {name} is cheaper than "
        f"{picture.inside_name}, so the immersion will heat the water."
    )


def _no_heating_sentence(picture: _Picture, ready_at: datetime) -> str:
    prefix = _ready_prefix(ready_at, picture.inputs.now)
    return f"{prefix}: the water is expected to be ready with no heating needed."


def _suggestion(picture: _Picture) -> str:
    """The sentence. The ready-by start comes first, then the keep-warm run."""
    start = picture.start
    if start is not None and start.start_by is not None:
        return _start_sentence(picture, start)
    if picture.keep_warm is not None:
        return picture.keep_warm
    if picture.ready_without_heating is not None:
        return _no_heating_sentence(picture, picture.ready_without_heating)
    if start is not None:
        return _cheaper_than_alt_sentence(picture, start)
    return _SENTENCES[picture.source](picture)


def _ready_start(inputs: AdviceInputs) -> AltHeatStart | None:
    """The run for the next ready time. It needs the immersion plan as its backstop."""
    ready = next_ready_at(inputs.now, inputs.ready_times)
    if inputs.water is None or not inputs.scheduled_heating or ready is None:
        return None
    solar = inputs.tariff.export_rate if inputs.solar_surplus else None
    query = StartQuery(inputs.tariff, inputs.now, inputs.water, inputs.alt_cost_per_kwh, solar)
    return suggest_alt_heat_start(query, ready)


def _ready_without_heating(inputs: AdviceInputs) -> datetime | None:
    """The next ready time when the water is below the target yet needs no heating for it."""
    ready = next_ready_at(inputs.now, inputs.ready_times)
    water = inputs.water
    if water is None or not inputs.scheduled_heating or ready is None:
        return None
    return None if water.at_target or water.needs_heating else ready


def _keep_warm(inputs: AdviceInputs, grid_now: float, names: LabelForms) -> str | None:
    """The sentence for a short run while the water cools to the minimum, else None."""
    water, alt = inputs.water, inputs.alt_cost_per_kwh
    if water is None or inputs.solar_surplus:
        return None
    minutes = keep_warm_minutes(water, grid_now, alt)
    if minutes is None:
        return None
    symbol = inputs.currency_symbol
    return (
        f"Water is at {water.temp:.1f}°C, close to the {water.min_temp:g}°C minimum. "
        f"{names.start} is cheaper than the grid now ({_money(symbol, alt)} against "
        f"{_money(symbol, grid_now)} per kWh of heat): run the {names.inside} water heating "
        f"for about {minutes} minutes to avoid an electric top-up."
    )


def _picture(inputs: AdviceInputs) -> _Picture:
    now, alt = inputs.now, inputs.alt_cost_per_kwh
    day_end = _day_end(now)
    spans = _spans(inputs.tariff, now, day_end)
    horizon_end, horizon = _horizon_end(inputs, day_end)
    solar = inputs.tariff.export_rate if inputs.solar_surplus else None
    grid_now = spans[0].cost
    names = label_forms(inputs.label)
    return _Picture(
        inputs=inputs,
        day_end=day_end,
        ranges=_alt_ranges(spans, alt),
        source=_cheapest(grid_now, alt, solar),
        grid_now=grid_now,
        best_electric_now=grid_now if solar is None else min(grid_now, solar),
        cheapest_stretch=_cheapest_stretch(_clip(spans, horizon_end)),
        horizon_end=horizon_end,
        horizon=horizon,
        names=names,
        start=_ready_start(inputs),
        keep_warm=_keep_warm(inputs, grid_now, names),
        ready_without_heating=_ready_without_heating(inputs),
    )


def advise_water_heating(inputs: AdviceInputs) -> WaterHeatingAdvice:
    """Which source is cheapest to heat the water now and over the horizon, and why."""
    picture = _picture(inputs)
    stretch = picture.cheapest_stretch
    solar = inputs.tariff.export_rate if inputs.solar_surplus else None
    return WaterHeatingAdvice(
        source=picture.source,
        suggestion=_suggestion(picture),
        alt_cost_per_kwh=picture.alt,
        electricity_cost_per_kwh=picture.grid_now,
        cheapest_electricity_cost_per_kwh=stretch.cost,
        alt_saving_per_kwh=picture.best_electric_now - picture.alt,
        alt_hours=_alt_hours(picture.ranges, inputs.now, picture.day_end),
        horizon=picture.horizon,
        horizon_ends=f"{picture.horizon_end:%H:%M}",
        cheapest_source_in_horizon=_cheapest(stretch.cost, picture.alt, solar),
        alt_start=picture.start,
        keep_warm=picture.keep_warm,
        label=clean_label(inputs.label),
    )
