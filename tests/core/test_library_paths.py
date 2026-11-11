"""The old `core` paths still return the objects of the copied tariff and time libraries."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager import lib
from custom_components.givenergy_inverter_manager.core import stored_energy, tariff
from custom_components.givenergy_inverter_manager.core import timeutil as old_timeutil
from custom_components.givenergy_inverter_manager.lib import timeutil


def test_the_old_tariff_paths_return_the_library_objects():
    for name in ("RatePeriod", "TariffConfig", "EnergyAccumulator", "CounterMemory", "BillBreakdown"):
        assert getattr(tariff, name) is getattr(lib.tariff, name)
    assert stored_energy.stored_energy_change is lib.tariff.stored_energy_change


def test_the_old_core_path_re_exports_the_same_time_functions():
    for name in ("elapsed_seconds", "local_time_on", "real_time_after", "shift_real"):
        assert getattr(old_timeutil, name) is getattr(timeutil, name)
