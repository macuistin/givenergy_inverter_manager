"""A tariff chosen from the store follows its newer revisions, in a real Home Assistant.

The store is a small folder read through the real store client. No network is used.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from conftest import MIDDAY, SERIAL, full_config_data
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager import repairs, shadow_ranker, tariff_updater
from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.core.wizard_store import choose_tariff
from custom_components.givenergy_inverter_manager.lib.tariffstore import (
    FolderCache,
    Store,
    folder_reader,
)
from custom_components.givenergy_inverter_manager.tariff_store import TariffStoreAccess
from tests.lib.tariffstore.building import build_store
from tests.lib.tariffstore.fixtures import tariff, write_store

TODAY = date(2026, 6, 15)
FOLLOWING = {
    "kind": "store",
    "country": "IE",
    "provider": "p",
    "tariff": "plan",
    "area": "urban",
    "name": "Plan (Urban)",
    "provider_name": "P Energy",
    "effective_from": "2026-01-01",
    "auto_update": True,
}
NEW_RATES = {"Day": "0.4", "Night": "0.2"}


@pytest.fixture
def scenario():
    return MIDDAY


def _areas(rates: dict[str, str]) -> dict:
    return {"urban": {"label": "Urban", "standing": "1", "rates": rates}}


def _store(hass, tmp_path: Path, files: dict[str, dict]) -> TariffStoreAccess:
    folder = write_store(tmp_path, files)
    build_store(folder)
    return TariffStoreAccess(hass, Store(folder_reader(folder), FolderCache(tmp_path / "cache")))


def _revisions(second_start: str = "2026-06-01") -> dict[str, dict]:
    first = tariff(effective_from="2026-01-01", effective_to=second_start)
    first["areas"] = _areas({"Day": "0.3", "Night": "0.15"})
    second = tariff(effective_from=second_start)
    second["areas"] = _areas(NEW_RATES)
    return {"p/plan/1.json": first, "p/plan/2.json": second}


async def _loaded(hass, monkeypatch, source: dict | None, store: TariffStoreAccess):
    """A loaded entry that follows *source*, its saved rates those of the first revision."""
    monkeypatch.setattr(tariff_updater, "TariffStoreAccess", lambda _hass: store)
    monkeypatch.setattr(shadow_ranker, "TariffStoreAccess", lambda _hass: store)
    options = {}
    if source:
        first = await store.async_definition("IE", "p", "plan", date(2026, 1, 15), "urban")
        options = {**choose_tariff(first, 1).options, "tariff_source": source}
    entry = MockConfigEntry(
        domain=DOMAIN, data=full_config_data(), options=options, unique_id=SERIAL, version=1
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


def _issue(hass, issue_id: str):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def test_a_newer_revision_in_force_is_applied_whole(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    store = _store(hass, tmp_path, _revisions())
    notices = []
    monkeypatch.setattr(
        persistent_notification,
        "async_create",
        lambda _hass, message, **kwargs: notices.append((message, kwargs)),
    )
    entry = await _loaded(hass, monkeypatch, FOLLOWING, store)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED

    assert entry.options["base_rate"] == 0.4
    assert entry.options["standing_charge_per_day"] == 1.0
    assert entry.options["tariff_source"]["effective_from"] == "2026-06-01"
    assert entry.options["tariff_source"]["previous"]["options"]["base_rate"] == 0.3
    assert len(notices) == 1
    assert notices[0][1]["title"] == "Tariff prices updated"
    assert "new prices from 2026-06-01" in notices[0][0]


async def test_a_revision_that_has_not_started_changes_nothing(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    store = _store(hass, tmp_path, _revisions(second_start="2026-07-01"))
    entry = await _loaded(hass, monkeypatch, FOLLOWING, store)

    assert entry.options["base_rate"] == 0.3
    assert entry.options["tariff_source"]["effective_from"] == "2026-01-01"


async def test_with_updates_off_a_repair_offers_the_new_revision(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    store = _store(hass, tmp_path, _revisions())
    entry = await _loaded(hass, monkeypatch, {**FOLLOWING, "auto_update": False}, store)

    assert entry.options["base_rate"] == 0.3
    issue = _issue(hass, repairs.ISSUE_TARIFF_UPDATE_AVAILABLE)
    assert issue is not None
    assert issue.translation_placeholders == {"name": "P Energy Plan (Urban)", "start": "2026-06-01"}


async def test_a_tariff_the_store_dropped_raises_a_repair_and_keeps_the_rates(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    store = _store(hass, tmp_path, _revisions())
    entry = await _loaded(hass, monkeypatch, {**FOLLOWING, "tariff": "gone"}, store)

    assert entry.options["base_rate"] == 0.3
    assert _issue(hass, repairs.ISSUE_TARIFF_NEEDS_ATTENTION) is not None


async def test_an_unreadable_store_changes_nothing_and_raises_nothing(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    store = _store(hass, tmp_path, _revisions())
    entry = await _loaded(hass, monkeypatch, FOLLOWING, store)
    flaky = TariffStoreAccess(hass, Store(_unreadable, FolderCache(tmp_path / "empty")))

    assert await tariff_updater.async_check_tariff(hass, entry, flaky, TODAY) is None
    assert _issue(hass, repairs.ISSUE_TARIFF_NEEDS_ATTENTION) is None


async def test_a_hand_entered_tariff_is_left_alone(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    store = _store(hass, tmp_path, _revisions())
    entry = await _loaded(hass, monkeypatch, None, store)

    assert await tariff_updater.async_check_tariff(hass, entry, store, TODAY) is None
    assert "tariff_source" not in entry.options


def _unreadable(path: str) -> bytes:
    raise OSError("offline")


async def test_the_plans_of_the_store_are_ranked_against_the_followed_tariff(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    """The ranking is worked out at start-up and read by the Tariff Rank sensors."""
    store = _store(hass, tmp_path, _revisions(second_start="2026-07-01"))
    entry = await _loaded(hass, monkeypatch, FOLLOWING, store)
    assert entry.runtime_data.ranker.ranking is not None
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    states = {s.attributes.get("friendly_name"): s for s in hass.states.async_all("sensor")}
    rank = next(s for n, s in states.items() if n and n.endswith("Tariff Rank"))
    assert rank.state == "1"
    assert rank.attributes["plans_compared"] == 1
    assert rank.attributes["ranking"][0]["yours"] is True
    saving = next(s for n, s in states.items() if n and n.endswith("Cheapest Plan Saving"))
    assert float(saving.state) == 0
