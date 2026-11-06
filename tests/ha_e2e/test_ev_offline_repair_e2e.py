"""A charger that stops answering shows as offline, raises a repair and clears it on return."""

from __future__ import annotations

from conftest import ZAPPI_STATES
from homeassistant.helpers import issue_registry as ir

from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.core.ev_offline import EV_OFFLINE_REPAIR_CYCLES

ISSUE = "ev_charger_offline"
STATUS = "sensor.myenergi_zappi_plug_status"


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE)


async def test_an_unavailable_charger_raises_one_error_repair_and_clears(
    hass, loaded_entry_with_charger
):
    coordinator = loaded_entry_with_charger.runtime_data
    hass.states.async_set(STATUS, "unavailable")

    for _ in range(EV_OFFLINE_REPAIR_CYCLES - 1):
        await coordinator.async_refresh()
    assert _issue(hass) is None

    await coordinator.async_refresh()
    issue = _issue(hass)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity == ir.IssueSeverity.ERROR

    hass.states.async_set(STATUS, ZAPPI_STATES[STATUS])
    await coordinator.async_refresh()
    assert _issue(hass) is None


async def test_the_charger_state_lists_its_source_entities_with_their_report_times(
    hass, loaded_entry_with_charger, sensor_entries
):
    await loaded_entry_with_charger.runtime_data.async_refresh()
    entity = next(
        e for e in sensor_entries(hass, loaded_entry_with_charger) if e.unique_id.endswith("_ev_charger_state")
    )
    sources = {row["role"]: row for row in hass.states.get(entity.entity_id).attributes["sources"]}
    assert sources["status"]["entity_id"] == STATUS
    assert sources["status"]["last_reported"] is not None
