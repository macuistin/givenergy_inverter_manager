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
    assert result["menu_options"] == ["shadow_add", "init"]

    result = await add_tariff(hass, result, "Flat", base_rate=0.25)
    assert result["step_id"] == "shadow_menu"
    assert result["menu_options"] == ["shadow_add", "shadow_remove", "init"]
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
    assert result["menu_options"] == ["shadow_remove", "init"]


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
