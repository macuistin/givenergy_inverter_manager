"""Shadow tariffs in Configure: add, remove, the limit, and what saving does."""

from __future__ import annotations

import pytest
from conftest import MIDDAY
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from wizard_support import choose, payload

from custom_components.givenergy_inverter_manager.const import CONF_SHADOW_TARIFFS


@pytest.fixture
def scenario():
    return MIDDAY


def manager(hass):
    return hass.config_entries.options


async def open_shadow_menu(hass, entry):
    result = await manager(hass).async_init(entry.entry_id)
    return await choose(manager(hass), result, "shadow_menu")


async def add_tariff(hass, result, name, **fields):
    result = await choose(manager(hass), result, "shadow_add")
    assert result["step_id"] == "shadow_add"
    return await manager(hass).async_configure(
        result["flow_id"], user_input=payload(result, shadow_name=name, rate_count="0", **fields)
    )


async def save(hass, result):
    """Back to the main menu from the shadow tariffs menu, then Save changes."""
    result = await choose(manager(hass), result, "init")
    result = await choose(manager(hass), result, "confirm")
    return await manager(hass).async_configure(result["flow_id"], user_input={})


async def test_a_shadow_tariff_is_added_and_saved_in_the_options(hass, loaded_entry):
    result = await open_shadow_menu(hass, loaded_entry)
    assert result["menu_options"] == ["shadow_from_list", "shadow_add", "shadow_search", "init"]

    result = await add_tariff(hass, result, "Flat", base_rate=0.25)
    assert result["step_id"] == "shadow_menu"
    assert result["menu_options"] == ["shadow_from_list", "shadow_add", "shadow_search", "shadow_remove", "init"]
    assert result["description_placeholders"]["shadow_list"] == "1 of 3: Flat"

    result = await save(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    saved = loaded_entry.options[CONF_SHADOW_TARIFFS]
    assert [(t["name"], t["base_rate"]) for t in saved] == [("Flat", 0.25)]
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.LOADED


async def test_a_shadow_tariff_with_timed_rates_asks_for_the_rows(hass, loaded_entry):
    result = await open_shadow_menu(hass, loaded_entry)
    result = await choose(manager(hass), result, "shadow_add")
    result = await manager(hass).async_configure(
        result["flow_id"], user_input=payload(result, shadow_name="Night saver", rate_count="1")
    )
    assert result["step_id"] == "shadow_rates"

    result = await manager(hass).async_configure(
        result["flow_id"],
        user_input={
            "rate_period_1": {"name": "Boost", "rate": 0.1, "start": "02:00:00", "end": "04:00:00"}
        },
    )
    assert result["step_id"] == "shadow_menu"
    result = await save(hass, result)

    saved = loaded_entry.options[CONF_SHADOW_TARIFFS][0]
    assert saved["rate_periods"] == [
        {"name": "Boost", "rate": 0.1, "start": "02:00", "end": "04:00"}
    ]


async def test_a_name_in_use_is_refused(hass, loaded_entry):
    result = await open_shadow_menu(hass, loaded_entry)
    result = await add_tariff(hass, result, "Flat")
    result = await choose(manager(hass), result, "shadow_add")
    result = await manager(hass).async_configure(
        result["flow_id"], user_input=payload(result, shadow_name="flat", rate_count="0")
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "shadow_name_duplicate"}


async def test_the_menu_stops_offering_add_at_the_limit(hass, loaded_entry):
    result = await open_shadow_menu(hass, loaded_entry)
    for name in ("A", "B", "C"):
        result = await add_tariff(hass, result, name)
    assert result["menu_options"] == ["shadow_search", "shadow_remove", "init"]


async def test_a_shadow_tariff_is_removed(hass, loaded_entry):
    result = await open_shadow_menu(hass, loaded_entry)
    result = await add_tariff(hass, result, "A")
    result = await add_tariff(hass, result, "B")
    result = await choose(manager(hass), result, "shadow_remove")
    result = await manager(hass).async_configure(
        result["flow_id"], user_input={"shadow_remove": "A"}
    )
    assert result["description_placeholders"]["shadow_list"] == "1 of 3: B"
    result = await save(hass, result)
    assert [t["name"] for t in loaded_entry.options[CONF_SHADOW_TARIFFS]] == ["B"]


async def test_nothing_is_written_when_the_list_is_unchanged(hass, loaded_entry):
    result = await open_shadow_menu(hass, loaded_entry)
    result = await add_tariff(hass, result, "A")
    result = await choose(manager(hass), result, "shadow_remove")
    result = await manager(hass).async_configure(
        result["flow_id"], user_input={"shadow_remove": "A"}
    )
    result = await manager(hass).async_configure(
        result["flow_id"], user_input={"next_step_id": "init"}
    )
    assert "confirm" not in result["menu_options"]


async def test_a_shadow_tariff_is_chosen_from_the_store_lists(
    hass, loaded_entry, monkeypatch, tmp_path
):
    from wizard_support import submit

    from custom_components.givenergy_inverter_manager.lib.tariffstore import (
        FolderCache,
        Store,
        folder_reader,
    )
    from custom_components.givenergy_inverter_manager.tariff_store import TariffStoreAccess
    from custom_components.givenergy_inverter_manager.wizard import store_steps
    from tests.lib.tariffstore.building import build_store
    from tests.lib.tariffstore.fixtures import tariff, write_store

    folder = write_store(tmp_path, {"p/plan/1.json": tariff(effective_from="2026-01-01")})
    build_store(folder)
    store = Store(folder_reader(folder), FolderCache(tmp_path / "cache"))
    monkeypatch.setattr(
        store_steps, "TariffStoreAccess", lambda _hass: TariffStoreAccess(hass, store)
    )

    result = await open_shadow_menu(hass, loaded_entry)
    result = await choose(manager(hass), result, "shadow_from_list")
    assert result["step_id"] == "store_country"
    for pick in ({"country": "IE"}, {"provider": "p"}, {"tariff": "plan"}, {"area": "rural"}):
        result = await submit(manager(hass), result, **pick)
    assert result["step_id"] == "store_review"
    assert "bill_start_day" not in [str(key) for key in result["data_schema"].schema]
    assert result["description_placeholders"]["lead"].startswith("This tariff will be added")
    result = await submit(manager(hass), result, export_rate=0.1)

    assert result["step_id"] == "shadow_menu"
    assert result["description_placeholders"]["shadow_list"] == "1 of 3: P Energy Plan (Rural)"
    result = await save(hass, result)
    saved = loaded_entry.options[CONF_SHADOW_TARIFFS][0]
    assert saved["base_rate"] == 0.32
    assert saved["export_rate"] == 0.1
    assert saved["vat_included"] is True
    assert saved["source"]["area"] == "rural"
    assert "tariff_source" not in loaded_entry.options  # the active tariff is untouched


async def test_a_cheaper_plan_is_searched_for_and_added(hass, loaded_entry, monkeypatch, tmp_path):
    from wizard_support import submit

    from custom_components.givenergy_inverter_manager.lib.tariffstore import (
        FolderCache,
        Store,
        folder_reader,
    )
    from custom_components.givenergy_inverter_manager.tariff_store import TariffStoreAccess
    from custom_components.givenergy_inverter_manager.wizard import shadow_search_steps
    from tests.lib.tariffstore.building import build_store
    from tests.lib.tariffstore.fixtures import flat, write_store

    folder = write_store(tmp_path, {"p/plan/1.json": flat(start="2026-01-01")})
    build_store(folder)
    store = Store(folder_reader(folder), FolderCache(tmp_path / "cache"))
    monkeypatch.setattr(
        shadow_search_steps, "TariffStoreAccess", lambda _hass: TariffStoreAccess(hass, store)
    )
    hass.config.country = "IE"

    result = await open_shadow_menu(hass, loaded_entry)
    assert "shadow_search" in result["menu_options"]
    result = await choose(manager(hass), result, "shadow_search")
    assert result["step_id"] == "shadow_search"
    result = await submit(manager(hass), result, unit="weeks", count=4, export_rate=0.1)

    assert result["step_id"] == "shadow_search_results"
    assert "Your plan" in result["description_placeholders"]["ranking"]
    assert result["description_placeholders"]["rank_line"].startswith("Your plan")
    result = await submit(manager(hass), result, plan="p/plan/all")
    assert result["step_id"] == "shadow_menu"
    result = await save(hass, result)
    saved = loaded_entry.options[CONF_SHADOW_TARIFFS][0]
    assert saved["source"]["tariff"] == "plan"
    assert "tariff_source" not in loaded_entry.options  # the active tariff is untouched
