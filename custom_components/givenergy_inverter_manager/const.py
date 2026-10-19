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

from .conf import (
    CONF_ALT_HEAT_COST as CONF_ALT_HEAT_COST,
)
from .conf import (
    CONF_ALT_HEAT_COST_ENTITY as CONF_ALT_HEAT_COST_ENTITY,
)
from .conf import (
    CONF_ALT_HEAT_COST_UNIT as CONF_ALT_HEAT_COST_UNIT,
)
from .conf import (
    CONF_ALT_HEAT_ENABLED as CONF_ALT_HEAT_ENABLED,
)
from .conf import (
    CONF_ALT_HEAT_LABEL as CONF_ALT_HEAT_LABEL,
)
from .conf import (
    CONF_BASE_RATE as CONF_BASE_RATE,
)
from .conf import (
    CONF_BASE_RATE_NAME as CONF_BASE_RATE_NAME,
)
from .conf import (
    CONF_BATTERY_CAPACITY as CONF_BATTERY_CAPACITY,
)
from .conf import (
    CONF_BATTERY_COST as CONF_BATTERY_COST,
)
from .conf import (
    CONF_BATTERY_MIN_SOC as CONF_BATTERY_MIN_SOC,
)
from .conf import (
    CONF_BATTERY_POWER as CONF_BATTERY_POWER,
)
from .conf import (
    CONF_BATTERY_SOC as CONF_BATTERY_SOC,
)
from .conf import (
    CONF_BATTERY_THROUGHPUT_BUDGET as CONF_BATTERY_THROUGHPUT_BUDGET,
)
from .conf import (
    CONF_BILL_START_DAY as CONF_BILL_START_DAY,
)
from .conf import (
    CONF_CAR_EFFICIENCY_KWH_PER_100KM as CONF_CAR_EFFICIENCY_KWH_PER_100KM,
)
from .conf import (
    CONF_CARBON_INTENSITY_ENTITY as CONF_CARBON_INTENSITY_ENTITY,
)
from .conf import (
    CONF_CHARGE_END_TIME_ENTITY as CONF_CHARGE_END_TIME_ENTITY,
)
from .conf import (
    CONF_CHARGE_REPLAN as CONF_CHARGE_REPLAN,
)
from .conf import (
    CONF_CHARGE_SHOULDER_MONTHS as CONF_CHARGE_SHOULDER_MONTHS,
)
from .conf import (
    CONF_CHARGE_START_TIME_ENTITY as CONF_CHARGE_START_TIME_ENTITY,
)
from .conf import (
    CONF_CHARGE_WINTER_MONTHS as CONF_CHARGE_WINTER_MONTHS,
)
from .conf import (
    CONF_CHARGE_WINTER_USES_FORECAST as CONF_CHARGE_WINTER_USES_FORECAST,
)
from .conf import (
    CONF_CHEAP_RATE_FLOOR_SOC as CONF_CHEAP_RATE_FLOOR_SOC,
)
from .conf import (
    CONF_CURRENCY as CONF_CURRENCY,
)
from .conf import (
    CONF_DASHBOARD_URL_PATH as CONF_DASHBOARD_URL_PATH,
)
from .conf import (
    CONF_DISCOUNT_RATE as CONF_DISCOUNT_RATE,
)
from .conf import (
    CONF_DRY_RUN as CONF_DRY_RUN,
)
from .conf import (
    CONF_ENABLE_CHARGE_SCHEDULE as CONF_ENABLE_CHARGE_SCHEDULE,
)
from .conf import (
    CONF_ENABLE_CHARGE_TARGET as CONF_ENABLE_CHARGE_TARGET,
)
from .conf import (
    CONF_EXPORT_RATE as CONF_EXPORT_RATE,
)
from .conf import (
    CONF_FORECAST_CONSERVATISM as CONF_FORECAST_CONSERVATISM,
)
from .conf import (
    CONF_FORECAST_ENTITY as CONF_FORECAST_ENTITY,
)
from .conf import (
    CONF_FORECAST_ENTITY_D2 as CONF_FORECAST_ENTITY_D2,
)
from .conf import (
    CONF_FORECAST_ENTITY_P10 as CONF_FORECAST_ENTITY_P10,
)
from .conf import (
    CONF_FORECAST_PROVIDER as CONF_FORECAST_PROVIDER,
)
from .conf import (
    CONF_GRID_POWER as CONF_GRID_POWER,
)
from .conf import (
    CONF_HOUSE_LOAD as CONF_HOUSE_LOAD,
)
from .conf import (
    CONF_IMMERSION_HYSTERESIS as CONF_IMMERSION_HYSTERESIS,
)
from .conf import (
    CONF_IMMERSION_MAX_RUN_MINUTES as CONF_IMMERSION_MAX_RUN_MINUTES,
)
from .conf import (
    CONF_IMMERSION_MIN_TEMP as CONF_IMMERSION_MIN_TEMP,
)
from .conf import (
    CONF_IMMERSION_READY_TIMES as CONF_IMMERSION_READY_TIMES,
)
from .conf import (
    CONF_IMMERSION_RUN_LIMIT_WARNING as CONF_IMMERSION_RUN_LIMIT_WARNING,
)
from .conf import (
    CONF_IMMERSION_SWITCH as CONF_IMMERSION_SWITCH,
)
from .conf import (
    CONF_IMMERSION_TARGET_TEMP as CONF_IMMERSION_TARGET_TEMP,
)
from .conf import (
    CONF_IMMERSION_TEMP_SENSOR as CONF_IMMERSION_TEMP_SENSOR,
)
from .conf import (
    CONF_IMMERSION_WATTAGE as CONF_IMMERSION_WATTAGE,
)
from .conf import (
    CONF_INVERTER_MAX_OUTPUT as CONF_INVERTER_MAX_OUTPUT,
)
from .conf import (  # noqa: F401
    CONF_INVERTER_SERIAL as CONF_INVERTER_SERIAL,
)
from .conf import (
    CONF_INVERTER_TEMP_ENTITY as CONF_INVERTER_TEMP_ENTITY,
)
from .conf import (
    CONF_OVERNIGHT_CHARGE_TARGET as CONF_OVERNIGHT_CHARGE_TARGET,
)
from .conf import (
    CONF_PSO_LEVY as CONF_PSO_LEVY,
)
from .conf import (
    CONF_RATE_PERIODS as CONF_RATE_PERIODS,
)
from .conf import (
    CONF_SKIP_CHARGE_SOC_THRESHOLD as CONF_SKIP_CHARGE_SOC_THRESHOLD,
)
from .conf import (
    CONF_SOLAR_POWER as CONF_SOLAR_POWER,
)
from .conf import (
    CONF_STANDING_CHARGE as CONF_STANDING_CHARGE,
)
from .conf import (
    CONF_STORED_DASHBOARD_URL_PATH as CONF_STORED_DASHBOARD_URL_PATH,
)
from .conf import (
    CONF_SURPLUS_DIVERT_MIN_W as CONF_SURPLUS_DIVERT_MIN_W,
)
from .conf import (
    CONF_SURPLUS_DIVERT_SOC as CONF_SURPLUS_DIVERT_SOC,
)
from .conf import (
    CONF_TARGET_SOC_ENTITY as CONF_TARGET_SOC_ENTITY,
)
from .conf import (
    CONF_TARIFF_CHANGES as CONF_TARIFF_CHANGES,
)
from .conf import (
    CONF_TARIFF_REVIEWED_ON as CONF_TARIFF_REVIEWED_ON,
)
from .conf import (
    CONF_VAT_RATE as CONF_VAT_RATE,
)
from .conf import (
    CONF_VERBOSE_LOGGING as CONF_VERBOSE_LOGGING,
)
from .defaults import (
    DEFAULT_ALT_HEAT_LABEL as DEFAULT_ALT_HEAT_LABEL,
)
from .defaults import (
    DEFAULT_BASE_RATE as DEFAULT_BASE_RATE,
)
from .defaults import (
    DEFAULT_BASE_RATE_NAME as DEFAULT_BASE_RATE_NAME,
)
from .defaults import (
    DEFAULT_BATTERY_CAPACITY as DEFAULT_BATTERY_CAPACITY,
)
from .defaults import (
    DEFAULT_BATTERY_COST as DEFAULT_BATTERY_COST,
)
from .defaults import (
    DEFAULT_BATTERY_MIN_SOC as DEFAULT_BATTERY_MIN_SOC,
)
from .defaults import (
    DEFAULT_BATTERY_THROUGHPUT_BUDGET as DEFAULT_BATTERY_THROUGHPUT_BUDGET,
)
from .defaults import (
    DEFAULT_BILL_START_DAY as DEFAULT_BILL_START_DAY,
)
from .defaults import (
    DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM as DEFAULT_CAR_EFFICIENCY_KWH_PER_100KM,
)
from .defaults import (
    DEFAULT_CHARGE_REPLAN as DEFAULT_CHARGE_REPLAN,
)
from .defaults import (
    DEFAULT_CHEAP_RATE_FLOOR_SOC as DEFAULT_CHEAP_RATE_FLOOR_SOC,
)
from .defaults import (
    DEFAULT_CURRENCY as DEFAULT_CURRENCY,
)
from .defaults import (
    DEFAULT_DISCOUNT_RATE as DEFAULT_DISCOUNT_RATE,
)
from .defaults import (
    DEFAULT_DRY_RUN as DEFAULT_DRY_RUN,
)
from .defaults import (
    DEFAULT_EXPORT_RATE as DEFAULT_EXPORT_RATE,
)
from .defaults import (  # noqa: F401
    DEFAULT_FORECAST_CONSERVATISM as DEFAULT_FORECAST_CONSERVATISM,
)
from .defaults import (
    DEFAULT_IMMERSION_HYSTERESIS as DEFAULT_IMMERSION_HYSTERESIS,
)
from .defaults import (
    DEFAULT_IMMERSION_MAX_RUN_MINUTES as DEFAULT_IMMERSION_MAX_RUN_MINUTES,
)
from .defaults import (
    DEFAULT_IMMERSION_MIN_TEMP as DEFAULT_IMMERSION_MIN_TEMP,
)
from .defaults import (
    DEFAULT_IMMERSION_RUN_LIMIT_WARNING as DEFAULT_IMMERSION_RUN_LIMIT_WARNING,
)
from .defaults import (
    DEFAULT_IMMERSION_TARGET_TEMP as DEFAULT_IMMERSION_TARGET_TEMP,
)
from .defaults import (
    DEFAULT_IMMERSION_WATTAGE as DEFAULT_IMMERSION_WATTAGE,
)
from .defaults import (
    DEFAULT_INVERTER_MAX_OUTPUT as DEFAULT_INVERTER_MAX_OUTPUT,
)
from .defaults import (
    DEFAULT_OVERNIGHT_CHARGE_TARGET as DEFAULT_OVERNIGHT_CHARGE_TARGET,
)
from .defaults import (
    DEFAULT_PSO_LEVY as DEFAULT_PSO_LEVY,
)
from .defaults import (
    DEFAULT_RATE_PERIODS as DEFAULT_RATE_PERIODS,
)
from .defaults import (
    DEFAULT_SKIP_CHARGE_SOC_THRESHOLD as DEFAULT_SKIP_CHARGE_SOC_THRESHOLD,
)
from .defaults import (
    DEFAULT_STANDING_CHARGE as DEFAULT_STANDING_CHARGE,
)
from .defaults import (
    DEFAULT_VAT_RATE as DEFAULT_VAT_RATE,
)
from .defaults import (
    DEFAULT_VERBOSE_LOGGING as DEFAULT_VERBOSE_LOGGING,
)
from .tuning import (
    ALT_HEAT_ADVICE_HORIZON_HOURS as ALT_HEAT_ADVICE_HORIZON_HOURS,
)
from .tuning import (
    ALT_HEAT_LABEL_MAX_LENGTH as ALT_HEAT_LABEL_MAX_LENGTH,
)
from .tuning import (
    ALT_HEAT_SCHEDULE_MAX_WINDOWS as ALT_HEAT_SCHEDULE_MAX_WINDOWS,
)
from .tuning import (
    ALT_HEAT_SCHEDULE_MIN_DAYS as ALT_HEAT_SCHEDULE_MIN_DAYS,
)
from .tuning import (
    ALT_HEAT_SCHEDULE_MIN_HOUR_KWH as ALT_HEAT_SCHEDULE_MIN_HOUR_KWH,
)
from .tuning import (
    ALT_HEAT_SCHEDULE_MIN_SAVING_PER_WEEK as ALT_HEAT_SCHEDULE_MIN_SAVING_PER_WEEK,
)
from .tuning import (
    ALT_HEAT_SCHEDULE_RECORD_DAYS as ALT_HEAT_SCHEDULE_RECORD_DAYS,
)
from .tuning import (
    ALT_HEAT_SCHEDULE_REPEAT_ONE_IN as ALT_HEAT_SCHEDULE_REPEAT_ONE_IN,
)
from .tuning import (
    ALT_HEAT_TRIGGER_MARGIN_C as ALT_HEAT_TRIGGER_MARGIN_C,
)
from .tuning import (
    APPLIANCE_MIN_BATTERY_SOC as APPLIANCE_MIN_BATTERY_SOC,
)
from .tuning import (
    APPLIANCE_RATE_THRESHOLD as APPLIANCE_RATE_THRESHOLD,
)
from .tuning import (
    BATTERY_EFFICIENCY_MIN_KWH as BATTERY_EFFICIENCY_MIN_KWH,
)
from .tuning import (
    BATTERY_FULL_SOC_PCT as BATTERY_FULL_SOC_PCT,
)
from .tuning import (
    BATTERY_LIFE_ESTIMATE_MIN_DAYS as BATTERY_LIFE_ESTIMATE_MIN_DAYS,
)
from .tuning import (
    BATTERY_MAX_SOC_STEP_PCT as BATTERY_MAX_SOC_STEP_PCT,
)
from .tuning import (
    BATTERY_RATED_CYCLES as BATTERY_RATED_CYCLES,
)
from .tuning import (
    CARBON_HIGH_THRESHOLD as CARBON_HIGH_THRESHOLD,
)
from .tuning import (
    CARBON_LOW_THRESHOLD as CARBON_LOW_THRESHOLD,
)
from .tuning import (
    CHARGE_EV_SOC_BONUS as CHARGE_EV_SOC_BONUS,
)
from .tuning import (
    CHARGE_FORECAST_CORRECTION_MAX as CHARGE_FORECAST_CORRECTION_MAX,
)
from .tuning import (
    CHARGE_FORECAST_CORRECTION_MIN as CHARGE_FORECAST_CORRECTION_MIN,
)
from .tuning import (
    CHARGE_FORECAST_CORRECTION_MIN_DAYS as CHARGE_FORECAST_CORRECTION_MIN_DAYS,
)
from .tuning import (
    CHARGE_FORECAST_CORRECTION_MIN_KWH as CHARGE_FORECAST_CORRECTION_MIN_KWH,
)
from .tuning import (
    CHARGE_LOAD_PROFILE_MIN_COVERAGE as CHARGE_LOAD_PROFILE_MIN_COVERAGE,
)
from .tuning import (
    CHARGE_LOAD_PROFILE_MIN_DAYS as CHARGE_LOAD_PROFILE_MIN_DAYS,
)
from .tuning import (
    CHARGE_LOAD_PROFILE_SAME_WEEKDAY_MIN_DAYS as CHARGE_LOAD_PROFILE_SAME_WEEKDAY_MIN_DAYS,
)
from .tuning import (
    CHARGE_MIN_TARGET_HEADROOM_PCT as CHARGE_MIN_TARGET_HEADROOM_PCT,
)
from .tuning import (
    CHARGE_PEAK_SOLAR_HOURS as CHARGE_PEAK_SOLAR_HOURS,
)
from .tuning import (
    CHARGE_SHOULDER_MIN_SOC as CHARGE_SHOULDER_MIN_SOC,
)
from .tuning import (
    CHARGE_SKIP_HEADROOM as CHARGE_SKIP_HEADROOM,
)
from .tuning import (
    CHARGE_SOLAR_USABLE_FRACTION as CHARGE_SOLAR_USABLE_FRACTION,
)
from .tuning import (
    CHARGE_STRONG_BUFFER as CHARGE_STRONG_BUFFER,
)
from .tuning import (
    CHARGE_SUMMER_MIN_TARGET_SOC as CHARGE_SUMMER_MIN_TARGET_SOC,
)
from .tuning import (
    CHARGE_TARGET_HOLD_LARGE_STEP_PCT as CHARGE_TARGET_HOLD_LARGE_STEP_PCT,
)
from .tuning import (
    CHARGE_TARGET_HOLD_MIN_MINUTES as CHARGE_TARGET_HOLD_MIN_MINUTES,
)
from .tuning import (
    CHARGE_TARGET_HOLD_STEP_PCT as CHARGE_TARGET_HOLD_STEP_PCT,
)
from .tuning import (
    CHARGE_WINDOW_HOLD_LARGE_STEP_MINUTES as CHARGE_WINDOW_HOLD_LARGE_STEP_MINUTES,
)
from .tuning import (
    CHARGE_WINDOW_HOLD_STEP_MINUTES as CHARGE_WINDOW_HOLD_STEP_MINUTES,
)
from .tuning import (
    CHARGE_WINDOW_MARGIN as CHARGE_WINDOW_MARGIN,
)
from .tuning import (
    CHARGE_WINDOW_ROUND_MINUTES as CHARGE_WINDOW_ROUND_MINUTES,
)
from .tuning import (
    CHARGE_WINTER_SKIP_SOC_PCT as CHARGE_WINTER_SKIP_SOC_PCT,
)
from .tuning import (
    CHARGE_WRITE_RETRY_OFFSETS_MIN as CHARGE_WRITE_RETRY_OFFSETS_MIN,
)
from .tuning import (
    CHARGE_WRITE_RETRY_STOP_BEFORE_END_MIN as CHARGE_WRITE_RETRY_STOP_BEFORE_END_MIN,
)
from .tuning import (
    CLIPPING_THRESHOLD_PERCENT as CLIPPING_THRESHOLD_PERCENT,
)
from .tuning import (
    CONFLICT_MIN_CHANGES as CONFLICT_MIN_CHANGES,
)
from .tuning import (
    CONFLICT_WINDOW_DAYS as CONFLICT_WINDOW_DAYS,
)
from .tuning import (
    COUNTER_RISE_FLOOR_KWH as COUNTER_RISE_FLOOR_KWH,
)
from .tuning import (
    COUNTER_RISE_MARGIN as COUNTER_RISE_MARGIN,
)
from .tuning import (
    COUNTER_UNIT_CHANGE_MIN_KWH as COUNTER_UNIT_CHANGE_MIN_KWH,
)
from .tuning import (
    COUNTER_UNIT_CHANGE_RATIO as COUNTER_UNIT_CHANGE_RATIO,
)
from .tuning import (
    EV_BASE_RATE_ALERT_DELAY_S as EV_BASE_RATE_ALERT_DELAY_S,
)
from .tuning import (
    EV_CHARGER_MIN_POWER_W as EV_CHARGER_MIN_POWER_W,
)
from .tuning import (
    EV_RECENT_SESSIONS_MAX as EV_RECENT_SESSIONS_MAX,
)
from .tuning import (
    GIVTCP_FROZEN_AFTER_S as GIVTCP_FROZEN_AFTER_S,
)
from .tuning import (
    IMMERSION_ASSUMED_TANK_LITRES as IMMERSION_ASSUMED_TANK_LITRES,
)
from .tuning import (
    IMMERSION_RATE_DAYS_KEPT as IMMERSION_RATE_DAYS_KEPT,
)
from .tuning import (
    IMMERSION_RATE_RUN_MIN_MINUTES as IMMERSION_RATE_RUN_MIN_MINUTES,
)
from .tuning import (
    IMMERSION_RATE_RUN_MIN_RISE_C as IMMERSION_RATE_RUN_MIN_RISE_C,
)
from .tuning import (
    IMMERSION_RATE_RUNS_KEPT as IMMERSION_RATE_RUNS_KEPT,
)
from .tuning import (
    IMMERSION_SWITCH_COOLDOWN_MINUTES as IMMERSION_SWITCH_COOLDOWN_MINUTES,
)
from .tuning import (
    INVERTER_TEMP_CRITICAL as INVERTER_TEMP_CRITICAL,
)
from .tuning import (
    INVERTER_TEMP_DERATING as INVERTER_TEMP_DERATING,
)
from .tuning import (
    INVERTER_TEMP_WARM as INVERTER_TEMP_WARM,
)
from .tuning import (
    NIGHT_SURVIVAL_WARNING_MARGIN_PCT as NIGHT_SURVIVAL_WARNING_MARGIN_PCT,
)
from .tuning import (
    OIL_BOILER_EFFICIENCY_PCT as OIL_BOILER_EFFICIENCY_PCT,
)
from .tuning import (
    OIL_KWH_PER_LITRE as OIL_KWH_PER_LITRE,
)
from .tuning import (
    POWER_DIRECTION_BAND_W as POWER_DIRECTION_BAND_W,
)
from .tuning import (
    REGISTER_WRITE_LOG_MAX_ENTRIES as REGISTER_WRITE_LOG_MAX_ENTRIES,
)
from .tuning import (
    REPLAN_FORECAST_CHANGE_MIN_KWH as REPLAN_FORECAST_CHANGE_MIN_KWH,
)
from .tuning import (
    REPLAN_FORECAST_CHANGE_PCT as REPLAN_FORECAST_CHANGE_PCT,
)
from .tuning import (
    REPLAN_LATE_CHECK_AFTER_MIN as REPLAN_LATE_CHECK_AFTER_MIN,
)
from .tuning import (
    REPLAN_LATE_CHECK_BEFORE_END_MIN as REPLAN_LATE_CHECK_BEFORE_END_MIN,
)
from .tuning import (
    REPLAN_MAX_WRITES as REPLAN_MAX_WRITES,
)
from .tuning import (
    REPLAN_MIN_CHANGE_PTS as REPLAN_MIN_CHANGE_PTS,
)
from .tuning import (
    REPLAN_MIN_REMAINING_MIN as REPLAN_MIN_REMAINING_MIN,
)
from .tuning import (
    SENSOR_OUTAGE_HOLD_LIMIT_S as SENSOR_OUTAGE_HOLD_LIMIT_S,
)
from .tuning import (
    SOLAR_DAY_DEBOUNCE_MINUTES as SOLAR_DAY_DEBOUNCE_MINUTES,
)
from .tuning import (
    SOLAR_NOISE_FLOOR_W as SOLAR_NOISE_FLOOR_W,
)
from .tuning import (
    SOLAR_SUNRISE_HOUR as SOLAR_SUNRISE_HOUR,
)
from .tuning import (
    STATE_MAX_LENGTH as STATE_MAX_LENGTH,
)
from .tuning import (
    SURPLUS_DIVERT_MIN_POWER_W as SURPLUS_DIVERT_MIN_POWER_W,
)
from .tuning import (
    SURPLUS_DIVERT_SOC_THRESHOLD as SURPLUS_DIVERT_SOC_THRESHOLD,
)
from .tuning import (  # noqa: F401
    TARIFF_REVIEW_STALE_DAYS as TARIFF_REVIEW_STALE_DAYS,
)
from .tuning import (
    THROUGHPUT_BUDGET_HIGH_PCT as THROUGHPUT_BUDGET_HIGH_PCT,
)
from .tuning import (
    UPDATE_INTERVAL_SECONDS as UPDATE_INTERVAL_SECONDS,
)

DOMAIN = "givenergy_inverter_manager"
INTEGRATION_VERSION = "0.19.11"  # keep in sync with manifest.json
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
