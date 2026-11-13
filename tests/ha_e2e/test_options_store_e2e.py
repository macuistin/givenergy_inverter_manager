"""Configure's Tariff source page against a real flow manager: choosing a plan from the list,
stopping following the store, and what a hand edit does to a tariff
that follows the store.

The store is a small folder read through the real store client. No network is used.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import MIDDAY, SERIAL, full_config_data
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from wizard_support import choose, submit

from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.lib.tariffstore import (
    FolderCache,
    Store,
    folder_reader,
)
from custom_components.givenergy_inverter_manager.tariff_store import TariffStoreAccess
from custom_components.givenergy_inverter_manager.wizard import store_steps
from tests.lib.tariffstore.building import build_store
from tests.lib.tariffstore.fixtures import tariff, write_store

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


@pytest.fixture
def scenario():
    return MIDDAY


def _entry(source: dict | None = None) -> MockConfigEntry:
    data = {**full_config_data(), **({"tariff_source": source} if source else {})}
    return MockConfigEntry(
        domain=DOMAIN, title="GivEnergy Inverter Manager", data=data, unique_id=SERIAL, version=1
    )


def _use_store(monkeypatch, hass, tmp_path: Path, reader=None) -> None:
    folder = write_store(tmp_path, {"p/plan/1.json": tariff(effective_from="2026-01-01")})
    build_store(folder)
    store = Store(reader or folder_reader(folder), FolderCache(tmp_path / "cache"))
    monkeypatch.setattr(
        store_steps, "TariffStoreAccess", lambda _hass: TariffStoreAccess(hass, store)
    )


async def _tariff_source(hass, entry):
    manager = hass.config_entries.options
    result = await manager.async_init(entry.entry_id)
    result = await choose(manager, result, "tariff_menu")
    return manager, await choose(manager, result, "tariff_source")


async def _save(manager, result):
    """From the tariff menu, open Save changes and confirm. Returns the confirm text and result."""
    result = await choose(manager, result, "init")
    result = await choose(manager, result, "confirm")
    text = result["description_placeholders"]["changes"]
    return text, await manager.async_configure(result["flow_id"], user_input={})


async def test_a_plan_chosen_in_configure_replaces_the_rates_and_records_its_source(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    _use_store(monkeypatch, hass, tmp_path)
    entry = _entry()
    entry.add_to_hass(hass)

    manager, result = await _tariff_source(hass, entry)
    assert result["menu_options"] == ["store_country", "tariff_menu"]
    result = await choose(manager, result, "store_country")
    for pick in (
        {"country": "IE"},
        {"provider": "p"},
        {"tariff": "plan"},
        {"area": "rural"},
        {"bill_start_day": 5},
    ):
        result = await submit(manager, result, **pick)
    assert result["step_id"] == "tariff_menu"
    assert "Tariff source: P Energy Plan (Rural), prices from 2026-01-01, from the store" in (
        result["description_placeholders"]["source"]
    )

    text, saved = await _save(manager, result)
    assert "Tariff source: Entered by hand to P Energy Plan (Rural)" in text
    assert "Base rate name: " in text or "Base rate:" in text
    assert saved["type"] is FlowResultType.CREATE_ENTRY
    options = saved["data"]
    assert options["base_rate"] == 0.32
    assert options["standing_charge_per_day"] == 1.1
    assert options["vat_included"] is True
    assert options["bill_start_day"] == 5
    assert options["tariff_source"]["area"] == "rural"
    assert options["tariff_source"]["kind"] == "store"


async def test_stopping_following_the_store_keeps_the_rates_and_marks_it_edited(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    _use_store(monkeypatch, hass, tmp_path)
    entry = _entry(FOLLOWING)
    entry.add_to_hass(hass)

    manager, result = await _tariff_source(hass, entry)
    assert result["menu_options"] == [
        "store_country",
        "store_updates_off",
        "store_detach",
        "tariff_menu",
    ]
    result = await choose(manager, result, "store_detach")
    text, saved = await _save(manager, result)

    assert "then edited by hand" in text
    assert saved["data"]["tariff_source"]["kind"] == "based_on"
    assert saved["data"]["tariff_source"]["area"] == "urban"
    assert "base_rate" not in saved["data"]  # the rates are the ones already saved


async def test_editing_a_rate_on_a_tariff_that_follows_the_store_detaches_it(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    _use_store(monkeypatch, hass, tmp_path)
    entry = _entry(FOLLOWING)
    entry.add_to_hass(hass)

    manager, result = await _tariff_source(hass, entry)
    assert "Changing a rate or a bill figure here detaches it" in (
        result["description_placeholders"]["source"]
    )
    result = await choose(manager, result, "tariff_menu")
    result = await choose(manager, result, "tariff")
    result = await submit(manager, result, base_rate=0.5)
    text, saved = await _save(manager, result)

    assert "then edited by hand" in text
    assert saved["data"]["base_rate"] == 0.5
    assert saved["data"]["tariff_source"]["kind"] == "based_on"


async def test_looking_at_a_page_without_changing_it_does_not_detach(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    _use_store(monkeypatch, hass, tmp_path)
    entry = _entry(FOLLOWING)
    entry.add_to_hass(hass)

    manager, result = await _tariff_source(hass, entry)
    result = await choose(manager, result, "tariff_menu")
    result = await choose(manager, result, "tariff")
    result = await submit(manager, result)  # the page as it was
    result = await choose(manager, result, "init")
    assert "confirm" not in result["menu_options"]  # nothing to save
    manager.async_abort(result["flow_id"])


async def test_a_store_that_cannot_be_read_returns_to_the_tariff_menu(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    def unreachable(path: str) -> bytes:
        raise OSError("no network")

    _use_store(monkeypatch, hass, tmp_path, reader=unreachable)
    entry = _entry()
    entry.add_to_hass(hass)

    manager, result = await _tariff_source(hass, entry)
    result = await choose(manager, result, "store_country")
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["tariff_menu"]
    manager.async_abort(result["flow_id"])


async def test_turning_automatic_updates_off_and_on_changes_only_the_record(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    _use_store(monkeypatch, hass, tmp_path)
    entry = _entry(FOLLOWING)
    entry.add_to_hass(hass)

    manager, result = await _tariff_source(hass, entry)
    result = await choose(manager, result, "store_updates_off")
    text, saved = await _save(manager, result)
    assert "from the store, updates off" in text
    assert saved["data"]["tariff_source"]["auto_update"] is False
    assert saved["data"]["tariff_source"]["kind"] == "store"
    assert "base_rate" not in saved["data"]


async def test_updates_off_offers_turning_them_on(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    _use_store(monkeypatch, hass, tmp_path)
    entry = _entry({**FOLLOWING, "auto_update": False})
    entry.add_to_hass(hass)

    manager, result = await _tariff_source(hass, entry)
    assert "store_updates_on" in result["menu_options"]
    assert "store_updates_off" not in result["menu_options"]
    result = await choose(manager, result, "store_updates_on")
    _, saved = await _save(manager, result)
    assert saved["data"]["tariff_source"]["auto_update"] is True


async def test_undo_puts_back_the_prices_from_before_the_last_update(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    _use_store(monkeypatch, hass, tmp_path)
    updated = {
        **FOLLOWING,
        "effective_from": "2026-06-01",
        "previous": {
            "options": {"base_rate": 0.3, "standing_charge_per_day": 1.0},
            "record": {**FOLLOWING},
        },
    }
    entry = _entry(updated)
    entry.add_to_hass(hass)

    manager, result = await _tariff_source(hass, entry)
    assert "store_undo" in result["menu_options"]
    result = await choose(manager, result, "store_undo")
    _, saved = await _save(manager, result)
    data = saved["data"]
    assert data["base_rate"] == 0.3
    assert data["standing_charge_per_day"] == 1.0
    assert data["tariff_source"]["effective_from"] == "2026-01-01"
    assert data["tariff_source"]["auto_update"] is False
    assert "previous" not in data["tariff_source"]
