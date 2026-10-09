"""An immersion heat earlier in the day is not an hourly load the battery has to cover.

The night survival estimate and the overnight charge target scale today's house energy up to
24 hours. The per-slot baseline profile already leaves the immersion and the EV out, and the
average daily load left out only the EV. One morning heat of 4.7 kWh then read as 0.2 kWh an
hour all night, and the estimate sat on the minimum SoC through an evening in which the
battery fell from 58% to 45%.
"""

from datetime import datetime

import pytest

from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run

CAPACITY_KWH = 19.0
SOC = 75.0
EVENING = datetime(2026, 10, 8, 19, 0)
OTHER_HOUSE_KWH = 16.6
IMMERSION_KWH = 4.7


def _cycle(*, immersion_kwh: float, other_house_kwh: float = OTHER_HOUSE_KWH):
    """Nineteen hours into the day, the heater having run for immersion_kwh of it."""
    acc = EnergyAccumulator()
    acc.immersion_kwh = immersion_kwh
    acc.house_kwh = other_house_kwh + immersion_kwh
    raw = _raw(
        battery_soc=SOC,
        battery_capacity_kwh=CAPACITY_KWH,
        solar_power_w=0.0,
        house_load_w=600.0,
        forecast_kwh_tomorrow=12.0,
    )
    data, _ = _run(
        raw=raw,
        cfg=_nightboost_cfg(),
        now=EVENING,
        acc=acc,
        today_raw_forecast_kwh=12.0,
    )
    return data


class TestSurvivalIgnoresTheImmersionHeat:
    def test_estimate_matches_the_house_without_the_heater(self):
        with_heat = _cycle(immersion_kwh=IMMERSION_KWH)
        without_heat = _cycle(immersion_kwh=0.0)
        assert with_heat.estimated_soc_at_sunrise == pytest.approx(
            without_heat.estimated_soc_at_sunrise
        )

    def test_shortfall_matches_the_house_without_the_heater(self):
        with_heat = _cycle(immersion_kwh=IMMERSION_KWH)
        without_heat = _cycle(immersion_kwh=0.0)
        assert with_heat.survival_reason == without_heat.survival_reason

    def test_a_heavy_house_load_without_the_heater_still_counts(self):
        """The fix removes the heater's share only."""
        light = _cycle(immersion_kwh=IMMERSION_KWH, other_house_kwh=OTHER_HOUSE_KWH)
        heavy = _cycle(immersion_kwh=IMMERSION_KWH, other_house_kwh=OTHER_HOUSE_KWH * 2)
        assert heavy.will_survive_night is False
        assert heavy.estimated_soc_at_sunrise <= light.estimated_soc_at_sunrise


class TestChargeTargetIgnoresTheImmersionHeat:
    def test_the_heater_does_not_block_a_skip_the_battery_can_afford(self):
        """Skipping needs the survival check to pass, so it reads the same load."""
        with_heat = _cycle(immersion_kwh=IMMERSION_KWH)
        without_heat = _cycle(immersion_kwh=0.0)
        assert without_heat.charge_decision.skip_charge is True
        assert with_heat.charge_decision.skip_charge is True
