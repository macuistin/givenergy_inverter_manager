"""defaults.py: the heating thresholds. const.py re-imports them so there is one source.

CHARGE_WINDOW_MARGIN is also the stretch the charge window sizing uses (core/charge_window.py),
which reads it through const.
"""

# Charge window sizing (core/charge_window.py). The charge time the plan needs is stretched by
# this fraction, because the battery slows near full and the real rate sits below the setting.
CHARGE_WINDOW_MARGIN = 0.15
IMMERSION_SWITCH_COOLDOWN_MINUTES = 10  # min between auto on/off writes to the real switch
# Rate assumed before a run has been measured: a large cylinder, which heats slowly, so the
# first plans start early rather than late.
IMMERSION_ASSUMED_TANK_LITRES = 300
# A run counts as a sample only when it was long and warmed the water enough to measure. Runs of
# a top-up size count, because the days they fall on are averaged.
IMMERSION_RATE_RUN_MIN_MINUTES = 10
IMMERSION_RATE_RUN_MIN_RISE_C = 1.0
# Installs from before the daily rates have the median of their last few runs until the first
# dated run is recorded.
IMMERSION_RATE_RUNS_KEPT = 5
# The rate used is the average of the daily rates of the last 7 days. A day's rate is the average
# of its runs. With one day of data that day is used as it is, so the rate follows the heater
# as it ages or the cylinder changes, and one odd day cannot dominate.
IMMERSION_RATE_DAYS_KEPT = 7
# How long a running element stays on while a required sensor is unavailable.
# Same value as the write interval, but a separate setting.
SENSOR_OUTAGE_HOLD_LIMIT_S = 300
# Ready-by heating waits for the sun when the solar still to come today covers the heater's energy
# this many times over (lib/heating/solar.py). House load and the battery take their share first.
# The 3 is an estimate, not a measured figure: a guess at the share they use.
IMMERSION_SOLAR_COVER_FACTOR = 3.0
