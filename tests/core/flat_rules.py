"""Keyword-argument adapters over the parameter-object API in core/rules.py.

Most rule tests describe a scenario as a flat set of keyword arguments with sensible
defaults and override one or two. These helpers keep that style: they take the flat
keywords, build the frozen input dataclasses and call the real rule function. They add
no logic of their own, so a test through here exercises exactly the production path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from custom_components.givenergy_inverter_manager.const import (
    DEFAULT_CURRENCY_SYMBOL,
    SURPLUS_DIVERT_MIN_POWER_W,
    SURPLUS_DIVERT_SOC_THRESHOLD,
)
from custom_components.givenergy_inverter_manager.core import rules
from custom_components.givenergy_inverter_manager.core.rules import (
    ApplianceRequest,
    ChargeDecision,
    ChargeInputs,
    DivertPolicy,
    ImmersionInputs,
    ImmersionRun,
    PowerReadings,
    PreBoostInputs,
    RateContext,
    SiteReadings,
    SolarForecast,
    SurplusInputs,
    WaterState,
)


def calculate_overnight_charge_target(
    current_soc: float,
    battery_capacity_kwh: float,
    forecast_kwh: float | None,
    inverter_max_kw: float,
    car_plugged_in: bool,
    min_soc: int,
    skip_charge_threshold: int,
    average_daily_consumption_kwh: float,
    cheapest_rate: float,
    solar_fractions: dict[int, float] | None = None,
    forecast_kwh_p10: float | None = None,
    forecast_conservatism: float = 0.0,
    forecast_kwh_d2: float | None = None,
    load_profile: list[float] | None = None,
    forecast_correction: float | None = None,
    solar_generating: bool = True,
    *,
    dt: datetime,
) -> ChargeDecision:
    return rules.calculate_overnight_charge_target(
        ChargeInputs(
            current_soc=current_soc,
            battery_capacity_kwh=battery_capacity_kwh,
            min_soc=min_soc,
            skip_charge_threshold=skip_charge_threshold,
            car_plugged_in=car_plugged_in,
            inverter_max_kw=inverter_max_kw,
            average_daily_consumption_kwh=average_daily_consumption_kwh,
            cheapest_rate=cheapest_rate,
            load_profile=load_profile,
            solar_generating=solar_generating,
        ),
        SolarForecast(
            forecast_kwh=forecast_kwh,
            solar_fractions=solar_fractions,
            forecast_kwh_p10=forecast_kwh_p10,
            forecast_conservatism=forecast_conservatism,
            forecast_kwh_d2=forecast_kwh_d2,
            forecast_correction=forecast_correction,
        ),
        dt,
    )


def should_divert_to_immersion(
    solar_power_w: float | None,
    house_load_w: float | None,
    battery_soc: float,
    battery_power_w: float | None,
    inverter_max_w: float,
    immersion_temp: float | None,
    immersion_target_temp: float,
    immersion_min_temp: float,
    immersion_hysteresis_c: float = 5.0,
    currently_on: bool = False,
    soc_threshold: int = SURPLUS_DIVERT_SOC_THRESHOLD,
    min_surplus_w: float = SURPLUS_DIVERT_MIN_POWER_W,
    battery_cycle_cost_per_kwh: float = 0.0,
    export_rate: float = 0.0,
    immersion_power_w: float = 0.0,
    immersion_temp_unavailable: bool = False,
    unavailable_for_s: float = 0.0,
    currency_symbol: str = DEFAULT_CURRENCY_SYMBOL,
) -> tuple[bool, str]:
    return rules.should_divert_to_immersion(
        ImmersionInputs(
            power=PowerReadings(
                solar_power_w=solar_power_w,
                house_load_w=house_load_w,
                battery_power_w=battery_power_w,
                battery_soc=battery_soc,
                inverter_max_w=inverter_max_w,
                immersion_power_w=immersion_power_w,
            ),
            water=WaterState(
                temp=immersion_temp,
                target_temp=immersion_target_temp,
                min_temp=immersion_min_temp,
                hysteresis_c=immersion_hysteresis_c,
                temp_unavailable=immersion_temp_unavailable,
            ),
            policy=DivertPolicy(
                soc_threshold=soc_threshold,
                min_surplus_w=min_surplus_w,
                battery_cycle_cost_per_kwh=battery_cycle_cost_per_kwh,
                export_rate=export_rate,
                currency_symbol=currency_symbol,
            ),
            run=ImmersionRun(currently_on=currently_on, unavailable_for_s=unavailable_for_s),
        )
    )


def suggest_appliance_run(
    solar_power_w: float,
    house_load_w: float,
    battery_soc: float,
    battery_power_w: float,
    appliance_power_w: float,
    appliance_name: str,
    rate_period_name: str,
    rate: float,
    export_rate: float,
    currency_symbol: str = DEFAULT_CURRENCY_SYMBOL,
) -> tuple[bool, str]:
    return rules.suggest_appliance_run(
        SiteReadings(solar_power_w, house_load_w, battery_soc, battery_power_w),
        ApplianceRequest(appliance_name, appliance_power_w),
        RateContext(rate_period_name, rate, export_rate, currency_symbol),
    )


def available_surplus_w(
    solar_power_w: float,
    house_load_w: float,
    battery_power_w: float = 0.0,
    immersion_on: bool = False,
    immersion_power_w: float = 0.0,
) -> float:
    return rules.available_surplus_w(
        SurplusInputs(
            solar_power_w, house_load_w, battery_power_w, immersion_on, immersion_power_w
        )
    )


def calculate_pre_boost_export_opportunity(**kwargs: Any) -> tuple[float, float, bool]:
    return rules.calculate_pre_boost_export_opportunity(PreBoostInputs(**kwargs))


def _simulate_min_soc(
    start_soc_pct: float,
    forecast_kwh: float,
    avg_daily_kwh: float,
    battery_capacity_kwh: float,
    load_profile: list[float] | None = None,
) -> float:
    day = rules._SimulatedDay(
        forecast_kwh,
        battery_capacity_kwh,
        rules._slot_loads_kwh(avg_daily_kwh, load_profile),
    )
    return rules._simulate_min_soc(start_soc_pct, day)


def _find_minimum_charge_target(
    forecast_kwh: float,
    avg_daily_kwh: float,
    battery_capacity_kwh: float,
    min_soc: int,
    load_profile: list[float] | None = None,
) -> int:
    day = rules._SimulatedDay(
        forecast_kwh,
        battery_capacity_kwh,
        rules._slot_loads_kwh(avg_daily_kwh, load_profile),
    )
    return rules._find_minimum_charge_target(day, min_soc)
