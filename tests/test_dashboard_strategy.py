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
        # create suggestions and a clearer error view, then the recovery from Home Assistant's
        # 5-second timeout, the wait for the command after a restart, a record of when the
        # script ran and the watch that defines the elements again in Home Assistant's new
        # registry. There is still no build step.
        assert len(self._source().splitlines()) <= 160

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
// Home Assistant's own script replaces window.customElements with a registry that starts empty.
const replacementDefined = {};
const replacement = {
  get: (n) => replacementDefined[n],
  define: (n, c) => { if (replacementDefined[n]) throw new Error("already defined"); replacementDefined[n] = c; },
};
const definedBeforeTheReplacement = Object.keys(defined);
globalThis.customElements = replacement;
const calls = [];
const good = { callWS: async (msg) => { calls.push(msg); return { views: [{ title: "x", cards: [] }] }; } };
const failing = (err) => ({ callWS: async () => { throw err; } });
(async () => {
  Strategy.retryForMs = 0;
  const ok = await Strategy.generate({}, good);
  const failed = await Strategy.generate({}, failing({ code: "unknown_error", message: "boom" }));
  const unloaded = await Strategy.generate({}, failing({ code: "not_found", message: "not set up" }));
  const listed = window.customStrategies.find((e) => e.type === "givenergy-manager");
  Strategy.retryEveryMs = 1;
  Strategy.retryForMs = 5000;
  let attempts = 0;
  const slowStart = { callWS: async () => {
    attempts += 1;
    if (attempts < 4) throw { code: attempts % 2 ? "unknown_command" : "not_found", message: "not yet" };
    return { views: [{ title: "ready" }] };
  } };
  const afterRetries = await Strategy.generate({}, slowStart);
  let otherCalls = 0;
  const otherFailure = await Strategy.generate({}, { callWS: async () => { otherCalls += 1; throw { code: "unknown_error", message: "boom" }; } });
  Strategy.retryForMs = 30;
  let neverReadyCalls = 0;
  const neverReady = await Strategy.generate({}, { callWS: async () => { neverReadyCalls += 1; throw { code: "unknown_command", message: "Unknown command." }; } });
  const retries = { afterRetries, attempts, otherCalls, otherText: otherFailure.views[0].cards[0].content, neverReadyCalls, neverReadyText: neverReady.views[0].cards[0].content };
  const text = (value) => ({ nodeType: 3, nodeValue: value, childNodes: [] });
  const element = (children, shadow) => ({ nodeType: 1, childNodes: children, shadowRoot: shadow });
  const page = (message) => element([element([], element([text(message)]))]);
  const rebuilt = [];
  const rebuild = () => rebuilt.push(1);
  const recover = (root) => Strategy.recoverIfTimedOut(root, rebuild);
  const recovery = {
    inShadowRoot: recover(page("Error: Timeout waiting for strategy element ll-strategy-dashboard-givenergy-manager to be registered")),
    legacyName: recover(page("Timeout waiting for strategy element ll-strategy-givenergy-manager to be registered")),
    otherStrategy: recover(page("Timeout waiting for strategy element ll-strategy-dashboard-maintenance-supporter to be registered")),
    healthyPage: recover(page("Battery 100%")),
    emptyPage: recover(element([])),
    noPage: recover(null),
    hugePage: recover(element(Array.from({ length: 20000 }, () => text("nothing here")))),
    rebuildCalls: rebuilt.length,
  };
  await new Promise((resolve) => setTimeout(resolve, 450));
  const registry = {
    definedBeforeTheReplacement,
    definedAfterTheReplacement: Object.keys(replacementDefined),
    sameClassWorks: typeof replacementDefined["ll-strategy-dashboard-givenergy-manager"].generate,
    trace: window.givenergyManagerStrategy,
  };
  console.log(JSON.stringify({
    registry, recovery, retries,
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

    def test_it_defines_its_elements_again_in_the_registry_that_replaces_the_first(self, result):
        """Home Assistant swaps window.customElements for an empty registry, and a definition
        made before the swap is in the old one, which nothing asks. That timed the dashboard out
        with "Timeout waiting for strategy element", whatever else was true."""
        registry = result["registry"]
        assert set(registry["definedBeforeTheReplacement"]) == {
            "ll-strategy-dashboard-givenergy-manager",
            "ll-strategy-givenergy-manager",
        }
        assert set(registry["definedAfterTheReplacement"]) == set(
            registry["definedBeforeTheReplacement"]
        )
        assert registry["sameClassWorks"] == "function"

    def test_the_trace_shows_that_it_had_to_define_them_again(self, result):
        trace = result["registry"]["trace"]
        assert set(trace["defined"]) == {
            "ll-strategy-dashboard-givenergy-manager",
            "ll-strategy-givenergy-manager",
        }
        assert len(trace["definedAtMs"]) == len(trace["defined"])
        assert trace["errors"] == []

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

    def test_it_asks_for_a_rebuild_when_the_page_shows_the_timeout_for_its_strategy(self, result):
        recovery = result["recovery"]
        assert recovery["inShadowRoot"] is True
        assert recovery["legacyName"] is True

    def test_it_leaves_other_pages_and_other_strategies_alone(self, result):
        recovery = result["recovery"]
        assert not recovery["otherStrategy"]
        assert not recovery["healthyPage"]
        assert not recovery["emptyPage"]
        assert not recovery["noPage"]
        assert recovery["rebuildCalls"] == 2

    def test_the_search_stops_on_a_huge_page(self, result):
        assert result["recovery"]["hugePage"] is False

    def test_it_asks_again_while_the_command_is_not_ready_and_builds_when_it_is(self, result):
        retries = result["retries"]
        assert retries["afterRetries"] == {"views": [{"title": "ready"}]}
        assert retries["attempts"] == 4

    def test_it_does_not_retry_an_error_that_waiting_will_not_fix(self, result):
        retries = result["retries"]
        assert retries["otherCalls"] == 1
        assert "boom" in retries["otherText"]

    def test_it_gives_up_with_the_error_view_when_it_never_becomes_ready(self, result):
        retries = result["retries"]
        assert retries["neverReadyCalls"] > 1
        assert "Unknown command" in retries["neverReadyText"]

    def test_the_recovery_is_skipped_where_there_is_no_page(self, result):
        # The harness has no document, so loading the script scheduled nothing and raised nothing.
        assert "ll-strategy-givenergy-manager" in result["names"]


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


class TestModuleUrl:
    def test_the_address_carries_the_version_and_nothing_else(self):
        strategy = _strategy()

        url = strategy.strategy_module_url(SimpleNamespace(data={}))

        assert url == f"{strategy.STRATEGY_URL_PATH}?v={strategy.INTEGRATION_VERSION}"

    def test_the_address_is_the_same_at_every_start(self):
        strategy = _strategy()

        first = strategy.strategy_module_url(SimpleNamespace(data={}))
        second = strategy.strategy_module_url(SimpleNamespace(data={}))

        assert first == second


class _Resources:
    """A stored Lovelace resource collection, as far as the integration uses it."""

    def __init__(self, items=None):
        self.items = list(items or [])
        self.created = []
        self.deleted = []
        self.info_calls = 0

    async def async_get_info(self):
        self.info_calls += 1
        return {"resources": len(self.items)}

    def async_items(self):
        return self.items

    async def async_create_item(self, data):
        item = {"id": f"id{len(self.items) + 1}", "type": data["res_type"], "url": data["url"]}
        self.items.append(item)
        self.created.append(data)
        return item

    async def async_delete_item(self, item_id):
        self.items = [i for i in self.items if i["id"] != item_id]
        self.deleted.append(item_id)


def _lovelace(resources):
    return SimpleNamespace(data={"lovelace": SimpleNamespace(resources=resources)})


def _item(item_id, url, kind="module"):
    return {"id": item_id, "type": kind, "url": url}


class TestTheResource:
    """The script is a Lovelace resource too, so a page served before setup still loads it."""

    def _url(self, strategy):
        return strategy.strategy_module_url(SimpleNamespace(data={}))

    def test_it_is_created_as_a_module_at_this_releases_address(self):
        strategy = _strategy()
        resources = _Resources()

        asyncio.run(strategy.async_sync_resource(_lovelace(resources)))

        assert resources.created == [{"res_type": "module", "url": self._url(strategy)}]

    def test_a_second_run_adds_nothing(self):
        strategy = _strategy()
        resources = _Resources()
        hass = _lovelace(resources)

        asyncio.run(strategy.async_sync_resource(hass))
        asyncio.run(strategy.async_sync_resource(hass))

        assert len(resources.created) == 1
        assert resources.deleted == []

    def test_a_resource_of_an_older_release_is_replaced_not_added_to(self):
        strategy = _strategy()
        old = _item("old", f"{strategy.STRATEGY_URL_PATH}?v=0.1.0&boot=1")
        resources = _Resources([old])

        asyncio.run(strategy.async_sync_resource(_lovelace(resources)))

        assert resources.deleted == ["old"]
        assert [i["url"] for i in resources.items] == [self._url(strategy)]

    def test_duplicates_are_cleared_and_one_stays(self):
        strategy = _strategy()
        url = self._url(strategy)
        resources = _Resources([_item("a", url), _item("b", url)])

        asyncio.run(strategy.async_sync_resource(_lovelace(resources)))

        assert resources.deleted == ["b"]
        assert resources.created == []

    def test_a_resource_of_the_right_address_but_the_wrong_type_is_replaced(self):
        strategy = _strategy()
        resources = _Resources([_item("a", self._url(strategy), kind="js")])

        asyncio.run(strategy.async_sync_resource(_lovelace(resources)))

        assert resources.deleted == ["a"]
        assert [i["type"] for i in resources.items] == ["module"]

    def test_other_resources_are_left_alone(self):
        strategy = _strategy()
        hacs = _item("hacs", "/hacsfiles/apexcharts-card/apexcharts-card.js?hacstag=1")
        near = _item("near", "/givenergy_inverter_manager/other.js")
        resources = _Resources([hacs, near])

        asyncio.run(strategy.async_sync_resource(_lovelace(resources)))

        assert resources.deleted == []
        assert {hacs["id"], near["id"]} <= {i["id"] for i in resources.items}

    def test_the_collection_is_loaded_before_it_is_read(self):
        strategy = _strategy()
        resources = _Resources()

        asyncio.run(strategy.async_sync_resource(_lovelace(resources)))

        assert resources.info_calls == 1

    def test_nothing_is_written_to_yaml_resources(self):
        strategy = _strategy()
        yaml_resources = SimpleNamespace(
            data=[], async_get_info=lambda: None, async_items=lambda: []
        )

        asyncio.run(strategy.async_sync_resource(_lovelace(yaml_resources)))

        assert yaml_resources.data == []

    def test_it_does_nothing_when_lovelace_is_not_set_up(self):
        strategy = _strategy()

        asyncio.run(strategy.async_sync_resource(SimpleNamespace(data={})))

    def test_a_failure_is_logged_and_never_raised(self, caplog):
        strategy = _strategy()
        resources = _Resources()

        async def boom(_data):
            raise RuntimeError("storage is read only")

        resources.async_create_item = boom

        asyncio.run(strategy.async_sync_resource(_lovelace(resources)))

        assert "storage is read only" in caplog.text

    def test_removing_takes_every_copy_out_and_nothing_else(self):
        strategy = _strategy()
        hacs = _item("hacs", "/hacsfiles/card-mod/card-mod.js")
        resources = _Resources(
            [_item("a", self._url(strategy)), hacs, _item("b", f"{strategy.STRATEGY_URL_PATH}?v=1")]
        )

        asyncio.run(strategy.async_remove_resource(_lovelace(resources)))

        assert resources.items == [hacs]

    def test_registering_the_strategy_syncs_the_resource_once(self, monkeypatch):
        strategy = _strategy()
        resources = _Resources()
        hass = _lovelace(resources)
        monkeypatch.setattr(strategy, "_register_websocket_command", lambda hass: None)

        async def serve(hass):
            return None

        monkeypatch.setattr(strategy, "_serve_strategy_file", serve)

        asyncio.run(strategy.async_register_strategy(hass))
        asyncio.run(strategy.async_register_strategy(hass))

        assert len(resources.created) == 1
