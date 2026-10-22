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

# ruff: noqa: F401
# The imports below re-export every name from the split modules.
from .conf import (
    CONF_ALT_HEAT_COST,
    CONF_ALT_HEAT_COST_ENTITY,
    CONF_ALT_HEAT_COST_UNIT,
    CONF_ALT_HEAT_ENABLED,
    CONF_ALT_HEAT_LABEL,
    CONF_BASE_RATE,
    CONF_BASE_RATE_NAME,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_COST,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_THROUGHPUT_BUDGET,
    CONF_BILL_START_DAY,
    CONF_CAR_EFFICIENCY_KWH_PER_100KM,
    CONF_CARBON_INTENSITY_ENTITY,
    CONF_CHARGE_END_TIME_ENTITY,
    CONF_CHARGE_REPLAN,
    CONF_CHARGE_SHOULDER_MONTHS,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_CHARGE_WINTER_MONTHS,
    CONF_CHARGE_WINTER_USES_FORECAST,
    CONF_CHEAP_RATE_FLOOR_SOC,
    CONF_CURRENCY,
    CONF_DASHBOARD_URL_PATH,
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
    CONF_IMMERSION_MAX_RUN_MINUTES,
    CONF_IMMERSION_MIN_TEMP,
    CONF_IMMERSION_READY_TIMES,
    CONF_IMMERSION_RUN_LIMIT_WARNING,
    CONF_IMMERSION_SWITCH,
    CONF_IMMERSION_TARGET_TEMP,
    CONF_IMMERSION_TEMP_SENSOR,
    CONF_IMMERSION_WATTAGE,
    CONF_INVERTER_MAX_OUTPUT,
    CONF_INVERTER_MAX_OUTPUT_ENTITY,
    CONF_INVERTER_SERIAL,
    CONF_INVERTER_TEMP_ENTITY,
    CONF_OVERNIGHT_CHARGE_TARGET,
    CONF_PSO_LEVY,
    CONF_RATE_PERIODS,
    CONF_SKIP_CHARGE_SOC_THRESHOLD,
    CONF_SOLAR_POWER,
    CONF_STANDING_CHARGE,
    CONF_STORED_DASHBOARD_URL_PATH,
    CONF_SURPLUS_DIVERT_MIN_W,
    CONF_SURPLUS_DIVERT_SOC,
    CONF_TARGET_SOC_ENTITY,
    CONF_TARIFF_CHANGES,
    CONF_TARIFF_REVIEWED_ON,
    CONF_VAT_RATE,
    CONF_VERBOSE_LOGGING,
)
from .defaults import (
    DEFAULT_ALT_HEAT_LABEL,
    DEFAULT_BASE_RATE,
    DEFAULT_BASE_RATE_NAME,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_BATTERY_COST,
    DEFAULT_BATTERY_MIN_SOC,
    DEFAULT_BATTERY_THROUGHPUT_BUDGET,
    DEFAULT_BILL_START_DAY,
    DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM,
    DEFAULT_CHARGE_REPLAN,
    DEFAULT_CHEAP_RATE_FLOOR_SOC,
    DEFAULT_CURRENCY,
    DEFAULT_DISCOUNT_RATE,
    DEFAULT_DRY_RUN,
    DEFAULT_EXPORT_RATE,
    DEFAULT_FORECAST_CONSERVATISM,
    DEFAULT_IMMERSION_HYSTERESIS,
    DEFAULT_IMMERSION_MAX_RUN_MINUTES,
    DEFAULT_IMMERSION_MIN_TEMP,
    DEFAULT_IMMERSION_RUN_LIMIT_WARNING,
    DEFAULT_IMMERSION_TARGET_TEMP,
    DEFAULT_IMMERSION_WATTAGE,
    DEFAULT_INVERTER_MAX_OUTPUT,
    DEFAULT_OVERNIGHT_CHARGE_TARGET,
    DEFAULT_PSO_LEVY,
    DEFAULT_RATE_PERIODS,
    DEFAULT_SKIP_CHARGE_SOC_THRESHOLD,
    DEFAULT_STANDING_CHARGE,
    DEFAULT_VAT_RATE,
    DEFAULT_VERBOSE_LOGGING,
)
from .lib.ev.defaults import (
    EV_BASE_RATE_ALERT_DELAY_S,
    EV_CHARGER_MIN_POWER_W,
    EV_RECENT_SESSIONS_MAX,
)
from .lib.givtcp.defaults import (
    GIVTCP_FROZEN_AFTER_S,
)
from .lib.guards.defaults import (
    COUNTER_RISE_FLOOR_KWH,
    COUNTER_RISE_MARGIN,
    COUNTER_UNIT_CHANGE_MIN_KWH,
    COUNTER_UNIT_CHANGE_RATIO,
)
from .lib.heating.defaults import (
    CHARGE_WINDOW_MARGIN,
    IMMERSION_ASSUMED_TANK_LITRES,
    IMMERSION_RATE_DAYS_KEPT,
    IMMERSION_RATE_RUN_MIN_MINUTES,
    IMMERSION_RATE_RUN_MIN_RISE_C,
    IMMERSION_RATE_RUNS_KEPT,
    IMMERSION_SWITCH_COOLDOWN_MINUTES,
    SENSOR_OUTAGE_HOLD_LIMIT_S,
)
from .tuning import (
    ALT_HEAT_ADVICE_HORIZON_HOURS,
    ALT_HEAT_LABEL_MAX_LENGTH,
    ALT_HEAT_SCHEDULE_MAX_WINDOWS,
    ALT_HEAT_SCHEDULE_MIN_DAYS,
    ALT_HEAT_SCHEDULE_MIN_HOUR_KWH,
    ALT_HEAT_SCHEDULE_MIN_SAVING_PER_WEEK,
    ALT_HEAT_SCHEDULE_RECORD_DAYS,
    ALT_HEAT_SCHEDULE_REPEAT_ONE_IN,
    ALT_HEAT_TRIGGER_MARGIN_C,
    APPLIANCE_MIN_BATTERY_SOC,
    APPLIANCE_RATE_THRESHOLD,
    BATTERY_EFFICIENCY_MIN_KWH,
    BATTERY_FULL_SOC_PCT,
    BATTERY_LIFE_ESTIMATE_MIN_DAYS,
    BATTERY_MAX_SOC_STEP_PCT,
    BATTERY_RATED_CYCLES,
    CARBON_HIGH_THRESHOLD,
    CARBON_LOW_THRESHOLD,
    CHARGE_EV_SOC_BONUS,
    CHARGE_FORECAST_CORRECTION_MAX,
    CHARGE_FORECAST_CORRECTION_MIN,
    CHARGE_FORECAST_CORRECTION_MIN_DAYS,
    CHARGE_FORECAST_CORRECTION_MIN_KWH,
    CHARGE_LOAD_PROFILE_MIN_COVERAGE,
    CHARGE_LOAD_PROFILE_MIN_DAYS,
    CHARGE_LOAD_PROFILE_SAME_WEEKDAY_MIN_DAYS,
    CHARGE_MIN_TARGET_HEADROOM_PCT,
    CHARGE_PEAK_SOLAR_HOURS,
    CHARGE_SHOULDER_MIN_SOC,
    CHARGE_SKIP_HEADROOM,
    CHARGE_SOLAR_USABLE_FRACTION,
    CHARGE_STRONG_BUFFER,
    CHARGE_SUMMER_MIN_TARGET_SOC,
    CHARGE_TARGET_HOLD_LARGE_STEP_PCT,
    CHARGE_TARGET_HOLD_MIN_MINUTES,
    CHARGE_TARGET_HOLD_STEP_PCT,
    CHARGE_WINDOW_HOLD_LARGE_STEP_MINUTES,
    CHARGE_WINDOW_HOLD_STEP_MINUTES,
    CHARGE_WINDOW_ROUND_MINUTES,
    CHARGE_WINTER_SKIP_SOC_PCT,
    CHARGE_WRITE_RETRY_OFFSETS_MIN,
    CHARGE_WRITE_RETRY_STOP_BEFORE_END_MIN,
    CLIPPING_THRESHOLD_PERCENT,
    CONFLICT_MIN_CHANGES,
    CONFLICT_WINDOW_DAYS,
    INVERTER_TEMP_CRITICAL,
    INVERTER_TEMP_DERATING,
    INVERTER_TEMP_WARM,
    NIGHT_SURVIVAL_WARNING_MARGIN_PCT,
    OIL_BOILER_EFFICIENCY_PCT,
    OIL_KWH_PER_LITRE,
    POWER_DIRECTION_BAND_W,
    REGISTER_WRITE_LOG_MAX_ENTRIES,
    REPLAN_FORECAST_CHANGE_MIN_KWH,
    REPLAN_FORECAST_CHANGE_PCT,
    REPLAN_LATE_CHECK_AFTER_MIN,
    REPLAN_LATE_CHECK_BEFORE_END_MIN,
    REPLAN_MAX_WRITES,
    REPLAN_MIN_CHANGE_PTS,
    REPLAN_MIN_REMAINING_MIN,
    SOLAR_DAY_DEBOUNCE_MINUTES,
    SOLAR_NOISE_FLOOR_W,
    SOLAR_SUNRISE_HOUR,
    STATE_MAX_LENGTH,
    SURPLUS_DIVERT_MIN_POWER_W,
    SURPLUS_DIVERT_SOC_THRESHOLD,
    TARIFF_REVIEW_STALE_DAYS,
    THROUGHPUT_BUDGET_HIGH_PCT,
    UPDATE_INTERVAL_SECONDS,
)

DOMAIN = "givenergy_inverter_manager"
INTEGRATION_VERSION = "0.21.0b3"  # keep in sync with manifest.json
NAME = "GivEnergy Inverter Manager"
DEVICE_MANUFACTURER = "macuistin"  # shown on the device page; GivEnergy does not make this

# ── Service actions ───────────────────────────────────────────────────────────
SERVICE_SUGGEST_APPLIANCE = "suggest_appliance_run"
SERVICE_COMPARE_TARIFF = "compare_tariff"
SERVICE_YEAR_ON_YEAR = "year_on_year_summary"
SERVICE_EXPORT_ENERGY_DATA = "export_energy_data"
SERVICE_GET_ROI_SUMMARY = "get_roi_summary"
SERVICE_GET_DASHBOARD_YAML = "get_dashboard_yaml"
SERVICE_UPDATE_DASHBOARD = "update_dashboard"

# ── Tariff ────────────────────────────────────────────────────────────────────
# The only values a dated change carries. Standing charge, levy, VAT and discount are not dated:
# the bill estimate reverses them from the stored import cost, which needs one value per period.
TARIFF_RATE_KEYS = (CONF_BASE_RATE, CONF_BASE_RATE_NAME, CONF_EXPORT_RATE, CONF_RATE_PERIODS)

# ── Solar forecast ────────────────────────────────────────────────────────────
FORECAST_PROVIDER_FORECAST_SOLAR = "forecast_solar"
FORECAST_PROVIDER_SOLCAST = "solcast"
# Attribute of a Solcast forecast sensor holding that period's P10 total in kWh.
FORECAST_P10_ATTRIBUTE = "estimate10"
# Solcast's per-period forecast attributes, in the order the plan prefers them: 30-minute periods,
# then hourly ones. Each period has `period_start` and `pv_estimate` (average kW).
FORECAST_PERIOD_ATTRIBUTES = ("detailedForecast", "detailedHourly")

# ── Carbon intensity ──────────────────────────────────────────────────────────
CARBON_STATUS_LOW = "Low"
CARBON_STATUS_MEDIUM = "Medium"
CARBON_STATUS_HIGH = "High"
CARBON_STATUS_UNKNOWN = "Unknown"

# ── Supported currencies ──────────────────────────────────────────────────────
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
DEFAULT_CURRENCY_SYMBOL = CURRENCIES[DEFAULT_CURRENCY]

# ── Alternative water heating advice (core/alt_heat_advice.py) ────────────────
# What the cost is the cost of. A litre is the price of a litre of heating oil, turned into heat
# with the two fixed assumptions below. A kWh of heat is the cost of one kWh delivered to the
# water, boiler efficiency already included.
ALT_HEAT_UNIT_LITRE = "litre"
ALT_HEAT_UNIT_KWH_HEAT = "kwh_heat"
ALT_HEAT_UNITS = (ALT_HEAT_UNIT_LITRE, ALT_HEAT_UNIT_KWH_HEAT)
DEFAULT_ALT_HEAT_UNIT = ALT_HEAT_UNIT_LITRE
# The oil price options of 0.17 and earlier. Setup converts them once
# (core/alt_heat_conversion.py) and nothing reads them afterwards. They are not CONF_ names
# because they are no longer options.
LEGACY_OIL_PRICE_PER_LITRE = "oil_price_per_litre"
LEGACY_OIL_PRICE_ENTITY = "oil_price_entity"

# ── Dry run mode ──────────────────────────────────────────────────────────────
# A file with this name in the Home Assistant config directory marks a test instance. While it
# exists, dry run is on whatever the saved option says. Only the file's presence is read.
TEST_INSTANCE_MARKER = ".givenergy_test_instance"

# ── Inverter temperature thresholds ───────────────────────────────────────────
# Inverter temperature status labels
INVERTER_TEMP_STATUS_NORMAL = "Normal"
INVERTER_TEMP_STATUS_WARM = "Warm"
INVERTER_TEMP_STATUS_DERATING = "Derating"
INVERTER_TEMP_STATUS_CRITICAL = "Critical"
INVERTER_TEMP_STATUS_UNKNOWN = "Unknown"

# ── HA platforms exposed by this integration ──────────────────────────────────
PLATFORMS = ["sensor", "switch", "number"]

# ── Battery throughput budget ─────────────────────────────────────────────────
THROUGHPUT_BUDGET_STATUS_OK = "OK"
THROUGHPUT_BUDGET_STATUS_HIGH = "High"
THROUGHPUT_BUDGET_STATUS_OVER = "Over budget"

# ── Register write log ────────────────────────────────────────────────────────
REPAIRS_PATH = "/config/repairs"  # Home Assistant's Repairs page, linked from Active Repairs

# ── Sensor state text ─────────────────────────────────────────────────────────
# The attribute that carries the full text of a sensor whose state had to be cut to fit.
# Attributes have no 255 character limit.
ATTR_FULL_TEXT = "full_text"
