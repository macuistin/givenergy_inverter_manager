"""
Tests for the dashboard strategy shim (strategy.py and frontend/givenergy-manager-strategy.js).

The websocket command, the static file route and the frontend module URL are
exercised against a real Home Assistant in tests/ha_e2e/test_dashboard_strategy_e2e.py.
The JavaScript is run under node when node is installed.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState

from tests.dashboard_support import ENTRY_ID, FULL_CONFIG, FakeRegistry, fake_hass


def _strategy():
    from custom_components.givenergy_inverter_manager import strategy

    return strategy


class TestStrategyFile:
    def _source(self) -> str:
        return _strategy().STRATEGY_FILE.read_text(encoding="utf-8")

    def test_file_exists_and_is_small(self):
        assert len(self._source().splitlines()) <= 40

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
eval(fs.readFileSync(process.argv[2], "utf8"));
const Strategy = defined["ll-strategy-givenergy-manager"];
const calls = [];
const good = { callWS: async (msg) => { calls.push(msg); return { views: [{ title: "x", cards: [] }] }; } };
const bad = { callWS: async () => { throw { code: "not_found", message: "not set up" }; } };
(async () => {
  const ok = await Strategy.generate({}, good);
  const failed = await Strategy.generate({}, bad);
  console.log(JSON.stringify({
    names: Object.keys(defined), calls, ok, failedType: failed.views[0].cards[0].type,
    failedText: failed.views[0].cards[0].content,
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
        assert "not set up" in result["failedText"]


def _loaded_entry(state=ConfigEntryState.LOADED, entry_id=ENTRY_ID):
    return SimpleNamespace(
        entry_id=entry_id,
        data=dict(FULL_CONFIG),
        options={},
        runtime_data=SimpleNamespace(ev_charger_brand=None),
        state=state,
    )


class TestDashboardForWebsocket:
    def _run(self, entries):
        with fake_hass(FULL_CONFIG, FakeRegistry(enable_all=True)) as hass:
            hass.config_entries.async_entries.return_value = entries
            hass.data = {}
            return asyncio.run(_strategy().async_dashboard_for_websocket(hass))

    def test_returns_the_dashboard_dict(self):
        from custom_components.givenergy_inverter_manager.dashboard_builder import (
            build_dashboard,
        )

        result = self._run([_loaded_entry()])
        with fake_hass(FULL_CONFIG, FakeRegistry(enable_all=True)) as hass:
            hass.config_entries.async_entries.return_value = [_loaded_entry()]
            expected = build_dashboard(hass, ENTRY_ID)
        assert result == expected
        assert [v["path"] for v in result["views"]][:3] == ["power-flow", "today", "bill"]

    def test_none_without_a_config_entry(self):
        assert self._run([]) is None

    def test_none_while_the_entry_is_not_loaded(self):
        assert self._run([_loaded_entry(state=ConfigEntryState.NOT_LOADED)]) is None

    def test_uses_the_first_loaded_entry_like_the_action(self):
        from custom_components.givenergy_inverter_manager.dashboard_builder import (
            build_dashboard,
        )

        result = self._run(
            [
                _loaded_entry(state=ConfigEntryState.NOT_LOADED, entry_id="other_entry"),
                _loaded_entry(),
            ]
        )
        with fake_hass(FULL_CONFIG, FakeRegistry(enable_all=True)) as hass:
            hass.config_entries.async_entries.return_value = [_loaded_entry()]
            expected = build_dashboard(hass, ENTRY_ID)
        assert result == expected


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
