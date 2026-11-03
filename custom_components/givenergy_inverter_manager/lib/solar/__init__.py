"""Solar forecast shape, the settled solar day, and rebuilding forecast accuracy from history."""

from .day import HeldSolarDay, SolarReading, settled_solar_w
from .defaults import SOLAR_DAY_DEBOUNCE_MINUTES, SOLAR_NOISE_FLOOR_W, SOLAR_STALE_AFTER_S
from .seeding import Reading, RecordedReadings, seed_forecast_records
from .shape import (
    DEFAULT_SOLAR_END_MINUTE,
    DEFAULT_SOLAR_SHAPE,
    SLOTS,
    producing_hours,
    solar_end_minute,
    solar_shape_from_periods,
    valid_shape,
)

__all__ = [
    "DEFAULT_SOLAR_END_MINUTE",
    "DEFAULT_SOLAR_SHAPE",
    "SLOTS",
    "SOLAR_DAY_DEBOUNCE_MINUTES",
    "SOLAR_NOISE_FLOOR_W",
    "SOLAR_STALE_AFTER_S",
    "HeldSolarDay",
    "Reading",
    "RecordedReadings",
    "SolarReading",
    "producing_hours",
    "seed_forecast_records",
    "settled_solar_w",
    "solar_end_minute",
    "solar_shape_from_periods",
    "valid_shape",
]
