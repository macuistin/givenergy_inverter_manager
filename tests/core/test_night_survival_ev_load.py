"""An EV charging overnight is not house load the battery has to cover.

The night survival estimate and the overnight charge target both start from the average daily
house load. That load is today's house energy so far scaled up to 24 hours, and the GivTCP
load figure includes the EV charger. A 7 kW charge at 01:00 therefore read as a house that
uses 170 kWh a day, and the estimate sat on the minimum SoC while the battery held 80%.
"""

from datetime import datetime

import pytest

from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw, _run

EV_W = 7000.0
BASELINE_W = 400.0
CAPACITY_KWH = 19.0
SOC = 80.0
SMALL_HOURS = datetime(2026, 6, 15, 2, 0)
HOURS_SO_FAR = 2.0


def _accumulator(*, ev_charging: bool) -> EnergyAccumulator:
    """Two hours into the day, with the EV drawing from midnight when ev_charging."""
    acc = EnergyAccumulator()
    ev_kwh = EV_W / 1000 * HOURS_SO_FAR if ev_charging else 0.0
    acc.zappi_kwh = ev_kwh
    acc.house_kwh = BASELINE_W / 1000 * HOURS_SO_FAR + ev_kwh
    return acc


def _cycle(*, ev_charging: bool, car_plugged_in: bool = True, now: datetime = SMALL_HOURS):
    house_load_w = BASELINE_W + (EV_W if ev_charging else 0.0)
    raw = _raw(
        battery_soc=SOC,
        battery_capacity_kwh=CAPACITY_KWH,
        solar_power_w=0.0,
        house_load_w=house_load_w,
        ev_power_w=EV_W if ev_charging else 0.0,
        ev_plugged_in=car_plugged_in,
        forecast_kwh_tomorrow=6.0,
    )
    data, _ = _run(
        raw=raw,
        cfg=_nightboost_cfg(),
        now=now,
        acc=_accumulator(ev_charging=ev_charging),
        today_raw_forecast_kwh=6.0,
    )
    return data


class TestSurvivalIgnoresTheEvCharge:
    def test_estimate_matches_the_house_without_the_car(self):
        with_ev = _cycle(ev_charging=True)
        without_ev = _cycle(ev_charging=False)
        assert with_ev.estimated_soc_at_sunrise == pytest.approx(
            without_ev.estimated_soc_at_sunrise
        )

    def test_estimate_stays_above_the_floor_while_the_battery_holds_charge(self):
        data = _cycle(ev_charging=True)
        assert data.estimated_soc_at_sunrise > 60.0

    def test_status_says_the_battery_lasts(self):
        data = _cycle(ev_charging=True)
        assert data.will_survive_night is True
        assert "Battery should last" in data.survival_reason
        assert "shortfall" not in data.survival_reason

    def test_a_flat_out_house_load_without_an_ev_is_still_a_shortfall(self):
        """The fix removes the EV share only. A heavy house load still counts."""
        acc = EnergyAccumulator()
        acc.house_kwh = 7.4 * HOURS_SO_FAR
        raw = _raw(
            battery_soc=SOC,
            battery_capacity_kwh=CAPACITY_KWH,
            solar_power_w=0.0,
            house_load_w=7400.0,
        )
        data, _ = _run(raw=raw, cfg=_nightboost_cfg(), now=SMALL_HOURS, acc=acc)
        assert data.will_survive_night is False


class TestChargeTargetIgnoresTheEvCharge:
    def test_the_car_buffer_is_the_only_effect_of_the_car(self):
        """Plugged in adds the deliberate buffer. Drawing 7 kW adds nothing on top."""
        charging = _cycle(ev_charging=True, car_plugged_in=True)
        idle = _cycle(ev_charging=False, car_plugged_in=True)
        assert charging.charge_decision.target_soc == idle.charge_decision.target_soc
        assert charging.charge_decision.skip_charge == idle.charge_decision.skip_charge

    def test_the_car_buffer_is_still_applied(self):
        plugged = _cycle(ev_charging=False, car_plugged_in=True)
        unplugged = _cycle(ev_charging=False, car_plugged_in=False)
        assert "Car plugged in" in plugged.charge_decision.reason
        assert plugged.charge_decision.target_soc >= unplugged.charge_decision.target_soc
