"""The ready-by plan waits for the sun when enough solar is forecast, else uses a cheap band's tail."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from custom_components.givenergy_inverter_manager.core.tariff import build_tariff
from custom_components.givenergy_inverter_manager.lib.heating.planned import (
    PlanQuery,
    describe_planned_heating,
)
from custom_components.givenergy_inverter_manager.lib.heating.ready import (
    ReadyInputs,
    plan_ready,
)
from custom_components.givenergy_inverter_manager.lib.heating.solar import (
    SolarOutlook,
    solar_window,
)
from custom_components.givenergy_inverter_manager.lib.heating.water import WaterReading

DUBLIN = ZoneInfo("Europe/Dublin")
TARIFF = build_tariff(
    {
        "base_rate": 0.365,
        "rate_periods": [
            {"name": "Night", "rate": 0.18, "start": "23:00", "end": "08:00"},
            {"name": "Nightboost", "rate": 0.1056, "start": "02:00", "end": "04:00"},
        ],
    }
)
EVENING = (time(19, 0),)
FIVE_PM = 17 * 60


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 20, hour, minute, tzinfo=DUBLIN)


def sun(kwh: float) -> SolarOutlook:
    return SolarOutlook(forecast_kwh=kwh, sunrise_hour=8, end_minute=FIVE_PM, heater_w=3000.0)


def plan(now: datetime, temp: float, solar: SolarOutlook | None):
    return plan_ready(ReadyInputs(TARIFF, now, EVENING, temp, 55.0, 10.0, solar=solar))


def test_good_solar_holds_off_the_grid_heating_in_the_tail_of_the_night_band():
    # 07:39, water 49.8 C: 21 minutes of the Night rate are left.
    assert plan(at(7, 39), 49.8, sun(10.0)).heat_now is False


def test_without_good_solar_the_tail_of_the_cheap_band_is_used():
    assert plan(at(7, 39), 49.8, sun(3.0)).heat_now is True
    assert plan(at(7, 39), 49.8, None).heat_now is True


def test_the_hold_ends_as_the_forecast_fades_through_the_day():
    # At 15:00 two of the nine solar hours are left, so 10 kWh forecast leaves 2.2 kWh ahead,
    # under three times the heater's energy.
    assert solar_window(sun(10.0), at(10, 0), at(19, 0), 0.6) is not None
    assert solar_window(sun(10.0), at(15, 0), at(19, 0), 0.6) is None
    assert plan(at(18, 40), 49.8, sun(10.0)).heat_now is True


def test_the_plan_text_names_the_sun():
    water = WaterReading(49.8, 55.0, 10.0, 50.0, 5.0)
    query = PlanQuery(TARIFF, at(7, 39), EVENING, water, False, None, sun(10.0))

    assert "from expected solar" in describe_planned_heating(query)
