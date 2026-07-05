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
INTEGRATION_VERSION = "0.1.0"  # keep in sync with manifest.json
NAME = "GivEnergy Inverter Manager"

# ── GivTCP inverter entities ────────────────────────────────────────────────
CONF_SOLAR_POWER         = "solar_power_entity"
CONF_BATTERY_SOC         = "battery_soc_entity"
CONF_BATTERY_POWER       = "battery_power_entity"
CONF_GRID_POWER          = "grid_power_entity"
CONF_HOUSE_LOAD          = "house_load_entity"
CONF_INVERTER_MAX_OUTPUT = "inverter_max_output_kw"
# GivTCP charge control entities — all optional
CONF_TARGET_SOC_ENTITY        = "target_soc_entity"           # number.*_target_soc
CONF_ENABLE_CHARGE_TARGET     = "enable_charge_target_entity" # switch.*_enable_charge_target
CONF_ENABLE_CHARGE_SCHEDULE   = "enable_charge_schedule_entity" # switch.*_enable_charge_schedule
CONF_CHARGE_START_TIME_ENTITY = "charge_start_time_entity"    # select.*_charge_start_time_slot_1
CONF_CHARGE_END_TIME_ENTITY   = "charge_end_time_entity"      # select.*_charge_end_time_slot_1
CONF_BATTERY_CAPACITY    = "battery_capacity_kwh"

# ── Tariff ───────────────────────────────────────────────────────────────────
# Base rate — the default rate when no timed period is active (e.g. standard daytime)
CONF_BASE_RATE       = "base_rate"
CONF_BASE_RATE_NAME  = "base_rate_name"
# Timed override periods stored as a list of dicts (start/end required):
# [{"name": "Night", "rate": 0.1644, "start": "23:00", "end": "08:00"}, ...]
CONF_RATE_PERIODS    = "rate_periods"
CONF_EXPORT_RATE     = "export_rate"
CONF_STANDING_CHARGE = "standing_charge_per_day"
CONF_PSO_LEVY        = "pso_levy_per_month"
CONF_VAT_RATE        = "vat_rate"
CONF_DISCOUNT_RATE   = "discount_rate"
CONF_BILL_START_DAY  = "bill_start_day"
CONF_CURRENCY        = "currency"   # symbol used in cost sensor units

# ── Solar forecast ───────────────────────────────────────────────────────────
CONF_FORECAST_ENTITY             = "forecast_entity"
CONF_FORECAST_PROVIDER           = "forecast_provider"
FORECAST_PROVIDER_FORECAST_SOLAR = "forecast_solar"
FORECAST_PROVIDER_SOLCAST        = "solcast"

# ── Immersion heater ─────────────────────────────────────────────────────────
CONF_IMMERSION_SWITCH      = "immersion_switch_entity"
CONF_IMMERSION_WATTAGE     = "immersion_wattage_w"
CONF_IMMERSION_TEMP_SENSOR = "immersion_temp_sensor_entity"
CONF_IMMERSION_TARGET_TEMP = "immersion_target_temp_c"
CONF_IMMERSION_MIN_TEMP    = "immersion_min_temp_c"

# ── EV charger ───────────────────────────────────────────────────────────────
# Battery protection threshold: pause EV charging when SoC drops below this
CONF_EV_BATTERY_PROTECT_SOC = "ev_battery_protect_soc_pct"

# ── Battery management ───────────────────────────────────────────────────────
CONF_BATTERY_MIN_SOC           = "battery_min_soc_pct"
CONF_OVERNIGHT_CHARGE_TARGET   = "overnight_charge_target_pct"
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

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_INVERTER_MAX_OUTPUT       = 5.0     # kW — GivEnergy GIV-HY-5.0
DEFAULT_BATTERY_CAPACITY          = 10.0    # kWh — conservative fallback if not configured
DEFAULT_IMMERSION_WATTAGE         = 3000    # W
DEFAULT_IMMERSION_TARGET_TEMP     = 55      # °C
DEFAULT_IMMERSION_MIN_TEMP        = 45      # °C
DEFAULT_BATTERY_MIN_SOC           = 10      # %
DEFAULT_OVERNIGHT_CHARGE_TARGET   = 80      # %
DEFAULT_SKIP_CHARGE_SOC_THRESHOLD = 75      # %
DEFAULT_VAT_RATE                  = 9.0     # % (Irish domestic electricity)
DEFAULT_DISCOUNT_RATE             = 5.5     # % (DD + online billing, Electric Ireland)
DEFAULT_STANDING_CHARGE           = 0.8259  # per day
DEFAULT_PSO_LEVY                  = 1.46    # per month
DEFAULT_EXPORT_RATE               = 0.195   # per kWh (Irish CEG rate)
DEFAULT_BILL_START_DAY            = 1       # day of month
DEFAULT_EV_BATTERY_PROTECT_SOC    = 20      # % — pause EV below this SoC

# Default rate periods: Electric Ireland Home Electric + Nightboost
# Nightboost (02:00–04:00) is listed last but takes priority over Night
# because get_current_rate() returns the cheapest active period.
DEFAULT_BASE_RATE      = 0.3334   # €/kWh — daytime / standard rate
DEFAULT_BASE_RATE_NAME = "Day"
# Timed override slots — cheapest active slot wins, then base rate applies
DEFAULT_RATE_PERIODS = [
    {"name": "Night",      "rate": 0.1644, "start": "23:00", "end": "08:00"},
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

# ── Operational thresholds ───────────────────────────────────────────────────
# Battery SoC must be above this before immersion divert activates
SURPLUS_DIVERT_SOC_THRESHOLD = 80    # %
# Minimum solar surplus (W) before turning on immersion
SURPLUS_DIVERT_MIN_POWER_W   = 500   # W
# Inverter output as % of max that signals clipping
CLIPPING_THRESHOLD_PERCENT   = 95    # %

# ── Coordinator ──────────────────────────────────────────────────────────────
UPDATE_INTERVAL_SECONDS = 30

# ── HA platforms exposed by this integration ─────────────────────────────────
PLATFORMS = ["sensor", "switch", "number"]

# ── Charge algorithm parameters ───────────────────────────────────────────────
# These govern the overnight charge decision logic in rules.py.
# Named here so behaviour is documented and auditable — not buried as magic numbers.
CHARGE_PEAK_SOLAR_HOURS      = 4.0   # peak-output hours assumed when no forecast available
CHARGE_MORNING_LOAD_FRACTION = 0.25  # fraction of daily load consumed before solar starts
CHARGE_SOLAR_USABLE_FRACTION = 0.6   # fraction of forecast kWh we can realistically charge from
CHARGE_EV_BUFFER_KWH         = 5.0   # extra kWh reserved overnight when EV is plugged in
CHARGE_SKIP_HEADROOM         = 0.8   # forecast/fill headroom needed to justify skipping charge
CHARGE_STRONG_FRACTION       = 0.8   # forecast >= battery_capacity * this → "strong" tier
CHARGE_MODERATE_FRACTION     = 0.5   # forecast >= battery_capacity * this → "moderate" tier
CHARGE_STRONG_BASE_SOC       = 50    # minimum target SoC for a strong-forecast night
CHARGE_MODERATE_BASE_SOC     = 70    # minimum target SoC for a moderate-forecast night
CHARGE_POOR_TARGET_SOC       = 90    # target SoC for a poor-forecast night
CHARGE_STRONG_BUFFER         = 10    # SoC points added above gap for strong forecast
CHARGE_MODERATE_BUFFER       = 20    # SoC points added above gap for moderate forecast
CHARGE_EV_SOC_BONUS          = 10    # extra SoC percentage added when EV is plugged in

# ── Solar / generation parameters ─────────────────────────────────────────────
SOLAR_SUNRISE_HOUR           = 8     # hour of day when solar generation typically starts

# ── Battery health parameters ─────────────────────────────────────────────────
BATTERY_RATED_CYCLES         = 6000  # typical LFP rated cycle life (manufacturer spec)

# ── EV diversion parameters ───────────────────────────────────────────────────
EV_SURPLUS_DIVERT_W          = 500   # minimum surplus (W) to switch Zappi to Eco+

# ── Configurable thresholds — exposed in config flow ─────────────────────────
# (SURPLUS_DIVERT_SOC_THRESHOLD and SURPLUS_DIVERT_MIN_POWER_W already defined above,
#  but not yet exposed to the user. Config keys added here for wiring them in.)
CONF_SURPLUS_DIVERT_SOC   = "surplus_divert_soc_pct"
CONF_SURPLUS_DIVERT_MIN_W = "surplus_divert_min_power_w"
