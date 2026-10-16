"""Active Repairs counts this integration's open repairs in the real issue registry, and only those."""

from __future__ import annotations

import pytest
from conftest import MIDDAY
from homeassistant.helpers import issue_registry as ir

from custom_components.givenergy_inverter_manager.const import DOMAIN

ENTITY_ID = "sensor.givenergy_inverter_manager_active_repairs"
PAUSE_TITLE = "The battery pause stops tonight's charge"


@pytest.fixture
def scenario():
    return MIDDAY


def _create(hass, domain: str, issue_id: str, translation_key: str, **kwargs) -> None:
    ir.async_create_issue(
        hass,
        domain,
        issue_id,
        is_fixable=kwargs.pop("is_fixable", False),
        severity=kwargs.pop("severity", ir.IssueSeverity.WARNING),
        translation_key=translation_key,
        **kwargs,
    )


def _ours(hass) -> set[str]:
    """The open, not ignored issues of this integration, as the registry holds them."""
    return {
        issue.issue_id
        for issue in ir.async_get(hass).issues.values()
        if issue.domain == DOMAIN and issue.active and issue.dismissed_version is None
    }


def _sensor(hass):
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    return state


def _issue(hass, issue_id: str) -> dict | None:
    return next((i for i in _sensor(hass).attributes["issues"] if i["issue_id"] == issue_id), None)


async def test_the_sensor_counts_what_the_registry_holds_after_setup(hass, loaded_entry):
    state = _sensor(hass)
    assert int(state.state) == len(_ours(hass))
    assert {i["issue_id"] for i in state.attributes["issues"]} == _ours(hass)
    assert "state_class" not in state.attributes
    assert "unit_of_measurement" not in state.attributes
    assert "device_class" not in state.attributes


async def test_an_issue_of_this_integration_is_counted_and_titled_at_once(hass, loaded_entry):
    before = int(_sensor(hass).state)
    _create(hass, DOMAIN, "e2e_pause", "charge_blocked_by_pause", is_fixable=True)
    await hass.async_block_till_done()  # no coordinator refresh: the registry event updates it

    state = _sensor(hass)
    assert int(state.state) == before + 1
    assert _issue(hass, "e2e_pause") == {
        "issue_id": "e2e_pause",
        "title": PAUSE_TITLE,
        "severity": "warning",
        "fixable": True,
    }
    assert f"- **{PAUSE_TITLE}**" in state.attributes["summary"]
    assert state.attributes["summary"].endswith("[Open Repairs](/config/repairs)")

    ir.async_delete_issue(hass, DOMAIN, "e2e_pause")
    await hass.async_block_till_done()
    assert int(_sensor(hass).state) == before
    assert _issue(hass, "e2e_pause") is None


async def test_an_issue_of_another_integration_is_not_counted(hass, loaded_entry):
    before = _sensor(hass)
    _create(hass, "other_integration", "something_broke", "something_broke")
    await hass.async_block_till_done()
    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    after = _sensor(hass)
    assert after.state == before.state
    assert after.attributes["issues"] == before.attributes["issues"]
    ir.async_delete_issue(hass, "other_integration", "something_broke")


async def test_an_ignored_issue_is_not_counted(hass, loaded_entry):
    before = int(_sensor(hass).state)
    _create(hass, DOMAIN, "e2e_pause", "charge_blocked_by_pause")
    await hass.async_block_till_done()
    assert int(_sensor(hass).state) == before + 1

    ir.async_ignore_issue(hass, DOMAIN, "e2e_pause", True)
    await hass.async_block_till_done()
    assert int(_sensor(hass).state) == before
    assert _issue(hass, "e2e_pause") is None

    ir.async_ignore_issue(hass, DOMAIN, "e2e_pause", False)
    await hass.async_block_till_done()
    assert int(_sensor(hass).state) == before + 1
    ir.async_delete_issue(hass, DOMAIN, "e2e_pause")


async def test_a_title_with_no_translation_falls_back_to_the_issue_id(hass, loaded_entry):
    _create(hass, DOMAIN, "e2e_untranslated", "no_such_translation_key")
    await hass.async_block_till_done()
    assert _issue(hass, "e2e_untranslated")["title"] == "e2e_untranslated"
    ir.async_delete_issue(hass, DOMAIN, "e2e_untranslated")


async def test_a_coordinator_update_reads_the_registry_too(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    _create(hass, DOMAIN, "e2e_pause", "charge_blocked_by_pause")
    await hass.async_block_till_done()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert "e2e_pause" in {i.issue_id for i in coordinator.data.active_repairs}
    assert int(_sensor(hass).state) == len(_ours(hass))
    ir.async_delete_issue(hass, DOMAIN, "e2e_pause")
