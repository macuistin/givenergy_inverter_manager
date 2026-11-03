"""defaults.py: the limits the solar day is judged by. const.py re-imports them."""

SOLAR_NOISE_FLOOR_W = 10.0  # W: readings below this are treated as zero
# The solar day starts once the reading has stayed at or above SOLAR_NOISE_FLOOR_W for this long,
# and ends once it has stayed below it for as long. At dawn and dusk the reading wanders across the
# floor every few cycles, and each crossing flipped the night window between 8 hours and the whole
# evening. Night survival and the charge skip check read the settled state.
SOLAR_DAY_DEBOUNCE_MINUTES = 5
# A held reading older than this, or a clock that went backwards, is a restart or a gap, so the
# day is judged afresh instead of debounced.
SOLAR_STALE_AFTER_S = 3600.0
