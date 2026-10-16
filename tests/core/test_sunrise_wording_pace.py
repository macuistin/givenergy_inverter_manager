"""The words of the night outlook quote the SoC at sunrise the sensor publishes.

Estimated SoC at Sunrise Without a Charge moves no faster than the battery can
(core/sunrise_hold.py). The reason and the explanation quoted the calculated figure from before
that pacing. With a battery pause from 23:00 to 08:00 the daytime window is wholly paused, so
the calculated figure equals the SoC. When solar stops counting at dusk the window becomes now to
08:00 and the calculated figure fell 15 to 20 points in one cycle, while the sensor ramped down
over half an hour. The explanation then disagreed with the sensor and with its own summary.

The daytime window now starts when solar is expected to stop (20:00 with no forecast shape), so
the figure still steps at dusk when solar stops earlier, as it does at 18:00 here.

The verdict and a shortfall stay on the calculated figure, so a real shortfall shows at once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

import pytest

from custom_components.givenergy_inverter_manager import sensor_values as sv
from custom_components.givenergy_inverter_manager.const import SOLAR_DAY_DEBOUNCE_MINUTES
from custom_components.givenergy_inverter_manager.core.battery_pause import PauseWindow
from custom_components.givenergy_inverter_manager.core.solar_day import HeldSolarDay
from custom_components.givenergy_inverter_manager.core.sunrise_hold import HeldSunrise
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run

PAUSE = PauseWindow(time(23, 0), time(8, 0))
CAPACITY_KWH = 19.0
START = datetime(2026, 10, 16, 12, 0)
END = datetime(2026, 10, 16, 22, 0)
DUSK = datetime(2026, 10, 16, 18, 0)
STEP = timedelta(seconds=30)

# The figure without a charge, in every form the words give it.
EXPLANATION_FIGURE = re.compile(r"(?:Estimated SoC at sunrise: |expected to reach about )(\d+)%")
REASON_FIGURE = re.compile(r"Estimated SoC at sunrise: (\d+)%")
SHORTFALL = re.compile(r"Estimated shortfall: \d+\.\dkWh before solar starts")


@dataclass(frozen=True)
class Evening:
    """One evening: the SoC at dusk, the daily load and the inverter that paces the sensor."""

    dusk_soc: float
    daily_load_kwh: float
    inverter_w: float


def _soc(evening: Evening, now: datetime) -> float:
    hours_after_dusk = max(0.0, (now - DUSK).total_seconds() / 3600)
    return evening.dusk_soc - hours_after_dusk * evening.daily_load_kwh / 24 / CAPACITY_KWH * 100


def _cycle(evening: Evening, now: datetime, held: HeldSunrise, held_solar: HeldSolarDay):
    raw = _raw(
        battery_soc=_soc(evening, now),
        battery_capacity_kwh=CAPACITY_KWH,
        solar_power_w=1500.0 if now < DUSK else 0.0,
        inverter_max_w=evening.inverter_w,
    )
    raw.battery_pause = PAUSE
    acc = EnergyAccumulator()
    acc.house_kwh = evening.daily_load_kwh * (now.hour * 60 + now.minute) / 1440
    data, _ = _run(
        raw=raw, cfg=_nightboost_cfg(), now=now, acc=acc, held_sunrise=held, held_solar=held_solar
    )
    return data


def _replay(evening: Evening):
    """Every cycle from midday to 22:00, the hold and the settled solar state carried."""
    held, held_solar = HeldSunrise(), HeldSolarDay()
    now = START
    while now <= END:
        yield now, _cycle(evening, now, held, held_solar)
        now += STEP


def _figure(pattern: re.Pattern[str], text: str) -> int:
    match = pattern.search(text)
    assert match, text
    return int(match.group(1))


SAFE_EVENINGS = [
    pytest.param(Evening(85.0, 15.0, 5000.0), id="5kW"),
    pytest.param(Evening(85.0, 15.0, 3600.0), id="3.6kW"),
]


class TestTheWordsQuoteThePublishedFigure:
    @pytest.mark.parametrize("evening", SAFE_EVENINGS)
    def test_the_explanation_quotes_the_sensor_every_cycle(self, evening):
        for now, data in _replay(evening):
            attrs = sv.night_survival_attributes(data)
            quoted = _figure(EXPLANATION_FIGURE, attrs["explanation"])
            assert quoted == round(data.estimated_soc_at_sunrise), now
            assert abs(quoted - attrs["estimated_soc_at_sunrise"]) <= 0.5, now

    @pytest.mark.parametrize("evening", SAFE_EVENINGS)
    def test_the_outlook_quotes_the_sensor_every_cycle(self, evening):
        for now, data in _replay(evening):
            assert data.will_survive_night, now
            quoted = _figure(REASON_FIGURE, data.survival_reason)
            assert quoted == round(data.estimated_soc_at_sunrise), now

    @pytest.mark.parametrize("evening", SAFE_EVENINGS)
    def test_the_sensor_is_paced_at_dusk(self, evening):
        """Without this the replay would not test the gap: the sensor ramps after dusk."""
        published = [data.estimated_soc_at_sunrise for _, data in _replay(evening)]
        swing_per_cycle = evening.inverter_w / 1000 / CAPACITY_KWH * 100 * STEP.seconds / 3600
        falls = [before - after for before, after in zip(published, published[1:], strict=False)]
        assert max(falls) == pytest.approx(swing_per_cycle)


class TestAShortfallShowsAtOnce:
    # Lasts the evening from 20:00, when solar is expected to stop, but not from 18:00.
    EVENING = Evening(40.0, 30.0, 5000.0)

    def _first_dusk_cycle(self):
        first_night = DUSK + timedelta(minutes=SOLAR_DAY_DEBOUNCE_MINUTES)
        cycles = list(_replay(self.EVENING))
        index = next(i for i, (now, _) in enumerate(cycles) if now >= first_night)
        return cycles[index - 1][1], cycles[index][1]

    def test_the_day_before_dusk_lasts_the_night(self):
        before, _ = self._first_dusk_cycle()
        assert before.will_survive_night

    def test_the_first_dusk_cycle_is_critical_before_the_sensor_catches_up(self):
        _, dusk = self._first_dusk_cycle()
        assert sv.night_survival_confidence(dusk) == sv.NIGHT_CRITICAL
        assert dusk.estimated_soc_at_sunrise > dusk.battery_min_soc

    def test_the_first_dusk_cycle_gives_the_shortfall_in_words(self):
        _, dusk = self._first_dusk_cycle()
        attrs = sv.night_survival_attributes(dusk)
        assert SHORTFALL.search(dusk.survival_reason)
        assert SHORTFALL.search(attrs["explanation"])
        assert attrs["outlook"] == "May run low"
