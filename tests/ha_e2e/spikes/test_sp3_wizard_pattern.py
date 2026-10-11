"""Spike SP3: the wizard pattern against a real Home Assistant.

Questions (docs/design/spikes/SP3.md):

1. Does a checklist step with dynamic routing to later steps work in a config flow and in an
   options flow, with ``last_step`` set per form and nothing stored until a confirm step?
2. Does ``async_update_and_abort`` plus an update listener give exactly one reload, and what
   does Home Assistant log for the 2026.12 deprecation?

The flows below are throwaway handlers registered only inside these tests (domain
``sp3_wizard``). Nothing under custom_components/ is used or changed.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import frame
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

DOMAIN = "sp3_wizard"
PAGES = ["tariff", "hot_water", "battery"]
LIVE_KEYS = {"dry_run", "slider"}


def _checklist() -> SelectSelector:
    """A multi-select of page ids: what the frontend draws as a list of checkboxes."""
    return SelectSelector(
        SelectSelectorConfig(options=PAGES, multiple=True, mode=SelectSelectorMode.LIST)
    )


class _Wizard:
    """Routing shared by the setup flow and the options flow (plain values on the handler)."""

    _queue: list[str]
    _values: dict[str, Any]

    def _start(self, ticked: list[str]) -> None:
        # Keep the page order fixed whatever order the frontend sends the ticks in.
        self._queue = [p for p in PAGES if p in ticked]
        self._pages = len(self._queue)

    def _total(self) -> int:
        """The first screen, the ticked pages and the confirm step."""
        return 2 + self._pages

    async def _next(self) -> Any:
        """Go to the next ticked page, or to the confirm step when none is left."""
        if self._queue:
            return await getattr(self, f"async_step_{self._queue.pop(0)}")()
        return await self.async_step_confirm()

    # Page forms. Every one but the confirm step is last_step=False ("Next").
    async def async_step_tariff(self, user_input: dict | None = None) -> Any:
        if user_input is not None:
            self._values["base_rate"] = user_input["base_rate"]
            self._values["rate_count"] = int(user_input["rate_count"])
            if self._values["rate_count"] > 0:
                return await self.async_step_tariff_rates()
            return await self._next()
        schema = vol.Schema(
            {
                vol.Required("base_rate", default=0.3): vol.Coerce(float),
                vol.Required("rate_count", default="0"): SelectSelector(
                    SelectSelectorConfig(options=["0", "1", "2", "3"])
                ),
            }
        )
        return self.async_show_form(
            step_id="tariff",
            data_schema=schema,
            last_step=False,
            description_placeholders={"step": "2", "total": str(self._total())},
        )

    async def async_step_tariff_rates(self, user_input: dict | None = None) -> Any:
        """Exactly as many rows as the count says: the schema is built when the form is shown."""
        count = self._values["rate_count"]
        if user_input is not None:
            self._values["rates"] = [
                {"name": user_input[f"name_{i}"], "rate": user_input[f"rate_{i}"]}
                for i in range(count)
            ]
            return await self._next()
        fields: dict[Any, Any] = {}
        for i in range(count):
            fields[vol.Required(f"name_{i}", default=f"Rate {i + 1}")] = str
            fields[vol.Required(f"rate_{i}", default=0.2)] = vol.Coerce(float)
        return self.async_show_form(
            step_id="tariff_rates", data_schema=vol.Schema(fields), last_step=False
        )

    async def async_step_hot_water(self, user_input: dict | None = None) -> Any:
        if user_input is not None:
            self._values["immersion_switch"] = user_input.get("immersion_switch", "")
            return await self._next()
        schema = vol.Schema(
            {
                vol.Optional("immersion_switch"): EntitySelector(
                    EntitySelectorConfig(domain="switch")
                )
            }
        )
        return self.async_show_form(step_id="hot_water", data_schema=schema, last_step=False)

    async def async_step_battery(self, user_input: dict | None = None) -> Any:
        if user_input is not None:
            self._values["battery_capacity_kwh"] = user_input["battery_capacity_kwh"]
            return await self._next()
        schema = vol.Schema({vol.Required("battery_capacity_kwh", default=10.0): vol.Coerce(float)})
        return self.async_show_form(step_id="battery", data_schema=schema, last_step=False)


class SetupFlow(_Wizard, config_entries.ConfigFlow):
    """Config flow: checklist, routed pages, one write (the entry) at confirm."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> Any:
        return await self.async_step_system()

    async def async_step_system(self, user_input: dict | None = None) -> Any:
        if user_input is not None:
            self._values = {"serial": "ab1234g567"}
            self._start(user_input["pages"])
            return await self._next()
        schema = vol.Schema({vol.Required("pages", default=["tariff"]): _checklist()})
        return self.async_show_form(
            step_id="system",
            data_schema=schema,
            last_step=False,
            description_placeholders={"found": "Inverter ab1234g567", "step": "1", "total": "3"},
        )

    async def async_step_confirm(self, user_input: dict | None = None) -> Any:
        if user_input is not None:
            return self.async_create_entry(title="Wizard", data=self._values)
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            last_step=True,
            description_placeholders={"summary": ", ".join(sorted(self._values))},
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> OptionsWizard:
        return OptionsWizard()

    async def async_step_reconfigure(self, user_input: dict | None = None) -> Any:
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            return self.async_update_and_abort(entry, data_updates={"host": user_input["host"]})
        return self.async_show_form(
            step_id="reconfigure", data_schema=vol.Schema({vol.Required("host"): str})
        )


class OptionsWizard(_Wizard, config_entries.OptionsFlow):
    """Options flow: nothing cached in __init__, one read-modify-write at confirm."""

    async def async_step_init(self, user_input: dict | None = None) -> Any:
        if user_input is not None:
            self._values = {}
            self._start(user_input["pages"])
            if not self._queue:
                return self.async_abort(reason="nothing_to_change")
            return await self._next()
        schema = vol.Schema({vol.Required("pages", default=[]): _checklist()})
        return self.async_show_form(step_id="init", data_schema=schema, last_step=False)

    async def async_step_confirm(self, user_input: dict | None = None) -> Any:
        # The CURRENT options, read now, not when the flow opened.
        current = dict(self.config_entry.options)
        merged = {**current, **self._values}
        if user_input is not None:
            return self.async_create_entry(title="", data=merged)
        changed = [k for k, v in merged.items() if current.get(k) != v]
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            last_step=True,
            description_placeholders={"changes": ", ".join(sorted(changed)) or "nothing"},
        )


class StaleSnapshotOptionsWizard(OptionsWizard):
    """The v0.17.1 pattern: options copied when the flow is created. Kept as a control."""

    def __init__(self, options: dict) -> None:
        self._snapshot = dict(options)

    async def async_step_confirm(self, user_input: dict | None = None) -> Any:
        if user_input is not None:
            return self.async_create_entry(title="", data={**self._snapshot, **self._values})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}), last_step=True)


class Counters:
    """Setup and unload counts of the throwaway integration."""

    def __init__(self) -> None:
        self.setups = 0
        self.unloads = 0


@pytest.fixture
def counters() -> Counters:
    return Counters()


@pytest.fixture(autouse=True)
def _fresh_deprecation_log() -> Iterator[None]:
    """report_usage logs once per integration and message. Start each test with a clean set."""
    frame._REPORTED_INTEGRATIONS.clear()
    yield
    frame._REPORTED_INTEGRATIONS.clear()


def _register(hass: HomeAssistant, counters: Counters, with_listener: bool) -> Iterator[Counters]:
    """Register the throwaway integration and its flow handler, and remove both afterwards."""

    async def async_setup_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
        counters.setups += 1
        if with_listener:

            async def _on_update(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> None:
                # What the real integration's listener does: decide, then reload once.
                hass.config_entries.async_schedule_reload(entry.entry_id)

            entry.async_on_unload(entry.add_update_listener(_on_update))
        return True

    async def async_unload_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
        counters.unloads += 1
        return True

    mock_integration(
        hass,
        MockModule(
            DOMAIN, async_setup_entry=async_setup_entry, async_unload_entry=async_unload_entry
        ),
        built_in=False,
    )
    mock_platform(hass, f"{DOMAIN}.config_flow", None)
    with mock_config_flow(DOMAIN, SetupFlow):
        yield counters


@pytest.fixture
def wizard(hass: HomeAssistant, counters: Counters) -> Iterator[Counters]:
    """The integration registers an update listener, as givenergy_inverter_manager does."""
    yield from _register(hass, counters, with_listener=True)


@pytest.fixture
def wizard_without_listener(hass: HomeAssistant, counters: Counters) -> Iterator[Counters]:
    yield from _register(hass, counters, with_listener=False)


async def _loaded_entry(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"serial": "ab1234g567", "host": "old"},
        options=options or {"dry_run": True, "slider": 80, "base_rate": 0.3},
        unique_id="ab1234g567",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


# ---------------------------------------------------------------------------------------------
# 1. Config flow: checklist, routing, last_step, nothing stored until confirm
# ---------------------------------------------------------------------------------------------


async def test_config_flow_checklist_routes_only_to_ticked_pages(hass, wizard):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert (flow["type"], flow["step_id"], flow["last_step"]) == (
        FlowResultType.FORM,
        "system",
        False,
    )

    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {"pages": ["battery", "tariff"]},  # order from the client is ignored
    )
    assert (flow["step_id"], flow["last_step"]) == ("tariff", False)

    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"base_rate": 0.31, "rate_count": "0"}
    )
    # hot_water was not ticked, so the next page is battery, then the confirm step.
    assert (flow["step_id"], flow["last_step"]) == ("battery", False)

    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"battery_capacity_kwh": 9.5}
    )
    assert (flow["type"], flow["step_id"], flow["last_step"]) == (
        FlowResultType.FORM,
        "confirm",
        True,
    )
    assert flow["description_placeholders"]["summary"] == (
        "base_rate, battery_capacity_kwh, rate_count, serial"
    )

    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert flow["data"] == {
        "serial": "ab1234g567",
        "base_rate": 0.31,
        "rate_count": 0,
        "battery_capacity_kwh": 9.5,
    }


async def test_config_flow_with_nothing_ticked_goes_straight_to_confirm(hass, wizard):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"pages": []})
    assert (flow["step_id"], flow["last_step"]) == ("confirm", True)
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert flow["data"] == {"serial": "ab1234g567"}


async def test_config_flow_answer_decides_how_many_rate_rows_the_next_form_has(hass, wizard):
    """The count asked on the tariff form builds the next form's schema (rule 2 and 5)."""
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"pages": ["tariff"]})
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"base_rate": 0.3, "rate_count": "2"}
    )
    assert (flow["step_id"], flow["last_step"]) == ("tariff_rates", False)
    names = [f["name"] for f in cv.to_field_list(flow["data_schema"])]
    assert names == ["name_0", "rate_0", "name_1", "rate_1"]

    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {"name_0": "Night", "rate_0": 0.1, "name_1": "Peak", "rate_1": 0.4},
    )
    assert flow["step_id"] == "confirm"
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert flow["data"]["rates"] == [
        {"name": "Night", "rate": 0.1},
        {"name": "Peak", "rate": 0.4},
    ]


async def test_config_flow_stores_nothing_until_confirm(hass, wizard, hass_storage):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow_id = flow["flow_id"]
    for user_input in (
        {"pages": ["tariff", "hot_water", "battery"]},
        {"base_rate": 0.3, "rate_count": "0"},
        {},
        {"battery_capacity_kwh": 9.5},
    ):
        flow = await hass.config_entries.flow.async_configure(flow_id, user_input)
        # After every screen: no entry, nothing in the config entries store, no setup.
        assert hass.config_entries.async_entries(DOMAIN) == []
        stored = hass_storage.get("core.config_entries", {}).get("data", {}).get("entries", [])
        assert [e for e in stored if e["domain"] == DOMAIN] == []
    assert flow["step_id"] == "confirm"
    assert wizard.setups == 0

    # Walking away at the confirm step (the abort the frontend sends on close) leaves nothing.
    hass.config_entries.flow.async_abort(flow_id)
    assert hass.config_entries.async_entries(DOMAIN) == []
    assert wizard.setups == 0


async def test_config_flow_step_counts_are_recomputed_per_screen(hass, wizard):
    """'Step n of about m' comes from description_placeholders, so it can change per screen."""
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert flow["description_placeholders"]["total"] == "3"
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"pages": ["tariff", "hot_water", "battery"]}
    )
    assert flow["description_placeholders"] == {"step": "2", "total": "5"}


async def test_checklist_form_serialises_for_the_frontend_api(hass, wizard, hass_client):
    """The REST view the frontend uses returns last_step and a multi-select schema."""
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()
    response = await client.post("/api/config/config_entries/flow", json={"handler": DOMAIN})
    assert response.status == 200
    body = await response.json()
    assert body["type"] == "form"
    assert body["step_id"] == "system"
    assert body["last_step"] is False
    (field,) = body["data_schema"]
    assert field["name"] == "pages"
    assert field["selector"]["select"]["multiple"] is True
    assert field["selector"]["select"]["mode"] == "list"
    assert field["selector"]["select"]["options"] == PAGES

    response = await client.post(
        f"/api/config/config_entries/flow/{body['flow_id']}", json={"pages": ["tariff"]}
    )
    body = await response.json()
    assert (body["step_id"], body["last_step"]) == ("tariff", False)
    hass.config_entries.flow.async_abort(body["flow_id"])


# ---------------------------------------------------------------------------------------------
# 2. Options flow variant
# ---------------------------------------------------------------------------------------------


async def test_options_flow_routes_and_writes_once_at_confirm(hass, wizard):
    entry = await _loaded_entry(hass)
    real = hass.config_entries.async_update_entry
    with patch.object(hass.config_entries, "async_update_entry", wraps=real) as update:
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        assert (flow["step_id"], flow["last_step"]) == ("init", False)

        flow = await hass.config_entries.options.async_configure(
            flow["flow_id"], {"pages": ["hot_water", "battery"]}
        )
        assert flow["step_id"] == "hot_water"
        flow = await hass.config_entries.options.async_configure(
            flow["flow_id"], {"immersion_switch": "switch.heater"}
        )
        assert flow["step_id"] == "battery"
        flow = await hass.config_entries.options.async_configure(
            flow["flow_id"], {"battery_capacity_kwh": 12.0}
        )
        assert (flow["step_id"], flow["last_step"]) == ("confirm", True)
        assert flow["description_placeholders"]["changes"] == (
            "battery_capacity_kwh, immersion_switch"
        )
        # Three screens answered and the confirm form shown: still no write.
        assert update.call_count == 0
        assert dict(entry.options) == {"dry_run": True, "slider": 80, "base_rate": 0.3}

        flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
        await hass.async_block_till_done()
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert update.call_count == 1
    assert dict(entry.options) == {
        "dry_run": True,
        "slider": 80,
        "base_rate": 0.3,
        "immersion_switch": "switch.heater",
        "battery_capacity_kwh": 12.0,
    }


async def test_options_confirm_merges_the_current_options_not_a_copy_from_flow_start(hass, wizard):
    """A live key moved while the wizard is open survives. Reads at confirm, never in __init__."""
    entry = await _loaded_entry(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"pages": ["battery"]}
    )
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"battery_capacity_kwh": 12.0}
    )

    # Meanwhile: dashboard control moved, dry run toggled.
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "slider": 95, "dry_run": False}
    )
    await hass.async_block_till_done()
    wizard.setups = wizard.unloads = 0

    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["slider"] == 95
    assert entry.options["dry_run"] is False
    assert entry.options["battery_capacity_kwh"] == 12.0


async def test_control_a_flow_that_copies_options_at_creation_overwrites_a_live_change(
    hass, wizard
):
    """Documents the v0.17.1 hazard (`self._options = dict(config_entry.options)` in __init__)."""
    entry = await _loaded_entry(hass)
    with patch.object(
        SetupFlow,
        "async_get_options_flow",
        staticmethod(lambda e: StaleSnapshotOptionsWizard(dict(e.options))),
    ):
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        flow = await hass.config_entries.options.async_configure(
            flow["flow_id"], {"pages": ["battery"]}
        )
        flow = await hass.config_entries.options.async_configure(
            flow["flow_id"], {"battery_capacity_kwh": 12.0}
        )
        hass.config_entries.async_update_entry(entry, options={**entry.options, "slider": 95})
        flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["slider"] == 80  # the live change was lost


async def test_options_flow_nothing_ticked_aborts_without_a_write(hass, wizard):
    entry = await _loaded_entry(hass)
    real = hass.config_entries.async_update_entry
    with patch.object(hass.config_entries, "async_update_entry", wraps=real) as update:
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"pages": []})
    assert flow["type"] is FlowResultType.ABORT
    assert update.call_count == 0


async def test_options_confirm_without_changes_does_not_notify_the_listener(hass, wizard):
    """An unchanged write returns False in async_update_entry, so no listener and no reload."""
    entry = await _loaded_entry(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"pages": ["tariff"]})
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"base_rate": 0.3, "rate_count": "0"}
    )
    wizard.setups = wizard.unloads = 0
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()
    # rate_count is new, so the options did change here: one reload, not two.
    assert (wizard.unloads, wizard.setups) == (1, 1)

    # Same answers again: the merged options equal the stored ones.
    wizard.setups = wizard.unloads = 0
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"pages": ["tariff"]})
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"base_rate": 0.3, "rate_count": "0"}
    )
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert (wizard.unloads, wizard.setups) == (0, 0)


async def test_options_flow_with_reload_class_refuses_an_entry_with_update_listeners(hass, wizard):
    """OptionsFlowWithReload is not an option for an integration that keeps its listener."""

    class AutoReloadOptions(config_entries.OptionsFlowWithReload):
        async def async_step_init(self, user_input: dict | None = None) -> Any:
            if user_input is not None:
                return self.async_create_entry(title="", data={"x": 1})
            return self.async_show_form(step_id="init", data_schema=vol.Schema({}))

    entry = await _loaded_entry(hass)
    assert entry.update_listeners
    with patch.object(
        SetupFlow, "async_get_options_flow", staticmethod(lambda e: AutoReloadOptions())
    ):
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        with pytest.raises(ValueError, match="update listeners should not be used"):
            await hass.config_entries.options.async_configure(flow["flow_id"], {})


# ---------------------------------------------------------------------------------------------
# 3. async_update_and_abort with an update listener
# ---------------------------------------------------------------------------------------------

DEPRECATION = "has an update listener and should use it for scheduling a reload"


async def _reconfigure(hass: HomeAssistant, entry: MockConfigEntry, host: str) -> dict:
    flow = await entry.start_reconfigure_flow(hass)
    assert flow["step_id"] == "reconfigure"
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"host": host})
    await hass.async_block_till_done()
    return flow


async def test_update_and_abort_with_a_listener_reloads_once_and_logs_nothing(hass, wizard, caplog):
    entry = await _loaded_entry(hass)
    caplog.set_level(logging.DEBUG)
    flow = await _reconfigure(hass, entry, "new")
    assert flow["type"] is FlowResultType.ABORT
    assert flow["reason"] == "reconfigure_successful"
    assert entry.data["host"] == "new"
    assert (wizard.unloads, wizard.setups) == (1, 2)  # one reload (setup ran once before)
    assert DEPRECATION not in caplog.text
    assert "2026.12" not in caplog.text


async def test_update_and_abort_without_a_listener_does_not_reload(hass, wizard_without_listener):
    entry = await _loaded_entry(hass)
    await _reconfigure(hass, entry, "new")
    assert entry.data["host"] == "new"
    assert (wizard_without_listener.unloads, wizard_without_listener.setups) == (0, 1)


async def test_update_and_abort_with_unchanged_data_does_not_notify_the_listener(hass, wizard):
    entry = await _loaded_entry(hass)
    await _reconfigure(hass, entry, "old")
    assert (wizard.unloads, wizard.setups) == (0, 1)


async def test_update_reload_and_abort_with_a_listener_logs_the_2026_12_deprecation(
    hass, wizard, caplog
):
    """What the brief says not to do: the helper plus a listener. Measures the log and reloads."""

    class ReloadFlow(SetupFlow):
        async def async_step_reconfigure(self, user_input: dict | None = None) -> Any:
            entry = self._get_reconfigure_entry()
            if user_input is not None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={"host": user_input["host"]}
                )
            return self.async_show_form(
                step_id="reconfigure", data_schema=vol.Schema({vol.Required("host"): str})
            )

    entry = await _loaded_entry(hass)
    caplog.set_level(logging.DEBUG)
    with mock_config_flow(DOMAIN, ReloadFlow):
        flow = await _reconfigure(hass, entry, "new")
    assert flow["reason"] == "reconfigure_successful"

    records = [r for r in caplog.records if DEPRECATION in r.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert records[0].levelno == logging.WARNING
    assert f"Detected that custom integration '{DOMAIN}' {DEPRECATION}." in message
    assert "This will stop working in Home Assistant 2026.12.0" in message
    # The listener reloads and so does the helper: two reloads for one change.
    assert wizard.unloads == 2
    assert wizard.setups == 3


async def test_the_deprecation_is_logged_once_per_run_for_an_integration(hass, wizard, caplog):
    class ReloadFlow(SetupFlow):
        async def async_step_reconfigure(self, user_input: dict | None = None) -> Any:
            entry = self._get_reconfigure_entry()
            if user_input is not None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={"host": user_input["host"]}
                )
            return self.async_show_form(
                step_id="reconfigure", data_schema=vol.Schema({vol.Required("host"): str})
            )

    entry = await _loaded_entry(hass)
    with mock_config_flow(DOMAIN, ReloadFlow):
        await _reconfigure(hass, entry, "a")
        await _reconfigure(hass, entry, "b")
    assert sum(DEPRECATION in r.getMessage() for r in caplog.records) == 1


def test_the_throwaway_handler_is_gone_after_the_fixture():
    """The handler is registered per test and never leaks into the real HANDLERS table."""
    assert DOMAIN not in config_entries.HANDLERS
