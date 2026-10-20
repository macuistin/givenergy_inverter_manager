"""defaults.py: the limits the GivTCP adapter works to. const.py re-imports the shared ones."""

# GivEnergy inverters have ~1M total register write capacity. Limiting unnecessary
# writes protects hardware lifetime. Predbat documents this as a known issue.
GIVTCP_MAX_WRITE_RETRIES = 2          # times one write may be sent before giving up
GIVTCP_WRITE_RETRY_SLEEP_S = 2        # seconds before the first read-back, doubling after
GIVTCP_WRITE_LIFETIME_WARN = 500_000  # log a warning at this write count (~50% of rated)
GIVTCP_MIN_WRITE_INTERVAL_S = 300     # minimum seconds before the same value is rewritten
GIVTCP_UNCONFIRMED_COOLDOWN_S = 60    # seconds before a value that never read back is sent again
GIVTCP_MIN_CHARGE_TARGET_PCT = 4      # lowest charge target GivTCP accepts
GIVTCP_MAX_CHARGE_TARGET_PCT = 100    # highest charge target GivTCP accepts

# The rates GivTCP holds until its user changes them: day, night and export, per kWh. A rate
# equal to one of these has most likely never been set, so it is not offered as a starting value.
GIVTCP_SHIPPED_RATES = {"day": 0.395, "night": 0.155, "export": 0.04}

# How long every GivTCP power and SoC entity may go without a report before the feed counts as
# frozen. GivTCP publishes about every 20 to 30 seconds and a cycle is 30 seconds, so ten minutes
# is twenty missed publishes: an add-on restart passes, an overnight crash trips. The
# five-minute write cooldown (GIVTCP_MIN_WRITE_INTERVAL_S) is not a feed age.
GIVTCP_FROZEN_AFTER_S = 600
