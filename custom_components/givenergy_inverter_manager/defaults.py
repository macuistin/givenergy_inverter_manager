"""defaults.py — default values for the options (the DEFAULT_ names).

No imports, so no cycle. const.py re-exports every name.
"""

# ── Solar forecast ────────────────────────────────────────────────────────────
DEFAULT_FORECAST_CONSERVATISM = 0.35  # dimensionless 0.0–1.0

# ── Supported currencies ──────────────────────────────────────────────────────
DEFAULT_CURRENCY = "EUR"

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_INVERTER_MAX_OUTPUT = 5.0  # kW — GivEnergy GIV-HY-5.0
DEFAULT_BATTERY_CAPACITY = 10.0  # kWh — conservative fallback if not configured
DEFAULT_IMMERSION_WATTAGE = 3000  # W
# The longest a scheduled immersion run lasts (core/scheduled_run.py). 0 turns the limit off.
DEFAULT_IMMERSION_MAX_RUN_MINUTES = 60  # minutes
DEFAULT_IMMERSION_TARGET_TEMP = 55  # °C — turn off when water reaches this
DEFAULT_IMMERSION_MIN_TEMP = 50  # °C — force on below this (legionella protection)
DEFAULT_IMMERSION_HYSTERESIS = 5  # °C — only restart after cooling this far below target
DEFAULT_IMMERSION_RUN_LIMIT_WARNING = True

# ── Alternative water heating advice (core/alt_heat_advice.py) ────────────────
DEFAULT_ALT_HEAT_LABEL = "Oil"
DEFAULT_BATTERY_MIN_SOC = 10  # %
DEFAULT_OVERNIGHT_CHARGE_TARGET = 80  # %
DEFAULT_SKIP_CHARGE_SOC_THRESHOLD = 75  # %
DEFAULT_VAT_RATE = 9.0  # % (Irish domestic electricity)
DEFAULT_DISCOUNT_RATE = 5.5  # % (DD + online billing, Electric Ireland)
DEFAULT_STANDING_CHARGE = 0.8259  # per day
DEFAULT_PSO_LEVY = 1.46  # per month
DEFAULT_EXPORT_RATE = 0.195  # per kWh (Irish CEG rate)
DEFAULT_BILL_START_DAY = 1  # day of month
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

# ── Dry run mode ──────────────────────────────────────────────────────────────
DEFAULT_DRY_RUN = False
DEFAULT_VERBOSE_LOGGING = False
DEFAULT_CHARGE_REPLAN = False

# ── Battery degradation cost ──────────────────────────────────────────────────
DEFAULT_BATTERY_COST = 0.0  # € — 0 disables the degradation cost check

# ── Battery throughput budget ─────────────────────────────────────────────────
DEFAULT_BATTERY_THROUGHPUT_BUDGET = 0.0

# ── Tuning controls ───────────────────────────────────────────────────────────
DEFAULT_CHEAP_RATE_FLOOR_SOC = 40  # % — 0 disables the floor
