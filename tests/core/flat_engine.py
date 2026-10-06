"""Keyword-argument adapters over the parameter-object API in core/engine.py.

The engine tests describe a cycle as flat keyword arguments and override one or two. These
helpers build the frozen input dataclasses and call the real engine function, adding no
logic of their own.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from custom_components.givenergy_inverter_manager.core import engine
from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
from custom_components.givenergy_inverter_manager.core.engine import (
    AccumulationWindow,
    Accumulators,
    CoordinatorData,
    CycleInputs,
    ForecastContext,
    ManualOverrides,
    PreviousCycle,
    RawSensorValues,
)
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator, TariffConfig
from custom_components.givenergy_inverter_manager.discovery import EVCharger


def build_coordinator_data(
    raw: RawSensorValues,
    cfg: dict[str, Any],
    acc: EnergyAccumulator,
    battery_stats: BatteryStats,
    last_soc: float | None,
    last_update_time: datetime | None,
    acc_week: EnergyAccumulator | None = None,
    acc_month: EnergyAccumulator | None = None,
    acc_year: EnergyAccumulator | None = None,
    acc_yesterday: EnergyAccumulator | None = None,
    now: datetime | None = None,
    ev_charger: EVCharger | None = None,
    override_charge_target: int | None = None,
    override_immersion: bool | None = None,
    override_skip_charge: bool = False,
    solar_fractions: dict[int, float] | None = None,
    last_reset_time: str = "",
    solar_forecast_kwh_today: float = 0.0,
    yesterday_forecast_accuracy_pct: float = 0.0,
    forecast_accuracy_7day_avg_pct: float = 0.0,
    load_profile: list[float] | None = None,
    forecast_correction: float | None = None,
    today_raw_forecast_kwh: float | None = None,
    today_raw_forecast_p10_kwh: float | None = None,
) -> tuple[CoordinatorData, str | None]:
    return engine.build_coordinator_data(
        CycleInputs(
            raw=raw,
            cfg=cfg,
            now=now,
            ev_charger=ev_charger,
            overrides=ManualOverrides(
                charge_target=override_charge_target,
                immersion=override_immersion,
                skip_charge=override_skip_charge,
            ),
        ),
        Accumulators(
            today=acc,
            week=acc_week,
            month=acc_month,
            year=acc_year,
            yesterday=acc_yesterday,
            last_reset_time=last_reset_time,
        ),
        PreviousCycle(battery_stats, last_soc, last_update_time),
        ForecastContext(
            solar_fractions=solar_fractions,
            solar_forecast_kwh_today=solar_forecast_kwh_today,
            yesterday_forecast_accuracy_pct=yesterday_forecast_accuracy_pct,
            forecast_accuracy_7day_avg_pct=forecast_accuracy_7day_avg_pct,
            load_profile=load_profile,
            forecast_correction=forecast_correction,
            today_raw_forecast_kwh=today_raw_forecast_kwh,
            today_raw_forecast_p10_kwh=today_raw_forecast_p10_kwh,
        ),
    )


def accumulate_energy(
    acc: EnergyAccumulator,
    raw: RawSensorValues,
    tariff: TariffConfig,
    current_period_name: str,
    now: datetime,
    last_update_time: datetime | None,
) -> None:
    engine.accumulate_energy(
        acc, raw, AccumulationWindow(tariff, current_period_name, now, last_update_time)
    )
