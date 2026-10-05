"""The five-step charge target write-back against real service calls."""

from __future__ import annotations

import pytest
from conftest import ENABLE_TARGET, TARGET_SOC
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.givenergy_inverter_manager.core.tariff import build_tariff

SERVICES = (
    ("number", "set_value"),
    ("switch", "turn_on"),
    ("switch", "turn_off"),
    ("select", "select_option"),
)


def _mock_writes(hass, failing: tuple[str, ...] = ()) -> dict[str, list]:
    """Register capturing services after setup and make the named ones raise.

    Setting up the platforms registers Home Assistant's own number and switch
    services over the ones from the service_calls fixture, so they are replaced
    here once the entry is loaded.
    """
    error = HomeAssistantError("write rejected")
    return {
        f"{domain}.{service}": async_mock_service(
            hass,
            domain,
            service,
            raise_exception=error if f"{domain}.{service}" in failing else None,
        )
        for domain, service in SERVICES
    }


async def _apply(entry, target_soc: int) -> None:
    coordinator = entry.runtime_data
    coordinator._last_write_time.clear()
    cfg = coordinator._effective_cfg()
    cheap = min(build_tariff(cfg).rate_periods, key=lambda p: p.rate)
    await coordinator._async_apply_charge_target(cfg, target_soc, cheap)


def _entity_ids(calls) -> list[str]:
    return [c.data["entity_id"] for c in calls]


async def test_failed_target_write_does_not_enable_the_charge_target(hass, loaded_entry):
    """number.set_value raising must stop the sequence before step 5."""
    calls = _mock_writes(hass, failing=("number.set_value",))

    await _apply(loaded_entry, 60)

    assert len(calls["number.set_value"]) == 1
    assert ENABLE_TARGET not in _entity_ids(calls["switch.turn_on"])


async def test_sequence_enables_the_charge_target_when_every_write_works(hass, loaded_entry):
    calls = _mock_writes(hass)

    await _apply(loaded_entry, 60)

    assert calls["number.set_value"][0].data["value"] == 60
    assert ENABLE_TARGET in _entity_ids(calls["switch.turn_on"])


@pytest.mark.parametrize(("requested", "written"), [(2, 4), (150, 100)])
async def test_target_is_clamped_to_the_range_givtcp_accepts(
    hass, loaded_entry, requested, written
):
    calls = _mock_writes(hass)

    await _apply(loaded_entry, requested)

    targets = [c for c in calls["number.set_value"] if c.data["entity_id"] == TARGET_SOC]
    assert targets
    assert {c.data["value"] for c in targets} == {written}


async def test_error_in_an_earlier_step_does_not_abort_the_sequence(hass, loaded_entry):
    calls = _mock_writes(hass, failing=("select.select_option",))

    await _apply(loaded_entry, 60)

    assert calls["number.set_value"][0].data["value"] == 60
    assert ENABLE_TARGET in _entity_ids(calls["switch.turn_on"])
