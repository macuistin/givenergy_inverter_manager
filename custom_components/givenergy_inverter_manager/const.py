"""
const.py — Constants and default values for GivEnergy Inverter Manager.

All configuration keys, platform names, threshold values, and defaults
are defined here. Import from this module rather than using string literals
elsewhere to avoid typos and make refactoring easier.

GivTCP entity naming convention (all prefixed with serial number):
    sensor.givtcp_{SERIAL}_pv_power
    sensor.givtcp_{SERIAL}_battery_soc
    sensor.givtcp_{SERIAL}_battery_power
    sensor.givtcp_{SERIAL}_grid_power
    sensor.givtcp_{SERIAL}_load_power
    number.givtcp_{SERIAL}_target_soc
"""

DOMAIN = "givenergy_inverter_manager"
INTEGRATION_VERSION = "0.8.0"  # keep in sync with manifest.json
NAME = "GivEnergy Inverter Manager"
DEVICE_MANUFACTURER = "macuistin"  # shown on the device page; GivEnergy does not make this

# ── Service actions ──────────────────────────────────────────────────────────
SERVICE_GET_DASHBOARD_YAML = "get_dashboard_yaml"
SERVICE_SUGGEST_APPLIANCE = "suggest_appliance_run"
SERVICE_COMPARE_TARIFF = "compare_tariff"
SERVICE_YEAR_ON_YEAR = "year_on_year_summary"
SERVICE_EXPORT_ENERGY_DATA = "export_energy_data"
SERVICE_GET_ROI_SUMMARY = "get_roi_summary"

# ── GivTCP inverter entities ────────────────────────────────────────────────
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
CONF_BATTERY_CAPACITY = "battery_capacity_kwh"

# ── Tariff ───────────────────────────────────────────────────────────────────
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

# ── Solar forecast ───────────────────────────────────────────────────────────
CONF_FORECAST_ENTITY = "forecast_entity"
CONF_FORECAST_PROVIDER = "forecast_provider"
FORECAST_PROVIDER_FORECAST_SOLAR = "forecast_solar"
FORECAST_PROVIDER_SOLCAST = "solcast"
# Solcast P10/P50 conservatism blend (0.0 = pure P50, 1.0 = pure P10).
# When Solcast is configured as the forecast provider and exposes separate P10/P90
# entities, this weight controls how pessimistic the forecast is.
# At 0.35 (the default, matching PALM): slightly pessimistic — avoids over-reliance
# on optimistic sunny-day forecasts that may not materialise.
# Optional — has no effect when a non-Solcast forecast provider is used.
CONF_FORECAST_CONSERVATISM = "forecast_conservatism"
DEFAULT_FORECAST_CONSERVATISM = 0.35  # dimensionless 0.0–1.0
CONF_FORECAST_ENTITY_P10 = "forecast_entity_p10"  # optional Solcast P10 sensor
CONF_FORECAST_ENTITY_D2 = "forecast_entity_d2"   # optional day-after-tomorrow forecast

# ── Carbon intensity ──────────────────────────────────────────────────────────
# Optional sensor providing real-time grid carbon intensity (g CO2/kWh).
# Compatible with the HA CO2Signal integration or any sensor publishing this unit.
CONF_CARBON_INTENSITY_ENTITY = "carbon_intensity_entity"
# Thresholds for status classification (g CO2/kWh).
# Below LOW → "Low" (high renewable fraction, good time to import).
# Above HIGH → "High" (mostly fossil generation, prefer self-consumption).
CARBON_LOW_THRESHOLD = 200   # g CO2/kWh
CARBON_HIGH_THRESHOLD = 400  # g CO2/kWh
CARBON_STATUS_LOW = "Low"
CARBON_STATUS_MEDIUM = "Medium"
CARBON_STATUS_HIGH = "High"
CARBON_STATUS_UNKNOWN = "Unknown"

# ── Immersion heater ─────────────────────────────────────────────────────────
CONF_IMMERSION_SWITCH = "immersion_switch_entity"
CONF_IMMERSION_WATTAGE = "immersion_wattage_w"
CONF_IMMERSION_TEMP_SENSOR = "immersion_temp_sensor_entity"
CONF_IMMERSION_TARGET_TEMP = "immersion_target_temp_c"
CONF_IMMERSION_MIN_TEMP = "immersion_min_temp_c"
CONF_IMMERSION_HYSTERESIS = "immersion_hysteresis_c"

# ── Battery management ───────────────────────────────────────────────────────
CONF_BATTERY_MIN_SOC = "battery_min_soc_pct"
CONF_OVERNIGHT_CHARGE_TARGET = "overnight_charge_target_pct"
CONF_SKIP_CHARGE_SOC_THRESHOLD = "skip_charge_soc_threshold_pct"

# ── Supported currencies ─────────────────────────────────────────────────────
CURRENCIES = {
    "EUR": "€",
    "GBP": "£",
    "USD": "$",
    "SEK": "kr",
    "NOK": "kr",
    "DKK": "kr",
    "AUD": "A$",
    "CAD": "C$",
    "NZD": "NZ$",
    "ZAR": "R",
}
DEFAULT_CURRENCY = "EUR"
DEFAULT_CURRENCY_SYMBOL = CURRENCIES[DEFAULT_CURRENCY]

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_INVERTER_MAX_OUTPUT = 5.0  # kW — GivEnergy GIV-HY-5.0
DEFAULT_BATTERY_CAPACITY = 10.0  # kWh — conservative fallback if not configured
DEFAULT_IMMERSION_WATTAGE = 3000  # W
DEFAULT_IMMERSION_TARGET_TEMP = 55  # °C — turn off when water reaches this
DEFAULT_IMMERSION_MIN_TEMP = 50  # °C — force on below this (legionella protection)
DEFAULT_IMMERSION_HYSTERESIS = 5  # °C — only restart after cooling this far below target
IMMERSION_SWITCH_COOLDOWN_MINUTES = 10  # min between auto on/off writes to the real switch
DEFAULT_BATTERY_MIN_SOC = 10  # %
DEFAULT_OVERNIGHT_CHARGE_TARGET = 80  # %
DEFAULT_SKIP_CHARGE_SOC_THRESHOLD = 75  # %
DEFAULT_VAT_RATE = 9.0  # % (Irish domestic electricity)
DEFAULT_DISCOUNT_RATE = 5.5  # % (DD + online billing, Electric Ireland)
DEFAULT_STANDING_CHARGE = 0.8259  # per day
DEFAULT_PSO_LEVY = 1.46  # per month
DEFAULT_EXPORT_RATE = 0.195  # per kWh (Irish CEG rate)
DEFAULT_BILL_START_DAY = 1  # day of month
CONF_CAR_EFFICIENCY_KWH_PER_100KM = "car_efficiency_kwh_per_100km"
DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM = 15.0  # kWh/100km — typical BEV efficiency

# Default rate periods: Electric Ireland Home Electric + Nightboost
# Nightboost (02:00–04:00) is listed last but takes priority over Night
# because get_current_rate() returns the cheapest active period.
DEFAULT_BASE_RATE = 0.3334  # €/kWh — daytime / standard rate
DEFAULT_BASE_RATE_NAME = "Day"
# Timed override slots — cheapest active slot wins, then base rate applies
DEFAULT_RATE_PERIODS = [
    {"name": "Night", "rate": 0.1644, "start": "23:00", "end": "08:00"},
    {"name": "Nightboost", "rate": 0.0965, "start": "02:00", "end": "04:00"},
]

# ── Dry run mode ─────────────────────────────────────────────────────────────
# When True, all inverter writes are skipped and logged as "would have done X".
# Sensors still update, charge decisions are still calculated — nothing is sent
# to GivTCP. Useful for verifying behaviour before first live deployment.
CONF_DRY_RUN = "dry_run"
DEFAULT_DRY_RUN = False

CONF_VERBOSE_LOGGING = "verbose_logging"
DEFAULT_VERBOSE_LOGGING = False

# ── Inverter temperature thresholds ─────────────────────────────────────────
INVERTER_TEMP_WARM = 60      # °C — efficiency begins to drop
INVERTER_TEMP_DERATING = 65  # °C — significant throttling begins
INVERTER_TEMP_CRITICAL = 75  # °C — protection mode likely

# Inverter temperature status labels
INVERTER_TEMP_STATUS_NORMAL = "Normal"
INVERTER_TEMP_STATUS_WARM = "Warm"
INVERTER_TEMP_STATUS_DERATING = "Derating"
INVERTER_TEMP_STATUS_CRITICAL = "Critical"
INVERTER_TEMP_STATUS_UNKNOWN = "Unknown"

# ── Operational thresholds ───────────────────────────────────────────────────
# Battery SoC must be above this before immersion divert activates
SURPLUS_DIVERT_SOC_THRESHOLD = 80  # %
# Minimum solar surplus (W) before turning on immersion
SURPLUS_DIVERT_MIN_POWER_W = 500  # W
# Inverter output as % of max that signals clipping
CLIPPING_THRESHOLD_PERCENT = 95  # %
# Battery SoC (%) at or above which the battery counts as full
BATTERY_FULL_SOC_PCT = 99.0  # %

# ── Appliance timing suggestion ──────────────────────────────────────────────
APPLIANCE_MIN_BATTERY_SOC = 80  # % — battery charge needed to run an appliance from the battery
APPLIANCE_RATE_THRESHOLD = 1.5  # × export rate — above this the grid rate is too high to suggest

# ── Coordinator ──────────────────────────────────────────────────────────────
UPDATE_INTERVAL_SECONDS = 30

# ── HA platforms exposed by this integration ─────────────────────────────────
PLATFORMS = ["sensor", "switch", "number"]

# ── Charge algorithm parameters ───────────────────────────────────────────────
# These govern the overnight charge decision logic in rules.py.
# Named here so behaviour is documented and auditable — not buried as magic numbers.

# Winter months: charge to 100% regardless of forecast. Solar is negligible
# and grid charging is nearly always the right decision in Ireland (Dec–Feb).
CHARGE_WINTER_MONTHS: tuple[int, ...] = (12, 1, 2)
# Shoulder months: raise the min_soc floor to max_soc_target — heating load is
# variable and the forecast is less reliable than in peak summer.
CHARGE_SHOULDER_MONTHS: tuple[int, ...] = (3, 4, 10, 11)
# Shoulder month min SoC floor (% of battery) — more conservative than summer floor.
CHARGE_SHOULDER_MIN_SOC = 70  # % — applied instead of battery_min_soc in shoulder months
# Winter months: the charge is skipped once the battery is at or above this SoC.
CHARGE_WINTER_SKIP_SOC_PCT = 95  # %
# The overnight target is never planned closer than this to the minimum SoC.
CHARGE_MIN_TARGET_HEADROOM_PCT = 5  # SoC points above min SoC

CHARGE_PEAK_SOLAR_HOURS = 4.0  # peak-output hours assumed when no forecast available
CHARGE_MORNING_LOAD_FRACTION = 0.25  # fraction of daily load consumed before solar starts
CHARGE_SOLAR_USABLE_FRACTION = 0.6  # fraction of forecast kWh we can realistically charge from
CHARGE_SKIP_HEADROOM = 0.8  # forecast/fill headroom needed to justify skipping charge
CHARGE_STRONG_BUFFER = 10  # SoC points added above gap for strong forecast
CHARGE_EV_SOC_BONUS = 10  # extra SoC percentage added when EV is plugged in
CHARGE_LOAD_PROFILE_MIN_COVERAGE = 0.9  # fraction of the day a load record must cover
CHARGE_LOAD_PROFILE_MIN_DAYS = 2  # complete days needed before the per-slot profile is used
CHARGE_LOAD_PROFILE_SAME_WEEKDAY_MIN_DAYS = 3  # same-weekday days needed to prefer them
CHARGE_FORECAST_CORRECTION_MIN = 0.6  # lowest factor applied to the P50 forecast
CHARGE_FORECAST_CORRECTION_MAX = 1.2  # highest factor applied to the P50 forecast
CHARGE_FORECAST_CORRECTION_MIN_DAYS = 5  # usable days needed before the factor is applied
CHARGE_FORECAST_CORRECTION_MIN_KWH = 0.5  # days with forecast or actual below this are ignored

# ── Solar / generation parameters ─────────────────────────────────────────────
SOLAR_SUNRISE_HOUR = 8  # hour of day when solar generation typically starts
SOLAR_NOISE_FLOOR_W = 10.0  # W — sensor readings below this are treated as zero

# ── Battery health parameters ─────────────────────────────────────────────────
BATTERY_RATED_CYCLES = 6000  # typical LFP rated cycle life (manufacturer spec)
NIGHT_SURVIVAL_WARNING_MARGIN_PCT = 5.0  # warn within this many SoC points of min SoC
BATTERY_LIFE_ESTIMATE_MIN_DAYS = 7  # days of cycle data needed before estimating years left
BATTERY_MAX_SOC_STEP_PCT = 10.0  # SoC change between two updates above this is a sensor glitch

# ── Battery degradation cost ──────────────────────────────────────────────────
# Install cost of the battery (€). When set, the cycle cost is computed as:
#   cycle_cost = battery_cost / (2 × capacity_kwh × BATTERY_RATED_CYCLES)
# This is used as a minimum threshold in divert decisions: only divert
# when the economic benefit exceeds the wear cost per kWh.
# Set to 0 to disable (default — behaves identically to previous versions).
CONF_BATTERY_COST = "battery_cost_eur"
DEFAULT_BATTERY_COST = 0.0  # € — 0 disables the degradation cost check

# ── Battery throughput budget ─────────────────────────────────────────────────
# Optional daily cycling budget (kWh charged plus discharged). 0 disables it.
CONF_BATTERY_THROUGHPUT_BUDGET = "battery_throughput_budget_kwh"
DEFAULT_BATTERY_THROUGHPUT_BUDGET = 0.0
THROUGHPUT_BUDGET_HIGH_PCT = 80.0  # at or above this, status is "High"
THROUGHPUT_BUDGET_STATUS_OK = "OK"
THROUGHPUT_BUDGET_STATUS_HIGH = "High"
THROUGHPUT_BUDGET_STATUS_OVER = "Over budget"

# ── EV diversion parameters ───────────────────────────────────────────────────
# Minimum power for an OCPP EV charger to start — 6A × 230V single-phase.
# If the available surplus is below this, the charger will refuse to start.
# This is also the surplus at which the EV Solar Surplus signal reads Available
# and the Zappi is switched to Eco+.
# Based on IEC 61851 minimum of 6A (1,380W at 230V). Single-phase assumption.
EV_CHARGER_MIN_POWER_W = 1380

# ── Configurable thresholds — exposed in config flow ─────────────────────────
# (SURPLUS_DIVERT_SOC_THRESHOLD and SURPLUS_DIVERT_MIN_POWER_W already defined above,
#  but not yet exposed to the user. Config keys added here for wiring them in.)
CONF_SURPLUS_DIVERT_SOC = "surplus_divert_soc_pct"
CONF_SURPLUS_DIVERT_MIN_W = "surplus_divert_min_power_w"

# Cheap rate floor — top up during cheap window if battery drops below this
CONF_CHEAP_RATE_FLOOR_SOC = "cheap_rate_floor_soc"
DEFAULT_CHEAP_RATE_FLOOR_SOC = 40  # % — 0 disables the floor

# ── GivTCP register write safety ──────────────────────────────────────────────
# GivEnergy inverters have ~1M total register write capacity. Limiting unnecessary
# writes protects hardware lifetime. Predbat documents this as a known issue.
GIVTCP_MAX_WRITE_RETRIES = 3          # attempts per write before giving up
GIVTCP_WRITE_RETRY_SLEEP_S = 2        # seconds between retry attempts
GIVTCP_WRITE_LIFETIME_WARN = 500_000  # log a warning at this write count (~50% of rated)
GIVTCP_MIN_WRITE_INTERVAL_S = 300     # minimum seconds before the same value is rewritten
# How long a running element stays on while a required sensor is unavailable.
# Same value as the write interval, but a separate setting.
SENSOR_OUTAGE_HOLD_LIMIT_S = 300
GIVTCP_MIN_CHARGE_TARGET_PCT = 4      # lowest charge target GivTCP accepts
GIVTCP_MAX_CHARGE_TARGET_PCT = 100    # highest charge target GivTCP accepts
