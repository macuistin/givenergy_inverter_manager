"""The old module paths re-export lib/heating, and cheapest_period exists in one place."""

import pytest

from custom_components.givenergy_inverter_manager import lib
from custom_components.givenergy_inverter_manager.core import (
    alt_heat_start,
    charge_window,
    immersion_rate,
    immersion_ready,
    immersion_window,
    planned_heating,
)

_OLD_PATHS = [immersion_rate, immersion_ready, immersion_window, planned_heating]


@pytest.mark.parametrize("module", _OLD_PATHS, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_every_public_name_is_the_lib_object(module):
    assert module.__all__
    assert all(getattr(module, n) is getattr(lib.heating, n) for n in module.__all__)


def test_the_water_reading_and_the_cheapest_period_each_have_one_definition():
    assert alt_heat_start.WaterReading is lib.heating.WaterReading
    assert charge_window.cheapest_period is lib.tariff.cheapest_period
