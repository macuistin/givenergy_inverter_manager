"""When a hot water temperature sensor that reads nothing raises a repair, and when it clears."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.core.temperature_feed import (
    SILENT_CYCLES,
    next_counts,
    silent_sensors,
)

UPPER = "sensor.upper"
LOWER = "sensor.lower"


def _run(cycles: list[dict[str, bool]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for readable in cycles:
        counts = next_counts(counts, readable)
    return counts


def test_a_sensor_must_stay_silent_for_the_whole_run_before_it_counts():
    short = _run([{UPPER: False}] * (SILENT_CYCLES - 1))
    full = _run([{UPPER: False}] * SILENT_CYCLES)

    assert silent_sensors(short) == ()
    assert silent_sensors(full) == (UPPER,)


def test_a_reading_in_between_starts_the_count_again():
    counts = _run([{UPPER: False}] * (SILENT_CYCLES - 1) + [{UPPER: True}] + [{UPPER: False}] * 3)

    assert counts == {UPPER: 3}
    assert silent_sensors(counts) == ()


def test_each_sensor_is_counted_on_its_own_and_named_in_order():
    counts = _run([{UPPER: False, LOWER: True}] * SILENT_CYCLES)
    assert silent_sensors(counts) == (UPPER,)

    counts = _run([{UPPER: False, LOWER: False}] * SILENT_CYCLES)
    assert silent_sensors(counts) == (UPPER, LOWER)


def test_a_sensor_taken_out_of_the_options_is_forgotten():
    counts = _run([{UPPER: False, LOWER: False}] * SILENT_CYCLES + [{UPPER: False}])

    assert LOWER not in counts
    assert silent_sensors(counts) == (UPPER,)


def test_no_configured_sensor_counts_nothing():
    assert _run([{}] * SILENT_CYCLES) == {}
    assert silent_sensors({}) == ()
