"""
pictures.py: small pictures for Home Assistant's markdown card: a bar and a day of rates.

The markdown card strips inline styles and `<svg>`, and it keeps an `<img>` whose source is a
data URI. So each picture is an SVG image that scales to the card's width. A bar's length can be
a template expression, which the card fills in before it draws the picture.

Pure Python, no Home Assistant imports.
"""

from __future__ import annotations

from datetime import datetime, time
from urllib.parse import quote

from .tariff import TariffConfig

# Characters a data URI may hold as they are. Everything else is percent encoded.
_SAFE = " =:/'.,-"
# A light track behind a bar, the same in the light theme and the dark one.
_TRACK = "<rect width='100' height='8' rx='1.2' ry='4' fill='#888' fill-opacity='0.18'/>"
_LENGTH = "LENGTH"
_MINUTES_PER_DAY = 24 * 60
# Rate colours from the cheapest to the dearest, picked evenly when a tariff has fewer rates.
_RATE_COLOURS = ("#2e7d32", "#7cb342", "#c0ca33", "#ffb300", "#f4511e")
_FLAT_COLOUR = "#7e57c2"
_STRIP_W, _STRIP_BAR_H, _STRIP_H = 360, 14, 32


def _image(svg: str, height: int | None = None, length: str = "") -> str:
    """An image of *svg* the width of the card. *length* replaces LENGTH after encoding."""
    uri = "data:image/svg+xml," + quote(svg, safe=_SAFE)
    if length:
        uri = uri.replace(_LENGTH, length)
    tall = f' height="{height}"' if height else ""
    return f'<img src="{uri}" width="100%"{tall} alt="">'


def bar(length: str, colour: str) -> str:
    """A bar the width of the card, filled to *length* of 100 in *colour*.

    *length* may be a number or a template expression such as `{{ pct }}`.
    """
    fill = f"<rect width='{_LENGTH}' height='8' rx='1.2' ry='4' fill='{colour}'/>"
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 8' "
        f"preserveAspectRatio='none'>{_TRACK}{fill}</svg>"
    )
    return _image(svg, height=10, length=length)


def rate_colours(tariff: TariffConfig) -> dict[str, str]:
    """A colour for each rate name: green for the cheapest, through to red for the dearest."""
    rates = {tariff.base_rate_name: tariff.base_rate}
    for period in tariff.rate_periods:
        rates.setdefault(period.name, period.rate)
    if len(rates) == 1:
        return dict.fromkeys(rates, _FLAT_COLOUR)
    ordered = sorted(rates, key=lambda name: rates[name])
    last = len(ordered) - 1
    step = (len(_RATE_COLOURS) - 1) / last
    return {name: _RATE_COLOURS[round(index * step)] for index, name in enumerate(ordered)}


def _minutes(moment: time) -> int:
    return moment.hour * 60 + moment.minute


def day_of_rates(tariff: TariffConfig) -> list[tuple[int, int, str]]:
    """The day as (start minute, end minute, rate name), with the cheapest of overlaps."""
    edges = {0, _MINUTES_PER_DAY}
    for period in tariff.rate_periods:
        edges |= {_minutes(period.start), _minutes(period.end)}
    ordered = sorted(edges)
    spans: list[tuple[int, int, str]] = []
    for start, end in zip(ordered, ordered[1:], strict=False):
        moment = datetime(2000, 1, 1, start // 60, start % 60)
        name = tariff.get_current_rate(moment).name
        if spans and spans[-1][2] == name:
            spans[-1] = (spans[-1][0], end, name)
        else:
            spans.append((start, end, name))
    return spans


def _x(minute: int) -> float:
    return round(minute * _STRIP_W / _MINUTES_PER_DAY, 2)


def _hour_label(hour: int) -> str:
    anchor = {0: "start", 24: "end"}.get(hour, "middle")
    return (
        f"<text x='{_x(hour * 60)}' y='{_STRIP_H - 2}' font-size='11' fill='#888' "
        f"font-family='sans-serif' text-anchor='{anchor}'>{hour:02d}:00</text>"
    )


def rate_strip(tariff: TariffConfig) -> str:
    """The day from midnight to midnight, each rate in its colour, with the hours under it."""
    colours = rate_colours(tariff)
    blocks = "".join(
        f"<rect x='{_x(start)}' width='{round(_x(end) - _x(start), 2)}' "
        f"height='{_STRIP_BAR_H}' fill='{colours[name]}'/>"
        for start, end, name in day_of_rates(tariff)
    )
    labels = "".join(_hour_label(hour) for hour in (0, 6, 12, 18, 24))
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' "
        f"viewBox='0 0 {_STRIP_W} {_STRIP_H}'>{blocks}{labels}</svg>"
    )
    return _image(svg)


def swatch(colour: str) -> str:
    """A dot in *colour*, set before a rate's name to tie it to the strip."""
    return f'<font color="{colour}">●</font>'
