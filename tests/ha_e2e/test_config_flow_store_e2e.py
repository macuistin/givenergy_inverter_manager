"""Choosing a tariff from the store in the setup wizard, against a real flow manager.

The store is a small folder built for the test and read through the real store client, so the
screens, the fit test and what is saved are the real ones. No network is used.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import MIDDAY
from homeassistant.data_entry_flow import FlowResultType
from setup_support import finish, manager, start, unload
from wizard_support import choose, submit, submit_raw

from custom_components.givenergy_inverter_manager.lib.tariffstore import (
    FolderCache,
    Store,
    folder_reader,
)
from custom_components.givenergy_inverter_manager.tariff_store import TariffStoreAccess
from custom_components.givenergy_inverter_manager.wizard import store_steps
from tests.lib.tariffstore.building import build_store
from tests.lib.tariffstore.fixtures import tariff, write_store


@pytest.fixture
def scenario():
    return MIDDAY


def _use_store(monkeypatch, hass, folder: Path, cache: Path, reader=None) -> None:
    store = Store(reader or folder_reader(folder), FolderCache(cache))
    monkeypatch.setattr(store_steps, "TariffStoreAccess", lambda _hass: TariffStoreAccess(hass, store))


def _built(tmp_path: Path, document: dict) -> Path:
    folder = write_store(tmp_path, {"p/plan/1.json": document})
    build_store(folder)
    return folder


async def _to_the_list(hass):
    result = await start(hass)
    result = await submit_raw(manager(hass), result, pages=["tariff"])
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "tariff_source"
    assert result["menu_options"] == ["store_country", "tariff"]
    return await choose(manager(hass), result, "store_country")


async def test_a_plan_chosen_from_the_list_is_saved_with_where_it_came_from(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    folder = _built(tmp_path, tariff(effective_from="2026-01-01"))
    _use_store(monkeypatch, hass, folder, tmp_path / "cache")

    result = await _to_the_list(hass)
    assert result["step_id"] == "store_country"
    result = await submit(manager(hass), result, country="IE")
    assert result["step_id"] == "store_provider"
    result = await submit(manager(hass), result, provider="p")
    assert result["step_id"] == "store_plan"
    result = await submit(manager(hass), result, tariff="plan")
    assert result["step_id"] == "store_area"
    result = await submit(manager(hass), result, area="rural")
    assert result["step_id"] == "store_review"
    review = result["description_placeholders"]["review"]
    assert "- Day: 0.32 EUR per kWh" in review
    assert "- Standing charge: 1.1 EUR per day" in review
    assert "VAT: 9%, already in the prices" in review

    result = await submit(manager(hass), result, bill_start_day=16)
    assert result["step_id"] == "confirm"
    entry = await finish(hass, result)
    assert entry.data["base_rate"] == 0.32
    assert entry.data["standing_charge_per_day"] == 1.1
    assert entry.data["vat_included"] is True
    assert entry.data["bill_start_day"] == 16
    assert entry.data["rate_periods"][0]["name"] == "Night"
    assert entry.data["tariff_source"] == {
        "kind": "store",
        "country": "IE",
        "provider": "p",
        "tariff": "plan",
        "area": "rural",
        "effective_from": "2026-01-01",
        "auto_update": True,
    }
    await unload(hass, entry)


async def test_a_plan_with_one_area_does_not_ask_for_it(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    flat = {
        "schema": 1, "name": "Flat", "provider": "P Energy", "effective_from": "2026-01-01",
        "source": {"id": "example-source", "url": "https://example.test/prices"},
        "bands": [{"name": "All day"}],
        "areas": {"all": {"standing": "0.5", "rates": {"All day": "0.25"}}},
    }
    folder = _built(tmp_path, flat)
    _use_store(monkeypatch, hass, folder, tmp_path / "cache")

    result = await _to_the_list(hass)
    result = await submit(manager(hass), result, country="IE")
    result = await submit(manager(hass), result, provider="p")
    result = await submit(manager(hass), result, tariff="plan")
    assert result["step_id"] == "store_review"
    manager(hass).async_abort(result["flow_id"])


async def test_a_store_that_cannot_be_read_leaves_only_typing_the_rates_in(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    def unreachable(path: str) -> bytes:
        raise OSError("no network")

    _use_store(monkeypatch, hass, tmp_path, tmp_path / "cache", reader=unreachable)

    result = await _to_the_list(hass)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["tariff"]
    assert "could not be read" in result["description_placeholders"]["note"]
    result = await choose(manager(hass), result, "tariff")
    assert result["step_id"] == "tariff"
    manager(hass).async_abort(result["flow_id"])


async def test_a_plan_the_options_cannot_hold_says_why_and_offers_typing_it_in(
    hass, hass_in_scenario, service_calls, monkeypatch, tmp_path
):
    weekend = tariff(
        effective_from="2026-01-01",
        bands=[{"name": "Day"}, {"name": "Night", "hours": "23:00-08:00", "days": ["sat", "sun"]}],
    )
    folder = _built(tmp_path, weekend)
    _use_store(monkeypatch, hass, folder, tmp_path / "cache")

    result = await _to_the_list(hass)
    result = await submit(manager(hass), result, country="IE")
    result = await submit(manager(hass), result, provider="p")
    result = await submit(manager(hass), result, tariff="plan")
    result = await submit_raw(manager(hass), result, area="rural")

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["store_country", "tariff"]
    assert "weekday, seasonal or public holiday rates" in result["description_placeholders"]["note"]
    result = await choose(manager(hass), result, "tariff")
    assert result["step_id"] == "tariff"
    manager(hass).async_abort(result["flow_id"])
