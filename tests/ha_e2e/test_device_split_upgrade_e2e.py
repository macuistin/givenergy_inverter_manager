"""An install from before the device split keeps its entity ids and gets the new devices."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.givenergy_inverter_manager.const import DOMAIN

_OLD_ID = "sensor.givenergy_inverter_manager_immersion_heater_power"


async def test_existing_entity_keeps_its_id_and_moves_to_the_immersion_device(
    hass_in_scenario, service_calls, config_entry
):
    hass = hass_in_scenario
    config_entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    registry = er.async_get(hass)
    main = devices.async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, config_entry.entry_id)}
    )
    registry.async_get_or_create(
        Platform.SENSOR,
        DOMAIN,
        f"{config_entry.entry_id}_immersion_power",
        suggested_object_id="givenergy_inverter_manager_immersion_heater_power",
        config_entry=config_entry,
        device_id=main.id,
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entry = registry.async_get(_OLD_ID)
    assert entry is not None
    assert entry.unique_id == f"{config_entry.entry_id}_immersion_power"
    immersion = next(
        d
        for d in dr.async_entries_for_config_entry(devices, config_entry.entry_id)
        if (DOMAIN, f"{config_entry.entry_id}_immersion") in d.identifiers
    )
    assert immersion.via_device_id == main.id
    assert entry.device_id == immersion.id
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_existing_switch_and_number_keep_their_ids_and_move_too(
    hass_in_scenario, service_calls, config_entry
):
    hass = hass_in_scenario
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = {
        (
            Platform.SWITCH,
            "auto_immersion",
        ): "switch.givenergy_inverter_manager_auto_immersion_divert",
        (Platform.NUMBER, "surplus_divert_soc_pct"): (
            "number.givenergy_inverter_manager_immersion_divert_minimum_soc"
        ),
    }
    for (platform, key), entity_id in old.items():
        registry.async_get_or_create(
            platform,
            DOMAIN,
            f"{config_entry.entry_id}_{key}",
            suggested_object_id=entity_id.split(".", 1)[1],
            config_entry=config_entry,
        )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    immersion = next(
        d
        for d in dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
        if (DOMAIN, f"{config_entry.entry_id}_immersion") in d.identifiers
    )
    for entity_id in old.values():
        entry = registry.async_get(entity_id)
        assert entry is not None
        assert entry.device_id == immersion.id
    await hass.config_entries.async_unload(config_entry.entry_id)
