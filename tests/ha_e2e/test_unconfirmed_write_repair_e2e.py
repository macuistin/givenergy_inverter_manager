"""An inverter that keeps its old value after a write raises one repair, and it clears itself."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from conftest import CHARGE_END, CHEAP_NIGHT, MIDDAY, TARGET_SOC
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import ServiceCall
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.givenergy_inverter_manager import repairs
from custom_components.givenergy_inverter_manager.const import CONF_DRY_RUN, DOMAIN

ISSUE = repairs.ISSUE_WRITE_NOT_CONFIRMED
SERVICES = (
    ("number", "set_value"),
    ("switch", "turn_on"),
    ("switch", "turn_off"),
    ("select", "select_option"),
)
# Midday has no cheap-rate floor top-up, so the only writes are the ones a test asks for.
SCENARIO = pytest.mark.parametrize("scenario", [MIDDAY], ids=lambda s: s.name)


def _written_value(service: str, data: dict) -> str:
    if service == "turn_on":
        return "on"
    if service == "turn_off":
        return "off"
    return str(data.get("option", data.get("value")))


def _inverter(hass, takes: Callable[[str], bool]) -> list[tuple[str, str, str]]:
    """Stand in for GivTCP. A write to an entity that `takes` it moves the state, others do not.

    Registered after setup, because setting up the platforms registers Home Assistant's own
    number and switch services over any registered earlier.
    """
    calls: list[tuple[str, str, str]] = []
    # The inverter holds an older target than the 80% tonight's write asks for.
    hass.states.async_set(TARGET_SOC, 50)

    def register(service: str, domain: str) -> None:
        async def handle(call: ServiceCall) -> None:
            entity_id = call.data["entity_id"]
            value = _written_value(service, dict(call.data))
            calls.append((entity_id, service, value))
            if takes(entity_id):
                hass.states.async_set(entity_id, value)

        hass.services.async_register(domain, service, handle)

    for domain, service in SERVICES:
        register(service, domain)
    return calls


async def _nightly_write(hass, entry) -> None:
    """Run the once-a-night write the way the time listener does, with the cooldown spent."""
    coordinator = entry.runtime_data
    coordinator._backend.writer.last_write_time.clear()
    coordinator._write_charge_target_to_inverter(dt_util.utcnow())
    await hass.async_block_till_done()


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE)


def _issue_events(hass) -> list[str]:
    """The actions the issue registry reports for this issue, as they happen."""
    actions: list[str] = []

    def record(event) -> None:
        if event.data["domain"] == DOMAIN and event.data["issue_id"] == ISSUE:
            actions.append(event.data["action"])

    hass.bus.async_listen(ir.EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED, record)
    return actions


@SCENARIO
async def test_a_target_the_inverter_does_not_take_raises_a_repair(hass, loaded_entry):
    _inverter(hass, takes=lambda entity_id: False)

    await _nightly_write(hass, loaded_entry)

    issue = _issue(hass)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == ISSUE
    assert issue.learn_more_url == repairs.LEARN_MORE_URLS[ISSUE]
    settings = issue.translation_placeholders["settings"]
    assert f"({TARGET_SOC}, wrote " in settings
    assert f"({CHARGE_END}, wrote " in settings


@SCENARIO
async def test_a_write_the_inverter_takes_raises_nothing(hass, loaded_entry):
    calls = _inverter(hass, takes=lambda entity_id: True)

    await _nightly_write(hass, loaded_entry)

    assert calls
    assert _issue(hass) is None


@SCENARIO
async def test_dry_run_sends_nothing_and_raises_nothing(hass, loaded_entry):
    calls = _inverter(hass, takes=lambda entity_id: False)
    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, CONF_DRY_RUN: True}
    )
    await hass.async_block_till_done()
    assert loaded_entry.runtime_data.is_dry_run is True

    await _nightly_write(hass, loaded_entry)

    assert calls == []
    assert _issue(hass) is None


@SCENARIO
async def test_a_second_failure_of_the_same_settings_does_not_raise_again(hass, loaded_entry):
    _inverter(hass, takes=lambda entity_id: False)
    events = _issue_events(hass)

    await _nightly_write(hass, loaded_entry)
    # One create, then one update for each further setting that failed in the same sequence.
    assert events[0] == "create"
    assert events.count("create") == 1
    after_first_night = list(events)

    await _nightly_write(hass, loaded_entry)

    assert events == after_first_night
    assert _issue(hass) is not None


@SCENARIO
async def test_a_later_write_the_inverter_takes_clears_the_repair(hass, loaded_entry):
    taking = {"on": False}
    _inverter(hass, takes=lambda entity_id: taking["on"])
    await _nightly_write(hass, loaded_entry)
    assert _issue(hass) is not None

    taking["on"] = True  # Real Time Control turned back on
    await _nightly_write(hass, loaded_entry)

    assert _issue(hass) is None


@SCENARIO
async def test_settings_that_come_back_one_by_one_shrink_the_repair_then_clear_it(
    hass, loaded_entry
):
    taking: set[str] = set()
    _inverter(hass, takes=lambda entity_id: entity_id in taking)
    await _nightly_write(hass, loaded_entry)
    before = _issue(hass).translation_placeholders["settings"]
    assert f"({TARGET_SOC}," in before

    taking.add(TARGET_SOC)
    await _nightly_write(hass, loaded_entry)

    after = _issue(hass).translation_placeholders["settings"]
    assert f"({TARGET_SOC}," not in after
    assert f"({CHARGE_END}," in after


@SCENARIO
async def test_a_value_that_arrives_late_clears_the_repair_on_the_next_cycle(hass, loaded_entry):
    taking = {TARGET_SOC: False}
    calls = _inverter(hass, takes=lambda entity_id: taking.get(entity_id, True))
    await _nightly_write(hass, loaded_entry)
    assert _issue(hass) is not None

    asked = next(value for entity_id, _, value in calls if entity_id == TARGET_SOC)
    hass.states.async_set(TARGET_SOC, asked)
    await loaded_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert _issue(hass) is None


@SCENARIO
async def test_unloading_the_entry_clears_the_repair(hass, loaded_entry):
    _inverter(hass, takes=lambda entity_id: False)
    await _nightly_write(hass, loaded_entry)
    assert _issue(hass) is not None

    await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert loaded_entry.state is ConfigEntryState.NOT_LOADED
    assert _issue(hass) is None


@SCENARIO
async def test_removing_the_entry_clears_the_repair(hass, loaded_entry):
    _inverter(hass, takes=lambda entity_id: False)
    await _nightly_write(hass, loaded_entry)
    assert _issue(hass) is not None

    await hass.config_entries.async_remove(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert _issue(hass) is None


@pytest.mark.parametrize("scenario", [CHEAP_NIGHT], ids=lambda s: s.name)
async def test_a_cheap_rate_floor_top_up_the_inverter_does_not_take_raises_too(loaded_entry, hass):
    # The service_calls fixture changes no state, so the top-up at setup is never confirmed.
    issue = _issue(hass)
    assert issue is not None
    assert "floor top-up" in issue.translation_placeholders["settings"]
