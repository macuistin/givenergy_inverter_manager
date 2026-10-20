"""defaults.py: the limits the guards judge by. const.py re-imports them so there is one source."""

# A daily energy counter that rises by more than the inverter's maximum power times the time
# between two readings, times this margin, plus the floor, is not energy. The margin covers a
# house that draws more than the inverter. A rise of this many times the old value (a counter
# changing units, as GivTCP 3.6 did for Gateway totals) is logged as a probable unit change.
COUNTER_RISE_MARGIN = 4.0
COUNTER_RISE_FLOOR_KWH = 0.5
COUNTER_UNIT_CHANGE_RATIO = 500
COUNTER_UNIT_CHANGE_MIN_KWH = 1.0  # below this the old value is too small to compare against
