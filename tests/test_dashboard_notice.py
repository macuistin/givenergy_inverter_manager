"""The notice that tells a user, once, how to add the dashboard.

The integration cannot create the dashboard. At first setup it looks for one that uses the
strategy, and sends a notification when there is none. The answer is saved as the
dashboard_url_path option, so a reload or a restart never asks again. Against real Home
Assistant, tests/ha_e2e/test_dashboard_notice_e2e.py runs the same flow with a real Lovelace.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.givenergy_inverter_manager import dashboard_notice as notice
from custom_components.givenergy_inverter_manager.const import CONF_DASHBOARD_URL_PATH

POINTER = {"strategy": {"type": "custom:givenergy-manager"}}


class _Dashboard:
    """A Lovelace dashboard with a saved config, or one that raises when it is loaded."""

    def __init__(self, config=None, error: Exception | None = None) -> None:
        self.async_load = AsyncMock(return_value=config, side_effect=error)


def _hass(dashboards=None, *, lovelace=True, as_dict=False):
    hass = MagicMock()
    if not lovelace:
        hass.data = {}
    elif as_dict:
        hass.data = {"lovelace": {"dashboards": dashboards or {}}}
    else:
        hass.data = {"lovelace": SimpleNamespace(dashboards=dashboards or {})}
    return hass


def _entry(options=None):
    return SimpleNamespace(options=dict(options or {}), entry_id="entry")


def _announce(hass, entry):
    with patch.object(notice, "_create_notification") as create:
        asyncio.run(notice.async_announce_dashboard(hass, entry))
    return create


def _saved(hass) -> list[dict]:
    return [call.kwargs["options"] for call in hass.config_entries.async_update_entry.call_args_list]


class TestFirstRun:
    def test_with_no_dashboard_it_sends_the_notification_and_saves_an_empty_path(self):
        hass, entry = _hass({None: _Dashboard(error=Exception())}), _entry()
        create = _announce(hass, entry)
        create.assert_called_once_with(hass)
        assert _saved(hass) == [{CONF_DASHBOARD_URL_PATH: ""}]

    def test_it_keeps_the_other_options_when_it_saves(self):
        hass, entry = _hass(), _entry({"dry_run": True})
        _announce(hass, entry)
        assert _saved(hass) == [{"dry_run": True, CONF_DASHBOARD_URL_PATH: ""}]

    def test_a_dashboard_that_uses_the_strategy_is_recorded_and_nothing_is_sent(self):
        hass = _hass({None: _Dashboard(error=Exception()), "givenergy": _Dashboard(POINTER)})
        create = _announce(hass, _entry())
        create.assert_not_called()
        assert _saved(hass) == [{CONF_DASHBOARD_URL_PATH: "givenergy"}]

    def test_the_default_dashboard_counts_and_is_recorded_as_lovelace(self):
        hass = _hass({None: _Dashboard(POINTER)})
        create = _announce(hass, _entry())
        create.assert_not_called()
        assert _saved(hass) == [{CONF_DASHBOARD_URL_PATH: "lovelace"}]

    def test_lovelace_held_as_a_dict_is_read_too(self):
        hass = _hass({"givenergy": _Dashboard(POINTER)}, as_dict=True)
        _announce(hass, _entry())
        assert _saved(hass) == [{CONF_DASHBOARD_URL_PATH: "givenergy"}]

    @pytest.mark.parametrize(
        "config",
        [
            {"views": []},
            {"strategy": {"type": "original-states"}},
            {"strategy": {"type": "custom:something-else"}},
            {"strategy": "custom:givenergy-manager"},
            None,
        ],
        ids=["static", "built-in strategy", "other custom strategy", "not a mapping", "empty"],
    )
    def test_a_dashboard_that_does_not_use_the_strategy_is_not_ours(self, config):
        hass = _hass({"mine": _Dashboard(config)})
        create = _announce(hass, _entry())
        create.assert_called_once_with(hass)
        assert _saved(hass) == [{CONF_DASHBOARD_URL_PATH: ""}]


class TestOnlyOnce:
    @pytest.mark.parametrize("saved", ["", "givenergy", "lovelace"])
    def test_a_saved_answer_means_nothing_is_looked_up_or_sent(self, saved):
        dashboard = _Dashboard(POINTER)
        hass = _hass({"givenergy": dashboard})
        create = _announce(hass, _entry({CONF_DASHBOARD_URL_PATH: saved}))
        create.assert_not_called()
        dashboard.async_load.assert_not_called()
        assert _saved(hass) == []

    def test_a_dashboard_the_user_deleted_is_not_asked_for_again(self):
        entry = _entry({CONF_DASHBOARD_URL_PATH: "givenergy"})
        hass = _hass({})  # the dashboard is gone
        create = _announce(hass, entry)
        create.assert_not_called()
        assert _saved(hass) == []

    def test_a_second_setup_after_the_first_does_not_send_again(self):
        hass, entry = _hass(), _entry()
        first = _announce(hass, entry)
        entry.options = _saved(hass)[-1]
        second = _announce(hass, entry)
        assert first.call_count == 1
        assert second.call_count == 0
        assert len(_saved(hass)) == 1


class TestWhenItCannotLook:
    def test_without_lovelace_it_sends_nothing_and_saves_nothing(self):
        hass = _hass(lovelace=False)
        create = _announce(hass, _entry())
        create.assert_not_called()
        assert _saved(hass) == []

    @pytest.mark.parametrize(
        "lovelace",
        [None, SimpleNamespace(), SimpleNamespace(dashboards=None), {"dashboards": "bad"}, 5],
        ids=["none", "no attribute", "none dashboards", "not a dict", "number"],
    )
    def test_dashboards_that_cannot_be_read_mean_the_user_is_told(self, lovelace):
        hass = MagicMock()
        hass.data = {"lovelace": lovelace} if lovelace is not None else {"lovelace": object()}
        create = _announce(hass, _entry())
        create.assert_called_once_with(hass)

    def test_a_dashboard_that_fails_to_load_is_skipped_and_the_rest_are_still_read(self):
        hass = _hass(
            {
                "broken": _Dashboard(error=RuntimeError("boom")),
                "givenergy": _Dashboard(POINTER),
            }
        )
        create = _announce(hass, _entry())
        create.assert_not_called()
        assert _saved(hass) == [{CONF_DASHBOARD_URL_PATH: "givenergy"}]

    def test_a_change_inside_lovelace_that_breaks_the_lookup_still_tells_the_user(self):
        hass = _hass()
        with patch.object(notice, "_dashboards", side_effect=AttributeError("moved")):
            create = _announce(hass, _entry())
        create.assert_called_once_with(hass)
        assert _saved(hass) == [{CONF_DASHBOARD_URL_PATH: ""}]


class TestTheNotification:
    def test_it_says_where_to_go_and_what_to_pick(self):
        text = notice.NOTIFICATION_MESSAGE
        assert "Settings → Dashboards → Add dashboard" in text
        assert "Community dashboards" in text
        assert "GivEnergy" in text
        assert notice.DOCS_URL in text

    def test_it_has_one_fixed_id_so_a_second_send_replaces_it(self):
        assert notice.NOTIFICATION_ID == "givenergy_inverter_manager_add_dashboard"

    def test_it_is_created_through_the_component_with_that_id(self):
        persistent = MagicMock()
        with patch.dict(
            "sys.modules",
            {"homeassistant.components.persistent_notification": persistent},
        ), patch("homeassistant.components.persistent_notification", persistent, create=True):
            hass = MagicMock()
            notice._create_notification(hass)
        persistent.async_create.assert_called_once_with(
            hass,
            notice.NOTIFICATION_MESSAGE,
            title=notice.NOTIFICATION_TITLE,
            notification_id=notice.NOTIFICATION_ID,
        )


class TestSetupNeverFails:
    def test_an_error_while_announcing_is_logged_and_setup_goes_on(self):
        from custom_components.givenergy_inverter_manager import _announce_dashboard

        hass, entry = MagicMock(), _entry()
        with patch(
            "custom_components.givenergy_inverter_manager.async_announce_dashboard",
            AsyncMock(side_effect=RuntimeError("boom")),
        ):
            asyncio.run(_announce_dashboard(hass, entry))


class TestRemoval:
    def _remove(self, other_entries):
        from custom_components.givenergy_inverter_manager import async_remove_entry

        hass = MagicMock()
        hass.config_entries.async_entries.return_value = other_entries
        entry = SimpleNamespace(entry_id="gone")
        with patch.object(notice, "_dismiss_notification") as dismiss:
            asyncio.run(async_remove_entry(hass, entry))
        return hass, dismiss

    def test_the_notice_is_taken_down_with_the_last_entry(self):
        hass, dismiss = self._remove([SimpleNamespace(entry_id="gone")])
        dismiss.assert_called_once_with(hass)

    def test_it_stays_while_another_entry_remains(self):
        _, dismiss = self._remove([SimpleNamespace(entry_id="gone"), SimpleNamespace(entry_id="b")])
        dismiss.assert_not_called()
