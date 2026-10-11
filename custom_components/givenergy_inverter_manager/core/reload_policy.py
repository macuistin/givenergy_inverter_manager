"""
reload_policy.py - which config changes reload the integration and which apply live.

A save used to reload the integration unless it only touched the three immersion temperatures
or the tariff review date. Moving a slider or toggling dry run restarted every entity. This
module states the rule once, per key, over the merged config (setup data under saved options).

  RELOAD_KEYS   changing the value changes what is set up: the wiring, the immersion switch
                and sensor, and the few settings read once at setup.
  PRESENCE_KEYS reload only when the group goes from nothing set to something set, or back.
                The alternative-heating advice device exists while any of them is set.
  LIVE_KEYS     the coordinator reads the value from the merged config on every cycle, or
                (the three immersion temperatures) the update listener copies it on.

A key in none of the three sets reloads. A new option therefore starts safe, and the table
test in tests/core/test_reload_policy.py fails until the key is placed deliberately.

Audit of the LIVE_KEYS (read on every 30 second cycle through coordinator._effective_cfg(),
unless noted):
  tariff                 base_rate, base_rate_name, rate_periods, export_rate, tariff_changes,
                         standing_charge_per_day, pso_levy_per_month, vat_rate, discount_rate,
                         bill_start_day: build_tariff(cfg) each cycle. The charge-target write
                         trigger is registered from the tariff at setup and at midnight, so a
                         live tariff change re-registers it (TARIFF_TRIGGER_KEYS).
  battery and charging   battery_capacity_kwh, inverter_max_output_kw, battery_min_soc_pct,
                         overnight_charge_target_pct, skip_charge_soc_threshold_pct,
                         cheap_rate_floor_soc, battery_cost_eur, battery_throughput_budget_kwh.
  forecast               forecast_entity_p10, forecast_entity_d2, carbon_intensity_entity,
                         forecast_conservatism. forecast_provider is stored and never read.
  hot water              immersion_wattage_w, immersion_ready_times.
  immersion temperatures immersion_target_temp_c, immersion_min_temp_c, immersion_hysteresis_c:
                         cached on the coordinator, copied by apply_config_change.
  EV                     car_efficiency_kwh_per_100km.
  controls               dry_run (coordinator.is_dry_run and the engine), verbose_logging
                         (the logger's config accessor), surplus_divert_soc_pct,
                         surplus_divert_min_power_w, tariff_reviewed_on (read by the repair
                         check).

Kept as RELOAD although re-read each cycle, because something else uses them once:
  forecast_entity        also seeds the forecast accuracy history, at setup.
  currency               sets the unit of every money sensor, fixed when the entity is added.
  the wiring keys        the charge target and window entities are also watched from setup.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from ..const import (
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_COST,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_THROUGHPUT_BUDGET,
    CONF_BILL_START_DAY,
    CONF_CAR_EFFICIENCY_KWH_PER_100KM,
    CONF_CARBON_INTENSITY_ENTITY,
    CONF_CHARGE_END_TIME_ENTITY,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_CHEAP_RATE_FLOOR_SOC,
    CONF_CURRENCY,
    CONF_DISCOUNT_RATE,
    CONF_DRY_RUN,
    CONF_ENABLE_CHARGE_SCHEDULE,
    CONF_ENABLE_CHARGE_TARGET,
    CONF_EXPORT_RATE,
    CONF_FORECAST_CONSERVATISM,
    CONF_FORECAST_ENTITY,
    CONF_FORECAST_ENTITY_D2,
    CONF_FORECAST_ENTITY_P10,
    CONF_FORECAST_PROVIDER,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_IMMERSION_HYSTERESIS,
    CONF_IMMERSION_MIN_TEMP,
    CONF_IMMERSION_READY_TIMES,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TARGET_TEMP,
    CONF_IMMERSION_TEMP_SENSOR,
    CONF_IMMERSION_WATTAGE,
    CONF_INVERTER_MAX_OUTPUT,
    CONF_INVERTER_SERIAL,
    CONF_INVERTER_TEMP_ENTITY,
    CONF_OIL_PRICE_ENTITY,
    CONF_OIL_PRICE_PER_LITRE,
    CONF_OVERNIGHT_CHARGE_TARGET,
    CONF_PSO_LEVY,
    CONF_RATE_PERIODS,
    CONF_SKIP_CHARGE_SOC_THRESHOLD,
    CONF_SOLAR_POWER,
    CONF_STANDING_CHARGE,
    CONF_SURPLUS_DIVERT_MIN_W,
    CONF_SURPLUS_DIVERT_SOC,
    CONF_TARGET_SOC_ENTITY,
    CONF_TARIFF_CHANGES,
    CONF_TARIFF_REVIEWED_ON,
    CONF_VAT_RATE,
    CONF_VERBOSE_LOGGING,
)


class Effect(StrEnum):
    """What a config change needs."""

    NONE = "none"
    LIVE = "live"
    RELOAD = "reload"


RELOAD_KEYS: frozenset[str] = frozenset(
    {
        # Wiring: the inverter serial (the unique ID) and the eleven entity IDs.
        CONF_INVERTER_SERIAL,
        CONF_SOLAR_POWER,
        CONF_BATTERY_SOC,
        CONF_BATTERY_POWER,
        CONF_GRID_POWER,
        CONF_HOUSE_LOAD,
        CONF_INVERTER_TEMP_ENTITY,
        CONF_TARGET_SOC_ENTITY,
        CONF_ENABLE_CHARGE_TARGET,
        CONF_ENABLE_CHARGE_SCHEDULE,
        CONF_CHARGE_START_TIME_ENTITY,
        CONF_CHARGE_END_TIME_ENTITY,
        # The optional device set.
        CONF_IMMERSION_SWITCH,
        CONF_IMMERSION_TEMP_SENSOR,
        # Read once at setup (forecast history seeding, entity units).
        CONF_FORECAST_ENTITY,
        CONF_CURRENCY,
    }
)

# Keys that decide one optional device together. Changing a value inside the group is live.
# The group reloads only when it goes from all unset to some set, or back.
PRESENCE_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({CONF_OIL_PRICE_PER_LITRE, CONF_OIL_PRICE_ENTITY}),
)
PRESENCE_KEYS: frozenset[str] = frozenset().union(*PRESENCE_GROUPS)

# The three immersion temperatures the number entities write to entry.data.
IMMERSION_TEMP_KEYS: frozenset[str] = frozenset(
    {CONF_IMMERSION_TARGET_TEMP, CONF_IMMERSION_MIN_TEMP, CONF_IMMERSION_HYSTERESIS}
)

# Keys that move the cheapest-rate start, which the charge-target write trigger is built from.
TARIFF_TRIGGER_KEYS: frozenset[str] = frozenset(
    {CONF_BASE_RATE, CONF_BASE_RATE_NAME, CONF_RATE_PERIODS, CONF_EXPORT_RATE, CONF_TARIFF_CHANGES}
)

LIVE_KEYS: frozenset[str] = frozenset(
    {
        # Controls
        CONF_DRY_RUN,
        CONF_VERBOSE_LOGGING,
        CONF_SURPLUS_DIVERT_SOC,
        CONF_SURPLUS_DIVERT_MIN_W,
        CONF_CHEAP_RATE_FLOOR_SOC,
        CONF_SKIP_CHARGE_SOC_THRESHOLD,
        CONF_FORECAST_CONSERVATISM,
        CONF_TARIFF_REVIEWED_ON,
        # Tariff
        CONF_STANDING_CHARGE,
        CONF_PSO_LEVY,
        CONF_VAT_RATE,
        CONF_DISCOUNT_RATE,
        CONF_BILL_START_DAY,
        # Battery and charging
        CONF_BATTERY_CAPACITY,
        CONF_INVERTER_MAX_OUTPUT,
        CONF_BATTERY_MIN_SOC,
        CONF_OVERNIGHT_CHARGE_TARGET,
        CONF_BATTERY_COST,
        CONF_BATTERY_THROUGHPUT_BUDGET,
        # Forecast
        CONF_FORECAST_PROVIDER,
        CONF_FORECAST_ENTITY_P10,
        CONF_FORECAST_ENTITY_D2,
        CONF_CARBON_INTENSITY_ENTITY,
        # Hot water and EV
        CONF_IMMERSION_WATTAGE,
        CONF_IMMERSION_READY_TIMES,
        CONF_CAR_EFFICIENCY_KWH_PER_100KM,
    }
    | TARIFF_TRIGGER_KEYS
    | IMMERSION_TEMP_KEYS
)


def _value(config: Mapping[str, Any], key: str) -> Any:
    """The value of *key*, with an empty string read as unset like None and a missing key."""
    value = config.get(key)
    return None if value == "" else value


def changed_keys(old: Mapping[str, Any], new: Mapping[str, Any]) -> frozenset[str]:
    """The keys whose value differs. Unset, None and an empty string count as the same."""
    return frozenset(key for key in {*old, *new} if _value(old, key) != _value(new, key))


def _any_set(config: Mapping[str, Any], group: frozenset[str]) -> bool:
    return any(bool(_value(config, key)) for key in group)


def _presence_flipped(
    old: Mapping[str, Any], new: Mapping[str, Any], group: frozenset[str]
) -> bool:
    """True when nothing in *group* was set before and something is now, or the reverse."""
    return _any_set(old, group) != _any_set(new, group)


def _needs_reload(key: str, old: Mapping[str, Any], new: Mapping[str, Any]) -> bool:
    if key in PRESENCE_KEYS:
        group = next(g for g in PRESENCE_GROUPS if key in g)
        return _presence_flipped(old, new, group)
    return key not in LIVE_KEYS


def change_effect(old: Mapping[str, Any], new: Mapping[str, Any]) -> Effect:
    """What going from the merged config *old* to *new* needs.

    NONE when no value changed, RELOAD when any changed key needs one (a key this module
    does not list counts), else LIVE.
    """
    changed = changed_keys(old, new)
    if not changed:
        return Effect.NONE
    if any(_needs_reload(key, old, new) for key in changed):
        return Effect.RELOAD
    return Effect.LIVE
