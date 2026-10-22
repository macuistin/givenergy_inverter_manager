"""conf.py — configuration entry and option keys (the CONF_ names).

No imports, so no cycle. const.py re-exports every name.
"""

# ── GivTCP inverter entities ──────────────────────────────────────────────────
CONF_INVERTER_SERIAL = "inverter_serial"  # persisted serial — used as unique_id
CONF_SOLAR_POWER = "solar_power_entity"
CONF_BATTERY_SOC = "battery_soc_entity"
CONF_BATTERY_POWER = "battery_power_entity"
CONF_GRID_POWER = "grid_power_entity"
CONF_HOUSE_LOAD = "house_load_entity"
CONF_INVERTER_MAX_OUTPUT = "inverter_max_output_kw"
CONF_INVERTER_TEMP_ENTITY = "inverter_temp_entity"  # sensor.*_invertor_temperature
# GivTCP charge control entities — all optional
CONF_TARGET_SOC_ENTITY = "target_soc_entity"  # number.*_target_soc
CONF_ENABLE_CHARGE_TARGET = "enable_charge_target_entity"  # switch.*_enable_charge_target
CONF_ENABLE_CHARGE_SCHEDULE = "enable_charge_schedule_entity"  # switch.*_enable_charge_schedule
CONF_CHARGE_START_TIME_ENTITY = "charge_start_time_entity"  # select.*_charge_start_time_slot_1
CONF_CHARGE_END_TIME_ENTITY = "charge_end_time_entity"  # select.*_charge_end_time_slot_1
CONF_BATTERY_CAPACITY = "battery_capacity_kwh"  # typed value, for no sensor or a dead one
# Sensors the battery capacity and inverter output are read from. Empty means the typed value.
CONF_BATTERY_CAPACITY_ENTITY = "battery_capacity_entity"
CONF_INVERTER_MAX_OUTPUT_ENTITY = "inverter_max_output_entity"

# ── Tariff ────────────────────────────────────────────────────────────────────
# Base rate — the default rate when no timed period is active (e.g. standard daytime)
CONF_BASE_RATE = "base_rate"
CONF_BASE_RATE_NAME = "base_rate_name"
# Timed override periods stored as a list of dicts (start/end required):
# [{"name": "Night", "rate": 0.1644, "start": "23:00", "end": "08:00"}, ...]
CONF_RATE_PERIODS = "rate_periods"
CONF_EXPORT_RATE = "export_rate"
CONF_STANDING_CHARGE = "standing_charge_per_day"
CONF_PSO_LEVY = "pso_levy_per_month"
CONF_VAT_RATE = "vat_rate"
CONF_DISCOUNT_RATE = "discount_rate"
CONF_BILL_START_DAY = "bill_start_day"
CONF_CURRENCY = "currency"  # symbol used in cost sensor units
# Dated rate changes: a list of dicts, each an "effective" date (YYYY-MM-DD) plus a full set of
# the TARIFF_RATE_KEYS values. The latest change on or before today replaces those saved values.
CONF_TARIFF_CHANGES = "tariff_changes"
# Date (YYYY-MM-DD) the user last saved a changed tariff or confirmed it in the repair.
# The first run records today when it is missing, so an upgrade never raises the repair at once.
CONF_TARIFF_REVIEWED_ON = "tariff_reviewed_on"
# URL path of the dashboard the user added from the strategy, once setup has seen it. Empty
# means setup told the user how to add one and has not seen it yet. Absent means setup has not
# looked, which is how it knows to look once.
CONF_DASHBOARD_URL_PATH = "dashboard_url_path"
# URL path of the storage dashboard the update_dashboard action last wrote. The out-of-date
# repair compares that dashboard with the generated one. Empty or absent means none is kept
# current. It is a key of its own because CONF_DASHBOARD_URL_PATH names a strategy dashboard,
# whose stored config is a pointer that must never be replaced.
CONF_STORED_DASHBOARD_URL_PATH = "stored_dashboard_url_path"

# ── Solar forecast ────────────────────────────────────────────────────────────
CONF_FORECAST_ENTITY = "forecast_entity"
# Stored by 0.17 and earlier and never read. No wizard page offers it any more, and an entry that
# holds it keeps it untouched.
CONF_FORECAST_PROVIDER = "forecast_provider"
# Solcast P10/P50 conservatism blend (0.0 = pure P50, 1.0 = pure P10).
# When Solcast is configured as the forecast provider and exposes separate P10/P90
# entities, this weight controls how pessimistic the forecast is.
# At 0.35 (the default, matching PALM): slightly pessimistic — avoids over-reliance
# on optimistic sunny-day forecasts that may not materialise.
# Optional — has no effect when a non-Solcast forecast provider is used.
CONF_FORECAST_CONSERVATISM = "forecast_conservatism"
CONF_FORECAST_ENTITY_P10 = "forecast_entity_p10"  # optional Solcast P10 sensor
CONF_FORECAST_ENTITY_D2 = "forecast_entity_d2"   # optional day-after-tomorrow forecast

# ── Carbon intensity ──────────────────────────────────────────────────────────
# Optional sensor providing real-time grid carbon intensity (g CO2/kWh).
# Compatible with the HA CO2Signal integration or any sensor publishing this unit.
CONF_CARBON_INTENSITY_ENTITY = "carbon_intensity_entity"

# ── Immersion heater ──────────────────────────────────────────────────────────
CONF_IMMERSION_SWITCH = "immersion_switch_entity"
CONF_IMMERSION_WATTAGE = "immersion_wattage_w"
CONF_IMMERSION_TEMP_SENSOR = "immersion_temp_sensor_entity"
CONF_IMMERSION_TARGET_TEMP = "immersion_target_temp_c"
CONF_IMMERSION_MIN_TEMP = "immersion_min_temp_c"
CONF_IMMERSION_HYSTERESIS = "immersion_hysteresis_c"

# ── Battery management ────────────────────────────────────────────────────────
CONF_BATTERY_MIN_SOC = "battery_min_soc_pct"
CONF_OVERNIGHT_CHARGE_TARGET = "overnight_charge_target_pct"
CONF_SKIP_CHARGE_SOC_THRESHOLD = "skip_charge_soc_threshold_pct"

# ── Defaults ──────────────────────────────────────────────────────────────────
# Ready-by planning (core/immersion_rate.py): the saved ready times, and the heating rate in
# degrees per hour that the integration learns from its own runs.
CONF_IMMERSION_READY_TIMES = "immersion_ready_times"
CONF_IMMERSION_MAX_RUN_MINUTES = "immersion_max_run_minutes"
# Whether the dashboard warns when the longest run stops a scheduled run (core/scheduled_run.py).
CONF_IMMERSION_RUN_LIMIT_WARNING = "immersion_run_limit_warning"

# ── Alternative water heating advice (core/alt_heat_advice.py) ────────────────
# Some homes also heat the same cylinder another way: an oil or gas boiler, a heat pump or solid
# fuel, through a second coil. With the setting on and a cost set, a sensor says when that is the
# cheaper way to heat the water. Advice only: the integration never switches the other system.
CONF_ALT_HEAT_ENABLED = "alt_heat_enabled"
CONF_ALT_HEAT_LABEL = "alt_heat_label"
CONF_ALT_HEAT_COST_UNIT = "alt_heat_cost_unit"
CONF_ALT_HEAT_COST = "alt_heat_cost"
CONF_ALT_HEAT_COST_ENTITY = "alt_heat_cost_entity"
CONF_CAR_EFFICIENCY_KWH_PER_100KM = "car_efficiency_kwh_per_100km"

# ── Dry run mode ──────────────────────────────────────────────────────────────
# When True, all inverter writes are skipped and logged as "would have done X".
# Sensors still update, charge decisions are still calculated — nothing is sent
# to GivTCP. Useful for verifying behaviour before first live deployment.
CONF_DRY_RUN = "dry_run"
CONF_VERBOSE_LOGGING = "verbose_logging"
# Whether the nightly charge target is worked out again while the cheap window is open. Off until
# GivTCP is confirmed to apply a changed target to a charge that is already running.
CONF_CHARGE_REPLAN = "charge_replan"

# ── Charge algorithm parameters ───────────────────────────────────────────────
# The winter and shoulder months are settings. They default from the latitude (core/seasons.py)
# and are saved only when the user edits them.
CONF_CHARGE_WINTER_MONTHS = "charge_winter_months"
CONF_CHARGE_SHOULDER_MONTHS = "charge_shoulder_months"
CONF_CHARGE_WINTER_USES_FORECAST = "charge_winter_uses_forecast"

# ── Battery degradation cost ──────────────────────────────────────────────────
# Install cost of the battery (€). When set, the cycle cost is computed as:
#   cycle_cost = battery_cost / (2 × capacity_kwh × BATTERY_RATED_CYCLES)
# This is used as a minimum threshold in divert decisions: only divert
# when the economic benefit exceeds the wear cost per kWh.
# Set to 0 to disable (default — behaves identically to previous versions).
CONF_BATTERY_COST = "battery_cost_eur"

# ── Battery throughput budget ─────────────────────────────────────────────────
# Optional daily cycling budget (kWh charged plus discharged). 0 disables it.
CONF_BATTERY_THROUGHPUT_BUDGET = "battery_throughput_budget_kwh"

# ── Tuning controls ───────────────────────────────────────────────────────────
# Each of these keys is edited through a number or switch entity (controls.py), which writes
# it to the saved options. The defaults are the ones defined above and below.
CONF_SURPLUS_DIVERT_SOC = "surplus_divert_soc_pct"
CONF_SURPLUS_DIVERT_MIN_W = "surplus_divert_min_power_w"
# Cheap rate floor — top up during cheap window if battery drops below this
CONF_CHEAP_RATE_FLOOR_SOC = "cheap_rate_floor_soc"
