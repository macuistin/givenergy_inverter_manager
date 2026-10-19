"""The overnight charge cost follows the rate in force while an extended window runs.

A charge that fits the cheapest period costs its energy at the cheapest rate. One that needs
longer is paid at the next period's rate for the rest, and the cost on both the fresh and the
published decision has to say so.
"""

from datetime import datetime

import pytest

from custom_components.givenergy_inverter_manager.core.tariff import build_tariff
from tests.conftest import _nightboost_cfg, _raw, _run

CAPACITY_KWH = 19.0
CHARGE_W = 3600.0
NIGHT = datetime(2031, 6, 15, 23, 0)
CFG = {**_nightboost_cfg(), "overnight_charge_target_pct": 100}
_PERIODS = {p.name: p.rate for p in build_tariff(CFG).rate_periods}
BOOST, NIGHT_RATE = _PERIODS["Nightboost"], _PERIODS["Night"]
BOOST_HOURS = 2.0


def _night(soc: float, charge_w: float | None, target: int):
    raw = _raw(
        battery_soc=soc,
        battery_capacity_kwh=CAPACITY_KWH,
        solar_power_w=0.0,
        forecast_kwh_tomorrow=0.0,
        battery_charge_rate_w=charge_w,
    )
    data, _ = _run(raw=raw, cfg=CFG, now=NIGHT, override_charge_target=target)
    return data


class TestAnExtendedWindow:
    def test_the_cost_pays_the_night_rate_for_the_energy_after_the_nightboost(self):
        data = _night(soc=20.0, charge_w=CHARGE_W, target=100)
        assert data.charge_window.extended
        deficit = CAPACITY_KWH * 0.8
        in_boost = BOOST_HOURS * CHARGE_W / 1000
        expected = in_boost * BOOST + (deficit - in_boost) * NIGHT_RATE
        for decision in (data.charge_decision, data.published_charge_decision):
            assert decision.cost_to_charge == pytest.approx(expected)

    def test_it_costs_more_than_the_cheapest_rate_alone(self):
        data = _night(soc=20.0, charge_w=CHARGE_W, target=100)
        assert data.charge_decision.cost_to_charge > CAPACITY_KWH * 0.8 * BOOST


class TestAWindowThatIsNotExtended:
    def test_a_charge_that_fits_the_nightboost_costs_the_cheapest_rate(self):
        data = _night(soc=60.0, charge_w=CHARGE_W, target=80)
        assert not data.charge_window.extended
        assert data.charge_decision.cost_to_charge == pytest.approx(CAPACITY_KWH * 0.2 * BOOST)

    def test_an_unknown_charge_rate_keeps_the_cheapest_rate_price(self):
        data = _night(soc=20.0, charge_w=None, target=100)
        assert data.charge_decision.cost_to_charge == pytest.approx(CAPACITY_KWH * 0.8 * BOOST)
