"""defaults.py: the numbers the half-hourly store needs. Imports nothing."""

# Length of one slot. Every slot is exactly this many real seconds, so a clock change shows up as
# a day with fewer or more slots, never as a slot of another length.
SLOT_SECONDS = 1800

# How many days of slots are kept. A year plus a spare bill period, so any bill can be re-priced.
SLOT_RETENTION_DAYS = 400

# A reading interval longer than this is a gap (Home Assistant down, or a stalled update). Its
# energy is not spread over the slots it spans, because the shape inside the gap is unknown.
SLOT_MAX_INTERVAL_SECONDS = 1800

# How deeply a bill tree may nest. A real bill is about four levels, so this refuses a document
# built to exhaust the stack without limiting any honest tariff.
MAX_TARIFF_TREE_DEPTH = 8
