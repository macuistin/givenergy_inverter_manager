"""defaults.py: the EV thresholds. const.py re-imports them so there is one source."""

# ── EV diversion parameters ───────────────────────────────────────────────────
# Minimum power for an OCPP EV charger to start — 6A × 230V single-phase.
# If the available surplus is below this, the charger will refuse to start.
# This is also the surplus at which the EV Solar Surplus signal reads Available
# and the Zappi is switched to Eco+.
# Based on IEC 61851 minimum of 6A (1,380W at 230V). Single-phase assumption.
EV_CHARGER_MIN_POWER_W = 1380
# How long a car must draw from the grid in the base-rate band before the repair
# "EV is charging at the base rate" is raised. Five minutes (ten cycles) skips a charger that
# starts, pauses and restarts, and a short grid spike while solar diverts.
EV_BASE_RATE_ALERT_DELAY_S = 300
EV_RECENT_SESSIONS_MAX = 10  # finished EV charging sessions kept for the recent charges table
