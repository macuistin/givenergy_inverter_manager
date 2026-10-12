"""The setup wizard, the repairs and the entity references, against the GivTCP system fixtures.

Only the single-phase hybrid fixture comes from real hardware. The others are built from GivTCP's
published datapoint reference (tests/fixtures/givtcp_systems/build.py), so what these tests prove
for them is that the integration follows its own rules on that layout, not that GivTCP publishes
exactly those names.
"""

from __future__ import annotations

import pytest
from conftest import MIDDAY, PREFIX, SERIAL
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from setup_support import finish, manager, run_pages, start, unload
from wizard_support import serialised

from custom_components.givenergy_inverter_manager.const import (
    CONF_INVERTER_SERIAL,
    CONF_SOLAR_POWER,
    CONF_TARGET_SOC_ENTITY,
    DOMAIN,
)
from tests.fixtures import givtcp_systems as fixtures

REAL_HYBRID = "hybrid_gen3_two_batteries_3_6_3"


@pytest.fixture
def scenario():
    return MIDDAY


def use_fixture(hass, name: str) -> None:
    """Replace every GivTCP entity in the harness with the ones in the fixture."""
    for entity_id in list(hass.states.async_entity_ids()):
        if "givtcp" in entity_id or SERIAL in entity_id:
            hass.states.async_remove(entity_id)
    for entity_id, value in fixtures.raw(name)["states"].items():
        hass.states.async_set(entity_id, value["state"], value.get("attributes", {}))


def found_text(result) -> str:
    return result["description_placeholders"]["found"]


def select_options(result) -> list[str]:
    fields = {f["name"]: f for f in serialised(result)}
    if "discovered_inverter" not in fields:
        return []
    return [o["value"] for o in fields["discovered_inverter"]["selector"]["select"]["options"]]


# ── The first screen, one fixture at a time ───────────────────────────────────


async def test_the_real_hybrid_says_what_it_is_and_asks_nothing(hass, hass_in_scenario, service_calls):
    use_fixture(hass, REAL_HYBRID)

    result = await start(hass)

    assert "(hybrid inverter), all sensors found and used" in found_text(result)
    assert "not been tested on real hardware" not in found_text(result)
    assert select_options(result) == []
    manager(hass).async_abort(result["flow_id"])


@pytest.mark.parametrize(
    ("name", "words"),
    [
        ("ac_coupled_3_6_3", "AC-coupled inverter"),
        ("all_in_one_3_6_3", "All-In-One"),
        ("three_phase_3_6_3", "three-phase inverter"),
    ],
)
async def test_a_type_not_tested_on_real_hardware_says_so(
    hass, hass_in_scenario, service_calls, name, words
):
    use_fixture(hass, name)

    result = await start(hass)

    assert f"({words}), all sensors found and used" in found_text(result)
    assert f"A {words} has not been tested on real hardware" in found_text(result)
    manager(hass).async_abort(result["flow_id"])


async def test_a_gateway_over_parallel_units_is_managed_without_a_question(
    hass, hass_in_scenario, service_calls
):
    use_fixture(hass, "gateway_parallel_two_aio_3_6_3")

    result = await start(hass)

    assert "GW5678K901 (Gateway)" in found_text(result)
    assert select_options(result) == []
    _, confirm = await run_pages(hass, result, [])
    entry = await finish(hass, confirm)
    try:
        assert entry.unique_id == "GW5678K901"
    finally:
        await unload(hass, entry)


async def test_an_all_in_one_beside_a_gateway_that_is_not_parallel_is_managed_directly(
    hass, hass_in_scenario, service_calls
):
    use_fixture(hass, "all_in_one_and_gateway_3_6_3")

    result = await start(hass)

    assert "AB1234G567 (All-In-One)" in found_text(result)
    assert "Also found, not managed: GW5678K901 (Gateway)" in found_text(result)
    assert select_options(result) == []
    manager(hass).async_abort(result["flow_id"])


async def test_two_inverters_ask_which_to_manage_and_say_they_are_never_added(
    hass, hass_in_scenario, service_calls
):
    use_fixture(hass, "two_hybrids_3_6_3")

    result = await start(hass)

    assert select_options(result) == ["AB1234G567", "CD5678H901"]
    assert "They are never added up." in found_text(result)
    _, confirm = await run_pages(hass, result, [], system={"discovered_inverter": "CD5678H901"})
    entry = await finish(hass, confirm)
    try:
        assert entry.unique_id == "CD5678H901"
        assert entry.data[CONF_SOLAR_POWER] == "sensor.givtcp_cd5678h901_pv_power"
    finally:
        await unload(hass, entry)


async def test_an_ems_gets_no_charge_settings_and_the_screen_says_so(
    hass, hass_in_scenario, service_calls
):
    use_fixture(hass, "ems_3_6_3")

    result = await start(hass)

    assert "no charge settings will be written" in found_text(result)
    assert "some sensors are missing" in found_text(result)
    manager(hass).async_abort(result["flow_id"])


# ── A prefix changed in GivTCP ────────────────────────────────────────────────


async def test_a_custom_prefix_is_set_up_and_read_from_its_own_entities(
    hass, hass_in_scenario, service_calls
):
    use_fixture(hass, "hybrid_custom_prefix_3_6_3")

    result = await start(hass)
    _, confirm = await run_pages(hass, result, [])
    entry = await finish(hass, confirm)
    try:
        assert entry.data[CONF_SOLAR_POWER] == "sensor.house_ab1234g567_pv_power"
        assert entry.data[CONF_TARGET_SOC_ENTITY] == "number.house_ab1234g567_target_soc"
        coordinator = entry.runtime_data
        assert coordinator._backend.identity.prefix == "house_ab1234g567"
        # The values derived from the prefix are read from the house_ entities, not givtcp_.
        values = coordinator._backend.read(coordinator._effective_cfg())
        assert values.data_age_s == pytest.approx(0.5)
        assert values.ac_charge_energy_today_kwh == pytest.approx(9.6)
        assert coordinator._backend.solar_energy_entity_id(coordinator._effective_cfg()) == (
            "sensor.house_ab1234g567_pv_energy_today_kwh"
        )
        assert coordinator._backend.feed_status(coordinator._effective_cfg(), coordinator._now())
    finally:
        await unload(hass, entry)


# ── Reconfigure ───────────────────────────────────────────────────────────────


async def test_reconfigure_finds_the_same_inverter_under_a_custom_prefix(
    hass, hass_in_scenario, service_calls, loaded_entry
):
    use_fixture(hass, "hybrid_custom_prefix_3_6_3")

    result = await loaded_entry.start_reconfigure_flow(hass)

    assert result["step_id"] == "reconfigure"
    assert "sensor.house_ab1234g567_pv_power" in result["description_placeholders"]["found"]


# ── What changed since the integration last looked ────────────────────────────


def _issue(hass, issue_id: str):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def _look(hass, entry) -> None:
    """Run the cycle that looks at the system again."""
    coordinator = entry.runtime_data
    coordinator._update_cycle = 9  # the next cycle is the tenth
    await coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_the_first_look_records_the_system_and_raises_nothing(hass, loaded_entry):
    await _look(hass, loaded_entry)

    stored = loaded_entry.runtime_data._acc.state.system_identity
    assert (stored["kind"], stored["controller"].lower()) == ("hybrid", SERIAL)
    assert _issue(hass, "system_looks_different") is None


async def test_a_new_givtcp_version_alone_is_not_a_different_system(hass, loaded_entry):
    await _look(hass, loaded_entry)
    hass.states.async_set(f"sensor.{PREFIX}_givtcp_version", "3.6.4")

    await _look(hass, loaded_entry)

    assert _issue(hass, "system_looks_different") is None
    assert loaded_entry.runtime_data._acc.state.system_identity["version"] == "3.6.4"


async def test_a_changed_type_raises_one_repair_and_keeps_the_stored_system(hass, loaded_entry):
    await _look(hass, loaded_entry)
    before = dict(loaded_entry.runtime_data._acc.state.system_identity)
    hass.states.async_set(f"sensor.{PREFIX}_invertor_type", "Three_phase")
    for suffix in ("grid_phase_1_voltage", "load_phase_1_power"):
        hass.states.async_set(f"sensor.{PREFIX}_{suffix}", "0")

    await _look(hass, loaded_entry)

    issue = _issue(hass, "system_looks_different")
    assert issue is not None and issue.is_fixable
    assert "type hybrid inverter to three-phase inverter" in issue.translation_placeholders["changes"]
    assert loaded_entry.runtime_data._acc.state.system_identity == before
    assert loaded_entry.unique_id == SERIAL  # the managed inverter is the same one

    loaded_entry.runtime_data.accept_system_as_it_is()

    assert _issue(hass, "system_looks_different") is None
    assert loaded_entry.runtime_data._acc.state.system_identity["kind"] == "three_phase"


async def test_a_gateway_that_appears_over_the_inverter_is_reported_not_followed(
    hass, loaded_entry
):
    await _look(hass, loaded_entry)
    gateway = "givtcp_gw5678k901"
    for suffix, value in (
        ("givtcp_version", "3.6.3"),
        ("soc", "50"),
        ("gateway_state", "Normal"),
        ("parallel_total_aio_number", "2"),
    ):
        hass.states.async_set(f"sensor.{gateway}_{suffix}", value)

    await _look(hass, loaded_entry)

    issue = _issue(hass, "system_looks_different")
    assert issue is not None
    assert f"managed inverter {SERIAL} to GW5678K901" in issue.translation_placeholders["changes"]
    assert loaded_entry.data[CONF_INVERTER_SERIAL] == SERIAL


# ── An entity id that GivTCP changed ──────────────────────────────────────────


def _register(hass, entity_id: str, unique_id: str) -> None:
    """Give an entity that only has a state a registry entry, as an MQTT entity has."""
    domain, _, name = entity_id.partition(".")
    state = hass.states.get(entity_id)
    hass.states.async_remove(entity_id)  # the registry will not reuse an id that has a state
    entry = er.async_get(hass).async_get_or_create(
        domain, "mqtt", unique_id, suggested_object_id=name
    )
    assert entry.entity_id == entity_id
    hass.states.async_set(entity_id, state.state, state.attributes)


async def test_an_entity_renamed_by_givtcp_is_found_again_by_its_registry_id(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data
    _register(hass, f"sensor.{PREFIX}_pv_power", "ab1234g567_pv_power")
    await coordinator.async_refresh()  # learns the unique id while the id still matches
    assert coordinator._acc.state.entity_refs[CONF_SOLAR_POWER]["unique_id"] == "ab1234g567_pv_power"

    # GivTCP 3.6.1 resets the id to its default and the old one disappears.
    registry = er.async_get(hass)
    old = f"sensor.{PREFIX}_pv_power"
    value = hass.states.get(old).state
    hass.states.async_remove(old)
    registry.async_update_entity(old, new_entity_id="sensor.pv_power_default")
    hass.states.async_set("sensor.pv_power_default", value)
    for _ in range(12):
        await coordinator.async_refresh()

    assert coordinator._effective_cfg()[CONF_SOLAR_POWER] == "sensor.pv_power_default"
    assert _issue(hass, "givtcp_entities_missing") is None
    assert coordinator.last_update_success


async def test_an_entity_that_cannot_be_found_raises_one_repair_after_five_minutes_and_no_crash(
    hass, loaded_entry
):
    coordinator = loaded_entry.runtime_data
    old = f"number.{PREFIX}_target_soc"
    hass.states.async_remove(old)

    for _ in range(9):
        await coordinator.async_refresh()
    assert _issue(hass, "givtcp_entities_missing") is None  # not yet: a start-up would look alike

    for _ in range(3):
        await coordinator.async_refresh()

    issue = _issue(hass, "givtcp_entities_missing")
    assert issue is not None
    assert old in issue.translation_placeholders["entities"]
    assert coordinator.last_update_success

    hass.states.async_set(old, "80")
    await coordinator.async_refresh()
    assert _issue(hass, "givtcp_entities_missing") is None


async def test_an_old_givtcp_raises_one_repair_and_it_clears_after_the_update(hass, loaded_entry):
    hass.states.async_set(f"sensor.{PREFIX}_givtcp_version", "3.6.1")

    await _look(hass, loaded_entry)

    issue = _issue(hass, "givtcp_too_old")
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.translation_placeholders == {"version": "3.6.1", "minimum": "3.6.2"}

    hass.states.async_set(f"sensor.{PREFIX}_givtcp_version", "3.6.3")
    await _look(hass, loaded_entry)

    assert _issue(hass, "givtcp_too_old") is None


async def test_a_version_that_cannot_be_read_raises_no_repair(hass, loaded_entry):
    hass.states.async_set(f"sensor.{PREFIX}_givtcp_version", "unknown")

    await _look(hass, loaded_entry)

    assert _issue(hass, "givtcp_too_old") is None
