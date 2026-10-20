"""The guard that keeps the integration from exporting, and that it lets normal work through."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.lib.givtcp import (
    BatteryMode,
    GivTCPPorts,
    SelfUseMode,
    make_backend,
)
from tests.fakes.export_guard import ExportGuard, IntegrationExported


def _guarded() -> ExportGuard:
    async def call(domain, service, data):
        return None

    return ExportGuard(make_backend({}, GivTCPPorts(lambda entity: None, call, lambda count: None)))


@pytest.mark.parametrize(
    "name",
    ["schedules", "force", "controls", "apply_discharge_plan", "start", "stop_discharge", "apply_slot"],
)
def test_the_export_surface_is_out_of_reach(name):
    with pytest.raises(IntegrationExported):
        getattr(_guarded(), name)


async def test_timed_export_is_refused_even_through_the_controls_interface():
    with pytest.raises(IntegrationExported):
        await _guarded().apply_battery_mode({}, BatteryMode.TIMED_EXPORT)


async def test_a_mode_that_never_exports_is_passed_on():
    assert not await _guarded().apply_battery_mode({}, SelfUseMode.ECO)  # nothing to write to


def test_everything_the_integration_uses_passes_through():
    guarded = _guarded()

    assert guarded.writer is not None
    assert guarded.write_count == 0
    assert callable(guarded.apply_charge_plan)
    assert callable(guarded.apply_battery_pause)
