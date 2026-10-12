"""Constants that belong to the GivTCP adapter: write safety and the charge target limits."""

# GivEnergy inverters have ~1M total register write capacity. Limiting unnecessary
# writes protects hardware lifetime. Predbat documents this as a known issue.
GIVTCP_MAX_WRITE_RETRIES = 3          # attempts per write before giving up
GIVTCP_WRITE_RETRY_SLEEP_S = 2        # seconds between retry attempts
GIVTCP_WRITE_LIFETIME_WARN = 500_000  # log a warning at this write count (~50% of rated)
GIVTCP_MIN_WRITE_INTERVAL_S = 300     # minimum seconds before the same value is rewritten
GIVTCP_MIN_CHARGE_TARGET_PCT = 4      # lowest charge target GivTCP accepts
GIVTCP_MAX_CHARGE_TARGET_PCT = 100    # highest charge target GivTCP accepts
