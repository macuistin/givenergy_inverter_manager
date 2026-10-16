"""The stored dashboard: update_dashboard writes it, and a repair says when it is out of date.

Everything runs against the real lovelace component (set up as in the SP1 spike,
tests/ha_e2e/spikes/test_sp1_dashboard_creation.py) with the harness's storage mock. Dashboards
are created and edited the way a user does, through the dashboards websocket commands, and read
back the same way the frontend reads them.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from conftest import MIDDAY
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.givenergy_inverter_manager.const import (
    CONF_DASHBOARD_URL_PATH,
    CONF_DRY_RUN,
    CONF_STORED_DASHBOARD_URL_PATH,
    DOMAIN,
)
from custom_components.givenergy_inverter_manager.core.stored_dashboard import as_stored
from custom_components.givenergy_inverter_manager.repairs import ISSUE_DASHBOARD_OUT_OF_DATE
from custom_components.givenergy_inverter_manager.strategy import async_dashboard_for_websocket

URL = "energy-home"
BACKUP = "givenergy_dashboard_backup.yaml"
MINE = {"views": [{"title": "Mine", "cards": [{"type": "markdown", "content": "hello"}]}]}


@pytest.fixture
def scenario():
    return MIDDAY


async def _ask(client, **msg) -> dict:
    _ask.next_id = getattr(_ask, "next_id", 0) + 1
    await client.send_json({"id": _ask.next_id, **msg})
    return await client.receive_json()


async def _set_up_lovelace(hass, hass_ws_client, config: dict | None = None):
    # Repairs registers HTTP views, so it is set up before the websocket client starts the app.
    assert await async_setup_component(hass, "repairs", {})
    assert await async_setup_component(hass, "lovelace", config or {})
    await hass.async_block_till_done()
    return await hass_ws_client(hass)


@pytest.fixture
async def lovelace(hass_in_scenario, hass_ws_client):
    """Lovelace, and an administrator's websocket client, before the entry is set up."""
    return await _set_up_lovelace(hass_in_scenario, hass_ws_client)


async def _create(client, url_path: str = URL, config: dict | None = None) -> None:
    created = await _ask(client, type="lovelace/dashboards/create", url_path=url_path, title="E")
    assert created["success"], created
    if config is not None:
        await _save(client, config, url_path)


async def _save(client, config: dict, url_path: str = URL) -> None:
    saved = await _ask(client, type="lovelace/config/save", url_path=url_path, config=config)
    assert saved["success"], saved


async def _read(client, url_path: str = URL) -> dict | None:
    read = await _ask(client, type="lovelace/config", url_path=url_path, force=False)
    return read["result"] if read["success"] else None


async def _set_up(hass, entry, options: dict | None = None) -> None:
    entry.add_to_hass(hass)
    if options:
        hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


@pytest.fixture
async def entry(hass_in_scenario, service_calls, config_entry, lovelace):
    """The config entry, set up after Lovelace as Home Assistant does at start."""
    await _set_up(hass_in_scenario, config_entry)
    yield config_entry
    if config_entry.state is ConfigEntryState.LOADED:
        await hass_in_scenario.config_entries.async_unload(config_entry.entry_id)
        await hass_in_scenario.async_block_till_done()


async def _update(hass, user, **data) -> dict:
    context = Context(user_id=user.id) if user else Context()
    return await hass.services.async_call(
        DOMAIN, "update_dashboard", data, blocking=True, return_response=True, context=context
    )


async def _generated(hass) -> dict:
    return as_stored(await async_dashboard_for_websocket(hass, is_admin=True))


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_DASHBOARD_OUT_OF_DATE)


async def _later(hass, freezer, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _backup(hass) -> Path:
    return Path(hass.config.path(BACKUP))


# ── the action ──────────────────────────────────────────────────────────────


async def test_the_action_writes_the_admin_dashboard_into_a_new_storage_dashboard(
    hass, entry, lovelace, hass_admin_user
):
    await _create(lovelace)

    response = await _update(hass, hass_admin_user, url_path=URL)

    stored = await _read(lovelace)
    assert stored == await _generated(hass)
    assert "settings" in [view["path"] for view in stored["views"]]
    assert response == {"url_path": URL, "views": len(stored["views"]), "backup_file": None}
    assert entry.options[CONF_STORED_DASHBOARD_URL_PATH] == URL
    assert not _backup(hass).exists()


async def test_the_previous_config_is_saved_to_the_backup_file(
    hass, entry, lovelace, hass_admin_user
):
    await _create(lovelace, config=MINE)

    response = await _update(hass, hass_admin_user, url_path=URL)

    assert response["backup_file"] == str(_backup(hass))
    assert yaml.safe_load(_backup(hass).read_text(encoding="utf-8")) == MINE


async def test_a_second_run_replaces_the_backup_with_what_it_replaced(
    hass, entry, lovelace, hass_admin_user
):
    await _create(lovelace, config=MINE)
    await _update(hass, hass_admin_user, url_path=URL)

    await _update(hass, hass_admin_user, url_path=URL)

    assert yaml.safe_load(_backup(hass).read_text(encoding="utf-8")) == await _generated(hass)


async def test_with_no_url_path_the_remembered_dashboard_is_written(
    hass, entry, lovelace, hass_admin_user
):
    await _create(lovelace)
    await _update(hass, hass_admin_user, url_path=URL)
    await _save(lovelace, MINE)

    response = await _update(hass, hass_admin_user)

    assert response["url_path"] == URL
    assert await _read(lovelace) == await _generated(hass)


async def test_someone_who_is_not_an_administrator_is_refused(
    hass, entry, lovelace, hass_read_only_user
):
    await _create(lovelace, config=MINE)

    with pytest.raises(ServiceValidationError) as err:
        await _update(hass, hass_read_only_user, url_path=URL)

    assert err.value.translation_key == "dashboard_update_needs_admin"
    assert "administrator" in str(err.value)
    assert await _read(lovelace) == MINE
    assert CONF_STORED_DASHBOARD_URL_PATH not in entry.options


async def test_a_call_with_no_user_is_refused(hass, entry, lovelace):
    await _create(lovelace)

    with pytest.raises(ServiceValidationError) as err:
        await _update(hass, None, url_path=URL)

    assert err.value.translation_key == "dashboard_update_needs_admin"
    assert await _read(lovelace) is None


async def test_an_unknown_url_path_is_refused(hass, entry, hass_admin_user):
    with pytest.raises(ServiceValidationError) as err:
        await _update(hass, hass_admin_user, url_path="no-such-dashboard")

    assert err.value.translation_key == "dashboard_not_found"
    assert "There is no dashboard at /no-such-dashboard" in str(err.value)
    assert CONF_STORED_DASHBOARD_URL_PATH not in entry.options


async def test_no_url_path_and_none_remembered_is_refused(hass, entry, hass_admin_user):
    with pytest.raises(ServiceValidationError) as err:
        await _update(hass, hass_admin_user)

    assert err.value.translation_key == "dashboard_url_path_missing"
    assert "Give the URL path" in str(err.value)


async def test_a_yaml_dashboard_is_refused_and_its_file_is_left_alone(
    hass_in_scenario, hass_ws_client, service_calls, config_entry, hass_admin_user
):
    hass = hass_in_scenario
    yaml_file = Path(hass.config.path("energy.yaml"))
    yaml_file.write_text("views: []\n", encoding="utf-8")
    dashboards = {"energy-yaml": {"mode": "yaml", "filename": "energy.yaml", "title": "E"}}
    await _set_up_lovelace(hass, hass_ws_client, {"lovelace": {"dashboards": dashboards}})
    await _set_up(hass, config_entry)

    with pytest.raises(ServiceValidationError) as err:
        await _update(hass, hass_admin_user, url_path="energy-yaml")

    assert err.value.translation_key == "dashboard_not_storage"
    assert "YAML dashboard" in str(err.value)
    assert yaml_file.read_text(encoding="utf-8") == "views: []\n"
    assert not _backup(hass).exists()
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_recovery_mode_is_refused(hass, entry, lovelace, hass_admin_user):
    await _create(lovelace, config=MINE)
    hass.config.recovery_mode = True
    try:
        with pytest.raises(ServiceValidationError) as err:
            await _update(hass, hass_admin_user, url_path=URL)
    finally:
        hass.config.recovery_mode = False

    assert err.value.translation_key == "dashboard_recovery_mode"
    assert await _read(lovelace) == MINE


# ── the repair ──────────────────────────────────────────────────────────────


async def test_the_repair_is_not_raised_when_nothing_is_remembered(hass, entry, lovelace, freezer):
    await _create(lovelace, config=MINE)

    await _later(hass, freezer, 3601)

    assert _issue(hass) is None


async def test_the_repair_is_not_raised_while_the_dashboard_matches(
    hass, entry, lovelace, hass_admin_user, freezer
):
    await _create(lovelace)
    await _update(hass, hass_admin_user, url_path=URL)

    await _later(hass, freezer, 3601)

    assert _issue(hass) is None


async def test_an_edited_dashboard_raises_the_repair_within_the_hour(
    hass, entry, lovelace, hass_admin_user, freezer
):
    await _create(lovelace)
    await _update(hass, hass_admin_user, url_path=URL)
    await _save(lovelace, MINE)

    await _later(hass, freezer, 3601)

    issue = _issue(hass)
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.is_persistent is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {"url_path": URL, "backup_file": BACKUP}


async def test_an_options_change_checks_at_once(hass, entry, lovelace, hass_admin_user):
    await _create(lovelace)
    await _update(hass, hass_admin_user, url_path=URL)
    await _save(lovelace, MINE)
    assert _issue(hass) is None

    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_DRY_RUN: True})
    await hass.async_block_till_done()

    assert _issue(hass) is not None


async def test_an_entity_registry_change_checks_after_a_quiet_minute(
    hass, entry, lovelace, hass_admin_user, freezer
):
    await _create(lovelace)
    await _update(hass, hass_admin_user, url_path=URL)
    registry = er.async_get(hass)
    battery_soc = next(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id == f"{entry.entry_id}_battery_soc"
    )

    registry.async_update_entity(battery_soc, disabled_by=er.RegistryEntryDisabler.USER)
    await hass.async_block_till_done()
    await _later(hass, freezer, 30)
    assert _issue(hass) is None

    await _later(hass, freezer, 31)
    assert _issue(hass) is not None


async def test_a_remembered_dashboard_that_differs_raises_the_repair_at_setup(
    hass_in_scenario, service_calls, config_entry, lovelace
):
    hass = hass_in_scenario
    await _create(lovelace, config=MINE)

    await _set_up(hass, config_entry, {CONF_STORED_DASHBOARD_URL_PATH: URL})

    assert _issue(hass) is not None
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(hass) is None


async def test_the_fix_writes_the_dashboard_and_clears_the_repair(
    hass, entry, lovelace, hass_admin_user, freezer
):
    await _create(lovelace)
    await _update(hass, hass_admin_user, url_path=URL)
    await _save(lovelace, MINE)
    await _later(hass, freezer, 3601)
    assert _issue(hass) is not None

    manager = repairs_flow_manager(hass)
    flow = await manager.async_init(DOMAIN, data={"issue_id": ISSUE_DASHBOARD_OUT_OF_DATE})
    assert flow["type"] is FlowResultType.FORM
    assert flow["step_id"] == "confirm"
    assert flow["description_placeholders"] == {"url_path": URL, "backup_file": BACKUP}
    result = await manager.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _issue(hass) is None
    assert await _read(lovelace) == await _generated(hass)
    assert yaml.safe_load(_backup(hass).read_text(encoding="utf-8")) == MINE


async def test_a_deleted_dashboard_clears_the_repair_and_is_forgotten(
    hass, entry, lovelace, hass_admin_user, freezer, caplog
):
    await _create(lovelace)
    await _update(hass, hass_admin_user, url_path=URL)
    await _save(lovelace, MINE)
    await _later(hass, freezer, 3601)
    assert _issue(hass) is not None

    deleted = await _ask(lovelace, type="lovelace/dashboards/delete", dashboard_id="energy_home")
    assert deleted["success"], deleted
    with caplog.at_level(logging.INFO):
        await _later(hass, freezer, 3601)
        await _later(hass, freezer, 3601)

    assert _issue(hass) is None
    assert entry.options[CONF_STORED_DASHBOARD_URL_PATH] == ""
    gone = [r for r in caplog.records if "is gone or not a storage dashboard" in r.getMessage()]
    assert len(gone) == 1
    assert gone[0].levelno == logging.INFO


async def test_a_strategy_dashboard_found_at_setup_is_never_kept_current(
    hass_in_scenario, service_calls, config_entry, lovelace, freezer
):
    hass = hass_in_scenario
    pointer = {"strategy": {"type": "custom:givenergy-manager"}}
    await _create(lovelace, config=pointer)
    await _set_up(hass, config_entry)

    await _later(hass, freezer, 3601)

    assert config_entry.options[CONF_DASHBOARD_URL_PATH] == URL
    assert not config_entry.options.get(CONF_STORED_DASHBOARD_URL_PATH)
    assert _issue(hass) is None
    assert await _read(lovelace) == pointer
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_a_remembered_dashboard_is_kept_while_lovelace_is_not_loaded(
    hass_in_scenario, service_calls, config_entry, freezer
):
    hass = hass_in_scenario
    await _set_up(hass, config_entry, {CONF_STORED_DASHBOARD_URL_PATH: URL})

    await _later(hass, freezer, 3601)

    assert config_entry.options[CONF_STORED_DASHBOARD_URL_PATH] == URL
    assert _issue(hass) is None
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_running_the_action_clears_the_repair_at_once(
    hass, entry, lovelace, hass_admin_user, freezer
):
    await _create(lovelace)
    await _update(hass, hass_admin_user, url_path=URL)
    await _save(lovelace, MINE)
    await _later(hass, freezer, 3601)
    assert _issue(hass) is not None

    await _update(hass, hass_admin_user)

    assert _issue(hass) is None
