"""tuning.py — numeric thresholds, limits and timings.

No imports, so no cycle. const.py re-exports every name.
"""

# ── Tariff ────────────────────────────────────────────────────────────────────
# Days without a tariff review before the repair appears. Suppliers change prices about once a
# year, and no existing constant measures time since a user action.
TARIFF_REVIEW_STALE_DAYS = 365

# ── Carbon intensity ──────────────────────────────────────────────────────────
# Thresholds for status classification (g CO2/kWh).
# Below LOW → "Low" (high renewable fraction, good time to import).
# Above HIGH → "High" (mostly fossil generation, prefer self-consumption).
CARBON_LOW_THRESHOLD = 200   # g CO2/kWh
CARBON_HIGH_THRESHOLD = 400  # g CO2/kWh


# ── Alternative water heating advice (core/alt_heat_advice.py) ────────────────
ALT_HEAT_LABEL_MAX_LENGTH = 20
# Fixed assumptions for the litre unit, not options. A typical boiler in service sits between an
# older non-condensing boiler (about 75 to 80%) and a new condensing one (about 90% or more). 85%
# leans low on purpose, so oil is not suggested on an efficiency the boiler does not reach in
# summer, when it heats only the cylinder.
OIL_BOILER_EFFICIENCY_PCT = 85  # %
# The commonly quoted energy content of kerosene heating oil.
OIL_KWH_PER_LITRE = 10.35  # kWh per litre of fuel
ALT_HEAT_ADVICE_HORIZON_HOURS = 24  # how far ahead the cheapest hours are looked for
# The two trigger sensors fire this far before the immersion would act: the ready-by trigger when
# the water is this far below its target, the low water trigger when it is this far above the
# lower boundary (the point where the immersion would top it up).
ALT_HEAT_TRIGGER_MARGIN_C = 1.0
# A suggested alternative heating schedule (core/alt_heat_schedule.py) is learned from a rolling
# record of the immersion's grid heating. Fixed assumptions, not options.
# Complete days kept, plus the day in progress. Two weeks hold every weekday twice, so a weekly
# habit shows up twice, and an old habit drops out within a fortnight of it ending.
ALT_HEAT_SCHEDULE_RECORD_DAYS = 14
# A single week is the shortest record that has seen each weekday once. Before that a pattern
# could be one busy weekend.
ALT_HEAT_SCHEDULE_MIN_DAYS = 7
# An hour counts as a habit when it recurs on at least one day in this many. A third is two or
# three days a week: it catches weekday routines and the daily top-up, and leaves out a guest's
# shower or one cold snap.
ALT_HEAT_SCHEDULE_REPEAT_ONE_IN = 3
# The least grid energy in one hour that counts as the immersion heating (about 5 minutes of a
# 3 kW element). Less is solar surplus that did not quite cover the heater.
ALT_HEAT_SCHEDULE_MIN_HOUR_KWH = 0.25
# The least saving a week that is worth a window, in the configured currency. About 13 a year:
# below it, setting up an automation costs more effort than it returns.
ALT_HEAT_SCHEDULE_MIN_SAVING_PER_WEEK = 0.25
# Two or three windows is a morning, an afternoon and an evening. More is not a schedule anyone
# sets up.
ALT_HEAT_SCHEDULE_MAX_WINDOWS = 3

# ── Inverter temperature thresholds ───────────────────────────────────────────
INVERTER_TEMP_WARM = 60      # °C — efficiency begins to drop
INVERTER_TEMP_DERATING = 65  # °C — significant throttling begins
INVERTER_TEMP_CRITICAL = 75  # °C — protection mode likely

# ── Operational thresholds ────────────────────────────────────────────────────
# Battery SoC must be above this before immersion divert activates
SURPLUS_DIVERT_SOC_THRESHOLD = 80  # %
# Minimum solar surplus (W) before turning on immersion
SURPLUS_DIVERT_MIN_POWER_W = 500  # W
# Inverter output as % of max that signals clipping
CLIPPING_THRESHOLD_PERCENT = 95  # %
# Battery SoC (%) at or above which the battery counts as full
BATTERY_FULL_SOC_PCT = 99.0  # %

# ── Appliance timing suggestion ───────────────────────────────────────────────
APPLIANCE_MIN_BATTERY_SOC = 80  # % — battery charge needed to run an appliance from the battery
APPLIANCE_RATE_THRESHOLD = 1.5  # × export rate — above this the grid rate is too high to suggest

# ── Coordinator ───────────────────────────────────────────────────────────────
UPDATE_INTERVAL_SECONDS = 30
# Power inside this band either side of zero counts as no flow. The sensors read it, and so does
# the charge hold, which counts a battery drawing more than this from the grid as charging.
POWER_DIRECTION_BAND_W = 50

# ── Charge algorithm parameters ───────────────────────────────────────────────
# In a winter month the charge goes to 100% regardless of forecast, because solar is negligible.
# In a shoulder month the min_soc floor is raised, because heating load is variable and the
# forecast is less reliable than in peak summer.
# Shoulder month min SoC floor (% of battery) — more conservative than summer floor.
CHARGE_SHOULDER_MIN_SOC = 70  # % — applied instead of battery_min_soc in shoulder months
# A planned overnight target is never below this, so a very sunny forecast still leaves the battery
# some charge in case the sun does not arrive. PALM holds the same floor in summer. The shoulder
# floor above is already higher, so this only matters in the other months.
CHARGE_SUMMER_MIN_TARGET_SOC = 25  # %
# Winter months: the charge is skipped once the battery is at or above this SoC.
CHARGE_WINTER_SKIP_SOC_PCT = 95  # %
# The overnight target is never planned closer than this to the minimum SoC.
CHARGE_MIN_TARGET_HEADROOM_PCT = 5  # SoC points above min SoC
# The published recommendation holds until the fresh target moves this far from it. Overnight
# readings jitter by ten points or more (early-morning load extrapolation), so a step this size
# keeps the sensor steady while a change worth acting on still shows. The write uses the fresh
# target, never the held one.
CHARGE_TARGET_HOLD_STEP_PCT = 5  # SoC points
# A published value then stands for at least this long before the next step of that size is
# published, so a slow drift in the load estimate moves the sensor once an hour, not every few
# minutes. A change of CHARGE_TARGET_HOLD_LARGE_STEP_PCT or more is published at once.
CHARGE_TARGET_HOLD_MIN_MINUTES = 60
CHARGE_TARGET_HOLD_LARGE_STEP_PCT = 15  # SoC points
CHARGE_PEAK_SOLAR_HOURS = 4.0  # peak-output hours assumed when no forecast available
CHARGE_SOLAR_USABLE_FRACTION = 0.6  # fraction of forecast kWh we can realistically charge from
CHARGE_SKIP_HEADROOM = 0.8  # forecast/fill headroom needed to justify skipping charge
CHARGE_STRONG_BUFFER = 10  # SoC points added above gap for strong forecast
CHARGE_EV_SOC_BONUS = 10  # extra SoC percentage added when EV is plugged in
CHARGE_LOAD_PROFILE_MIN_COVERAGE = 0.9  # fraction of the day a load record must cover
CHARGE_LOAD_PROFILE_MIN_DAYS = 2  # complete days needed before the per-slot profile is used
CHARGE_LOAD_PROFILE_SAME_WEEKDAY_MIN_DAYS = 3  # same-weekday days needed to prefer them
CHARGE_FORECAST_CORRECTION_MIN = 0.4  # lowest factor applied to the P50 forecast
CHARGE_FORECAST_CORRECTION_MAX = 1.2  # highest factor applied to the P50 forecast
CHARGE_FORECAST_CORRECTION_MIN_DAYS = 5  # usable days needed before the factor is applied
CHARGE_FORECAST_CORRECTION_MIN_KWH = 0.5  # days with forecast or actual below this are ignored
CHARGE_WINDOW_ROUND_MINUTES = 5  # the window end is rounded up to a multiple of this
# The published window end holds like the target does: it moves once the planned end is
# CHARGE_WINDOW_HOLD_STEP_MINUTES away and the held end has stood for the target's hold time
# (CHARGE_TARGET_HOLD_MIN_MINUTES), or at once when it is CHARGE_WINDOW_HOLD_LARGE_STEP_MINUTES
# away. The window written to the inverter is always the planned one.
CHARGE_WINDOW_HOLD_STEP_MINUTES = 15
CHARGE_WINDOW_HOLD_LARGE_STEP_MINUTES = 45

# ── Solar / generation parameters ─────────────────────────────────────────────
SOLAR_SUNRISE_HOUR = 8  # hour of day when solar generation typically starts
SOLAR_NOISE_FLOOR_W = 10.0  # W — sensor readings below this are treated as zero
# The solar day starts once the reading has stayed at or above SOLAR_NOISE_FLOOR_W for this long,
# and ends once it has stayed below it for as long. At dawn and dusk the reading wanders across the
# floor every few cycles, and each crossing flipped the night window between 8 hours and the whole
# evening. Night survival and the charge skip check read the settled state.
SOLAR_DAY_DEBOUNCE_MINUTES = 5

# ── Battery health parameters ─────────────────────────────────────────────────
BATTERY_RATED_CYCLES = 6000  # typical LFP rated cycle life (manufacturer spec)
NIGHT_SURVIVAL_WARNING_MARGIN_PCT = 5.0  # warn within this many SoC points of min SoC
BATTERY_LIFE_ESTIMATE_MIN_DAYS = 7  # days of cycle data needed before estimating years left
BATTERY_MAX_SOC_STEP_PCT = 10.0  # SoC change between two updates above this is a sensor glitch
BATTERY_EFFICIENCY_MIN_KWH = 2.0  # kWh in and out today before round-trip efficiency is reported

# ── Battery throughput budget ─────────────────────────────────────────────────
THROUGHPUT_BUDGET_HIGH_PCT = 80.0  # at or above this, status is "High"


# ── Register write log ────────────────────────────────────────────────────────
# The write safety limits (retries, cooldown, lifetime warning) live in
# inverter/givtcp/constants.py with the GivTCP adapter.
# Something other than this integration is suspected of setting the charge target when the write
# log holds at least this many outside changes with no Home Assistant user inside the window.
# A missed nightly charge write is tried again this many minutes after the trigger, and not at all
# when less than the stop margin of the window would remain.
CHARGE_WRITE_RETRY_OFFSETS_MIN = (2, 5, 10, 20)
CHARGE_WRITE_RETRY_STOP_BEFORE_END_MIN = 15
# Re-planning inside the cheap window. All of it stops when less than REPLAN_MIN_REMAINING_MIN of
# the window is left. The late check runs once, at the later of 30 minutes after the first write
# and 60 minutes before the window ends. A new target is written only when it moves the old one by
# REPLAN_MIN_CHANGE_PTS or more, and at most REPLAN_MAX_WRITES times a night.
REPLAN_MIN_REMAINING_MIN = 15
REPLAN_LATE_CHECK_AFTER_MIN = 30
REPLAN_LATE_CHECK_BEFORE_END_MIN = 60
REPLAN_FORECAST_CHANGE_PCT = 15
REPLAN_FORECAST_CHANGE_MIN_KWH = 1.0
REPLAN_MIN_CHANGE_PTS = 5
REPLAN_MAX_WRITES = 3
CONFLICT_MIN_CHANGES = 2
CONFLICT_WINDOW_DAYS = 3
# A daily energy counter that rises by more than the inverter's maximum power times the time
# between two readings, times this margin, plus the floor, is not energy. The margin covers a
# house that draws more than the inverter. A rise of this many times the old value (a counter
# changing units, as GivTCP 3.6 did for Gateway totals) is logged as a probable unit change.
COUNTER_RISE_MARGIN = 4.0
COUNTER_RISE_FLOOR_KWH = 0.5
COUNTER_UNIT_CHANGE_RATIO = 500
COUNTER_UNIT_CHANGE_MIN_KWH = 1.0  # below this the old value is too small to compare against
REGISTER_WRITE_LOG_MAX_ENTRIES = 20   # recent writes and outside changes kept in the write log
# How long every GivTCP power and SoC entity may go without a report before the feed counts as
# frozen. GivTCP publishes about every 20 to 30 seconds and a cycle is 30 seconds, so ten minutes
# is twenty missed publishes: an add-on restart passes, an overnight crash trips. The
# five-minute write cooldown (inverter/givtcp/constants.py) and the element hold above are not
# feed ages.
GIVTCP_FROZEN_AFTER_S = 600

# ── Sensor state text ─────────────────────────────────────────────────────────
# Home Assistant stores a state of up to 255 characters (homeassistant.const
# MAX_LENGTH_STATE_STATE). A longer one is logged as an error and reads unknown. core/ cannot
# import Home Assistant, so the limit is repeated here.
STATE_MAX_LENGTH = 255
