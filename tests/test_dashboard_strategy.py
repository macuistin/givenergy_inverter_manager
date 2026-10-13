"""
Tests for the dashboard strategy shim (strategy.py and frontend/givenergy-manager-strategy.js).

The websocket command, the static file route and the frontend module URL are
exercised against a real Home Assistant in tests/ha_e2e/test_dashboard_strategy_e2e.py.
The JavaScript is run under node when node is installed.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState

from tests.dashboard_support import (
    ADMIN_ID,
    ENTRY_ID,
    FULL_CONFIG,
    FakeRegistry,
    dashboard_dict,
    fake_hass,
)


def _strategy():
    from custom_components.givenergy_inverter_manager import strategy

    return strategy


class TestStrategyFile:
    def _source(self) -> str:
        return _strategy().STRATEGY_FILE.read_text(encoding="utf-8")

    def test_file_exists_and_is_small(self):
        # 40 lines until the strategy registered itself in window.customStrategies, gave
        # create suggestions and a clearer error view. There is still no build step.
        assert len(self._source().splitlines()) <= 80

    def test_no_dependencies_or_build_chain(self):
        source = self._source()
        assert "import " not in source.replace("// ", "")
        assert "require(" not in source

    def test_calls_the_websocket_command_the_integration_registers(self):
        assert f'"{_strategy().WS_TYPE}"' in self._source()

    def test_defines_the_strategy_element(self):
        assert "ll-strategy-givenergy-manager" in self._source()

    def test_url_path_is_under_the_integration_domain(self):
        s = _strategy()
        assert s.STRATEGY_URL_PATH == "/givenergy_inverter_manager/givenergy-manager-strategy.js"
        assert s.STRATEGY_FILE.name == s.STRATEGY_URL_PATH.rsplit("/", 1)[1]


_NODE_HARNESS = """
const fs = require("fs");
globalThis.HTMLElement = class {};
const defined = {};
globalThis.customElements = { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } };
globalThis.window = { customStrategies: [{ type: "someone-elses" }] };
const source = fs.readFileSync(process.argv[2], "utf8");
eval(source);
const afterFirstLoad = window.customStrategies.map((e) => e.type);
eval(source);
const afterSecondLoad = window.customStrategies.map((e) => e.type);
const Strategy = defined["ll-strategy-givenergy-manager"];
const calls = [];
const good = { callWS: async (msg) => { calls.push(msg); return { views: [{ title: "x", cards: [] }] }; } };
const failing = (err) => ({ callWS: async () => { throw err; } });
(async () => {
  const ok = await Strategy.generate({}, good);
  const failed = await Strategy.generate({}, failing({ code: "unknown_error", message: "boom" }));
  const unloaded = await Strategy.generate({}, failing({ code: "not_found", message: "not set up" }));
  const listed = window.customStrategies.find((e) => e.type === "givenergy-manager");
  console.log(JSON.stringify({
    names: Object.keys(defined), calls, ok, failedType: failed.views[0].cards[0].type,
    failedText: failed.views[0].cards[0].content,
    unloadedText: unloaded.views[0].cards[0].content,
    suggestions: Strategy.getCreateSuggestions({}), noEditor: Strategy.noEditor,
    afterFirstLoad, afterSecondLoad, listed,
  }));
})();
"""


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    harness = tmp_path_factory.mktemp("js") / "harness.js"
    harness.write_text(_NODE_HARNESS, encoding="utf-8")
    out = subprocess.run(
        ["node", str(harness), str(_strategy().STRATEGY_FILE)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(out.stdout)


def test_node_is_there_to_run_the_strategy_in_ci():
    """The node tests below skip without node. CI sets CI=true, and must not skip them quietly."""
    if os.environ.get("CI"):
        assert shutil.which("node") is not None, "install node in CI so the strategy JS is tested"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
class TestStrategyRunsUnderNode:

    def test_registers_both_element_names(self, result):
        assert set(result["names"]) == {
            "ll-strategy-givenergy-manager",
            "ll-strategy-dashboard-givenergy-manager",
        }

    def test_generate_returns_what_the_websocket_command_returns(self, result):
        assert result["calls"] == [{"type": _strategy().WS_TYPE}]
        assert result["ok"] == {"views": [{"title": "x", "cards": []}]}

    def test_generate_shows_a_markdown_card_when_the_command_fails(self, result):
        assert result["failedType"] == "markdown"
        assert "boom" in result["failedText"]

    def test_the_error_view_links_the_troubleshooting_page(self, result):
        assert "/docs/troubleshooting.md" in result["failedText"]

    def test_the_error_view_says_when_the_integration_is_not_loaded(self, result):
        assert "is not loaded" in result["unloadedText"]
        assert "not_found" not in result["unloadedText"]

    def test_generate_sends_no_field_but_the_type(self, result):
        assert all(set(call) == {"type"} for call in result["calls"])

    def test_it_suggests_a_title_and_an_icon_for_a_new_dashboard(self, result):
        assert result["suggestions"] == {"title": "GivEnergy", "icon": "mdi:solar-power-variant"}

    def test_it_is_listed_under_community_dashboards(self, result):
        assert result["listed"]["type"] == "givenergy-manager"
        assert result["listed"]["strategyType"] == "dashboard"
        assert result["listed"]["documentationURL"].endswith("/docs/dashboard.md")

    def test_registering_keeps_other_strategies_and_adds_ours_once(self, result):
        assert result["afterFirstLoad"] == ["someone-elses", "givenergy-manager"]
        assert result["afterSecondLoad"] == result["afterFirstLoad"]

    def test_it_has_no_config_editor(self, result):
        assert result["noEditor"] is True


def _loaded_entry(state=ConfigEntryState.LOADED, entry_id=ENTRY_ID):
    return SimpleNamespace(
        entry_id=entry_id,
        data=dict(FULL_CONFIG),
        options={},
        runtime_data=SimpleNamespace(ev_charger_brand=None),
        state=state,
    )


def _user(user_id, *, admin, system=False):
    return SimpleNamespace(id=user_id, is_admin=admin, system_generated=system)


class TestDashboardForWebsocket:
    def _run(self, entries, users=None, *, is_admin=True):
        users = [_user(ADMIN_ID, admin=True)] if users is None else users
        with fake_hass(FULL_CONFIG, FakeRegistry(enable_all=True)) as hass:
            hass.config_entries.async_entries.return_value = entries
            hass.data = {}
            hass.auth.async_get_users = AsyncMock(return_value=users)
            return asyncio.run(
                _strategy().async_dashboard_for_websocket(hass, is_admin=is_admin)
            )

    def _settings(self, result):
        return next((v for v in result["views"] if v["path"] == "settings"), None)

    def test_settings_view_is_visible_to_the_administrators_only(self):
        users = [
            _user("owner-id", admin=True),
            _user("child-id", admin=False),
            _user("supervisor-id", admin=True, system=True),
            _user("second-admin-id", admin=True),
        ]
        settings = self._settings(self._run([_loaded_entry()], users))
        assert settings["visible"] == [{"user": "owner-id"}, {"user": "second-admin-id"}]

    def test_a_viewer_who_is_not_an_administrator_gets_no_settings_view(self):
        result = self._run([_loaded_entry()], is_admin=False)
        assert self._settings(result) is None
        assert "'navigation_path': 'settings'" not in str(result)

    def test_a_viewer_who_is_not_an_administrator_gets_no_administrator_ids(self):
        users = [_user("owner-id", admin=True)]
        assert "owner-id" not in str(self._run([_loaded_entry()], users, is_admin=False))

    def test_no_settings_view_when_no_user_is_an_administrator(self):
        result = self._run([_loaded_entry()], [_user("child-id", admin=False)])
        assert self._settings(result) is None

    def test_returns_the_dashboard_dict(self):
        result = self._run([_loaded_entry()])
        assert result == dashboard_dict(ev_brand=None, resources=None)
        assert [v["path"] for v in result["views"]][:3] == ["power-flow", "today", "plan"]

    def test_none_without_a_config_entry(self):
        assert self._run([]) is None

    def test_none_while_the_entry_is_not_loaded(self):
        assert self._run([_loaded_entry(state=ConfigEntryState.NOT_LOADED)]) is None

    def test_uses_the_first_loaded_entry_like_the_action(self):
        result = self._run(
            [
                _loaded_entry(state=ConfigEntryState.NOT_LOADED, entry_id="other_entry"),
                _loaded_entry(),
            ]
        )
        assert result == dashboard_dict(ev_brand=None, resources=None)


class TestRegisterOnce:
    def test_registers_once_per_run(self, monkeypatch):
        from unittest.mock import MagicMock

        strategy = _strategy()
        websocket = MagicMock()
        served = MagicMock()

        async def serve(hass):
            served(hass)

        monkeypatch.setattr(strategy, "_register_websocket_command", websocket)
        monkeypatch.setattr(strategy, "_serve_strategy_file", serve)
        hass = SimpleNamespace(data={})

        asyncio.run(strategy.async_register_strategy(hass))
        asyncio.run(strategy.async_register_strategy(hass))

        assert websocket.call_count == 1
        assert served.call_count == 1


class _FakeDashboard:
    def __init__(self, mode, config=None, error=None):
        self.mode = mode
        self._config = config
        self._error = error

    async def async_load(self, force):
        if self._error:
            raise self._error
        return self._config


class _FakeBus:
    def __init__(self):
        self.fired = []

    def async_fire(self, event_type, data):
        self.fired.append((event_type, data))


def _hass_with_dashboards(monkeypatch, dashboards):
    import sys
    import types

    const = types.ModuleType("homeassistant.components.lovelace.const")
    const.LOVELACE_DATA = "lovelace"
    monkeypatch.setitem(sys.modules, "homeassistant.components.lovelace.const", const)
    return SimpleNamespace(
        data={"lovelace": SimpleNamespace(dashboards=dashboards)}, bus=_FakeBus()
    )


class TestNudgeDashboards:
    OURS = {"strategy": {"type": "custom:givenergy-manager"}}

    def test_only_storage_dashboards_that_name_the_strategy_are_told(self, monkeypatch):
        strategy = _strategy()
        hass = _hass_with_dashboards(
            monkeypatch,
            {
                "givenergy-auto": _FakeDashboard("storage", self.OURS),
                "other-strategy": _FakeDashboard(
                    "storage", {"strategy": {"type": "custom:something-else"}}
                ),
                "cards": _FakeDashboard("storage", {"views": []}),
                "from-yaml": _FakeDashboard("yaml", self.OURS),
                "unsaved": _FakeDashboard("storage", error=RuntimeError("no config")),
            },
        )

        told = asyncio.run(strategy.async_nudge_dashboards(hass))

        assert told == 1
        assert hass.bus.fired == [("lovelace_updated", {"url_path": "givenergy-auto"})]

    def test_a_second_call_in_the_same_run_tells_no_one(self, monkeypatch):
        strategy = _strategy()
        hass = _hass_with_dashboards(
            monkeypatch, {"givenergy-auto": _FakeDashboard("storage", self.OURS)}
        )

        asyncio.run(strategy.async_nudge_dashboards(hass))
        again = asyncio.run(strategy.async_nudge_dashboards(hass))

        assert again == 0
        assert len(hass.bus.fired) == 1

    def test_the_default_dashboard_is_told_with_no_url_path(self, monkeypatch):
        strategy = _strategy()
        hass = _hass_with_dashboards(monkeypatch, {None: _FakeDashboard("storage", self.OURS)})

        asyncio.run(strategy.async_nudge_dashboards(hass))

        assert hass.bus.fired == [("lovelace_updated", {"url_path": None})]

    def test_no_lovelace_data_tells_no_one_and_raises_nothing(self):
        strategy = _strategy()
        hass = SimpleNamespace(data={}, bus=_FakeBus())

        assert asyncio.run(strategy.async_nudge_dashboards(hass)) == 0
        assert hass.bus.fired == []
