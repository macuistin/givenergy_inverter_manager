"""Shared pieces of the SP3 spike: the throwaway wizard flows and the fixtures that register them.

Not collected as tests (the name has no `test_` prefix). The three `test_sp3_*` modules import
from here, which keeps each of them under the 500-line limit.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import frame
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
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


async def loaded_entry(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
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


class ReloadFlow(SetupFlow):
    """Reconfigure with the helper the brief says not to use: update, reload and abort."""

    async def async_step_reconfigure(self, user_input: dict | None = None) -> Any:
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry, data_updates={"host": user_input["host"]}
            )
        return self.async_show_form(
            step_id="reconfigure", data_schema=vol.Schema({vol.Required("host"): str})
        )
