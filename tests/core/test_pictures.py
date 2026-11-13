"""pictures.py draws the bar and the strip of the day that the dashboard's markdown cards show."""

from __future__ import annotations

import re
from datetime import time
from urllib.parse import unquote

from custom_components.givenergy_inverter_manager.core.pictures import (
    bar,
    day_of_rates,
    rate_colours,
    rate_strip,
    swatch,
)
from custom_components.givenergy_inverter_manager.core.tariff import RatePeriod, TariffConfig


def _tariff(*periods: RatePeriod, base: float = 0.30) -> TariffConfig:
    return TariffConfig(
        rate_periods=list(periods),
        base_rate=base,
        base_rate_name="Day",
        export_rate=0.1,
        standing_charge=0.5,
        pso_levy=1.0,
        vat_rate=9.0,
        discount_rate=0.0,
        bill_start_day=1,
    )


NIGHT = RatePeriod("Night", 0.15, time(23, 0), time(8, 0))
BOOST = RatePeriod("Boost", 0.08, time(2, 0), time(4, 0))
PEAK = RatePeriod("Peak", 0.45, time(17, 0), time(19, 0))


def _svg(image: str) -> str:
    (src,) = re.findall(r'src="data:image/svg\+xml,([^"]+)"', image)
    return unquote(src)


def test_a_bar_is_an_image_the_width_of_the_card_with_its_length_left_for_the_template():
    image = bar("{{ pct }}", "#43a047")

    assert 'width="100%"' in image
    assert "width='{{ pct }}'" in _svg(image)
    assert "fill='#43a047'" in _svg(image)
    assert "<" not in re.search(r'src="([^"]*)"', image).group(1)


def test_the_day_is_split_where_a_rate_starts_or_ends_and_the_cheapest_overlap_wins():
    assert day_of_rates(_tariff(NIGHT, BOOST)) == [
        (0, 120, "Night"),
        (120, 240, "Boost"),
        (240, 480, "Night"),
        (480, 1380, "Day"),
        (1380, 1440, "Night"),
    ]


def test_a_flat_tariff_is_one_block_in_one_colour():
    tariff = _tariff()

    assert day_of_rates(tariff) == [(0, 1440, "Day")]
    assert list(rate_colours(tariff)) == ["Day"]


def test_the_cheapest_rate_is_the_greenest_and_the_dearest_the_reddest():
    colours = rate_colours(_tariff(NIGHT, PEAK))

    assert colours["Night"] == "#2e7d32"
    assert colours["Peak"] == "#f4511e"
    assert colours["Day"] not in (colours["Night"], colours["Peak"])


def test_the_strip_draws_one_block_for_each_stretch_and_labels_the_hours():
    svg = _svg(rate_strip(_tariff(NIGHT, BOOST)))

    assert svg.count("<rect") == 5
    for label in ("00:00", "06:00", "12:00", "18:00", "24:00"):
        assert label in svg


def test_a_swatch_is_a_dot_in_the_rates_colour():
    assert swatch("#2e7d32") == '<font color="#2e7d32">●</font>'
