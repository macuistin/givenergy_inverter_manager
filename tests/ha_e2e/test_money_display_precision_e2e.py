"""A money total shows two decimals, also on an install that registered the sensor without that."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import DOMAIN

MONEY = ("import_cost_today", "import_cost_this_month", "overnight_charge_cost", "accrued_bill")
PRICE_PER_KWH = "current_rate"


def _register(hass, entry, key: str, options: dict | None = None) -> str:
    """An entity registered by an earlier release: no suggested precision in its options."""
    created = er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_{key}",
        config_entry=entry,
        suggested_object_id=f"givenergy_inverter_manager_{key}",
    )
    if options:
        er.async_get(hass).async_update_entity_options(created.entity_id, "sensor", options)
    return created.entity_id


def _sensor_options(hass, entity_id: str) -> dict:
    return dict(er.async_get(hass).async_get(entity_id).options.get("sensor", {}))


async def _setup(hass, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_an_existing_money_entity_picks_up_two_decimals(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    entity_ids = [_register(hass, config_entry, key) for key in MONEY]
    assert all(_sensor_options(hass, e) == {} for e in entity_ids)

    await _setup(hass, config_entry)

    for entity_id in entity_ids:
        assert _sensor_options(hass, entity_id) == {"suggested_display_precision": 2}
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_a_price_per_kwh_gets_no_suggested_precision(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    price = _register(hass, config_entry, PRICE_PER_KWH)

    await _setup(hass, config_entry)

    assert "suggested_display_precision" not in _sensor_options(hass, price)
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_the_unit_and_the_statistics_settings_do_not_change(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    entity_id = _register(hass, config_entry, "import_cost_today")
    await _setup(hass, config_entry)

    attributes = hass.states.get(entity_id).attributes

    assert attributes["unit_of_measurement"] == "€"
    assert attributes["state_class"] == "total"
    assert attributes["device_class"] == "monetary"
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_a_precision_the_user_chose_is_kept(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    entity_id = _register(hass, config_entry, "import_cost_today", {"display_precision": 0})

    await _setup(hass, config_entry)

    assert _sensor_options(hass, entity_id) == {
        "display_precision": 0,
        "suggested_display_precision": 2,
    }
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_a_fresh_install_has_two_decimals_on_every_money_total(
    hass, hass_in_scenario, service_calls, config_entry
):
    config_entry.add_to_hass(hass)
    await _setup(hass, config_entry)

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{config_entry.entry_id}_accrued_bill")
    assert _sensor_options(hass, entity_id) == {"suggested_display_precision": 2}
    await hass.config_entries.async_unload(config_entry.entry_id)
