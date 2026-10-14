"""The dashboard YAML action returns the strategy's dashboard as text, in a real Home Assistant."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError

from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.strategy import async_dashboard_for_websocket


async def _run(hass, user=None, **data) -> dict:
    context = Context(user_id=user.id) if user else Context()
    return await hass.services.async_call(
        DOMAIN, "get_dashboard_yaml", data, blocking=True, return_response=True, context=context
    )


def _paths(views: list[dict]) -> list[str]:
    return [view["path"] for view in views]


async def test_an_administrator_gets_the_whole_dashboard_as_yaml(
    hass, loaded_entry, hass_admin_user
):
    response = await _run(hass, hass_admin_user)

    config = yaml.safe_load(response["yaml"])
    assert config == await async_dashboard_for_websocket(hass, is_admin=True)
    assert response["views"] == len(config["views"])
    assert "settings" in _paths(config["views"])


async def test_someone_who_is_not_an_administrator_gets_no_settings_view(
    hass, loaded_entry, hass_read_only_user
):
    config = yaml.safe_load((await _run(hass, hass_read_only_user))["yaml"])

    assert config == await async_dashboard_for_websocket(hass, is_admin=False)
    assert "settings" not in _paths(config["views"])


async def test_a_call_with_no_user_gets_no_settings_view(hass, loaded_entry):
    config = yaml.safe_load((await _run(hass))["yaml"])

    assert "settings" not in _paths(config["views"])


async def test_the_action_says_so_when_the_integration_is_not_loaded(hass, loaded_entry):
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)

    with pytest.raises(ServiceValidationError):
        await _run(hass)


async def test_no_file_is_written_unless_asked_for(hass, loaded_entry, hass_admin_user):
    response = await _run(hass, hass_admin_user)

    assert "file" not in response
    assert not Path(hass.config.path("givenergy_dashboard.yaml")).exists()


async def test_write_file_saves_the_same_yaml_in_the_config_folder(
    hass, loaded_entry, hass_admin_user
):
    response = await _run(hass, hass_admin_user, write_file=True)

    path = Path(response["file"])
    assert path == Path(hass.config.path("givenergy_dashboard.yaml"))
    assert path.read_text(encoding="utf-8") == response["yaml"]


async def test_write_file_replaces_the_file_it_wrote_before(hass, loaded_entry, hass_admin_user):
    path = Path(hass.config.path("givenergy_dashboard.yaml"))
    path.write_text("old", encoding="utf-8")

    await _run(hass, hass_admin_user, write_file=True)

    assert path.read_text(encoding="utf-8").startswith("views:")
