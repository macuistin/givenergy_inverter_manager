"""Shadow tariffs in real Home Assistant: their device, their sensors and what they read."""

from __future__ import annotations

import pytest
from conftest import MIDDAY, SERIAL, full_config_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import CONF_SHADOW_TARIFFS, DOMAIN
from custom_components.givenergy_inverter_manager.lib.tariff import SlotDay

SHADOW = {
    "name": "Flat",
    "base_rate": 0.40,
    "export_rate": 0.0,
    "rate_periods": [],
    "standing_charge_per_day": 0.0,
    "pso_levy_per_month": 0.0,
    "vat_rate": 0.0,
    "discount_rate": 0.0,
}
KEYS = ("bill", "difference")


@pytest.fixture
def scenario():
    return MIDDAY


async def _set_up(hass, *, shadows: bool = True) -> MockConfigEntry:
    data = full_config_data()
    if shadows:
        data[CONF_SHADOW_TARIFFS] = [SHADOW]
    entry = MockConfigEntry(
        domain=DOMAIN, title="GivEnergy Inverter Manager", data=data, unique_id=SERIAL, version=1
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _entity_id(hass, domain: str, entry, suffix: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.entry_id}_shadow_flat_{suffix}"
    )


async def test_a_shadow_tariff_has_a_device_and_three_entities_that_start_enabled(
    hass_in_scenario,
):
    hass = hass_in_scenario
    entry = await _set_up(hass)
    registry = er.async_get(hass)

    ids = [
        _entity_id(hass, "sensor", entry, "bill"),
        _entity_id(hass, "sensor", entry, "difference"),
        _entity_id(hass, "binary_sensor", entry, "cheaper"),
    ]
    assert ids == [
        "sensor.shadow_tariffs_flat_bill_so_far",
        "sensor.shadow_tariffs_flat_difference_from_your_tariff",
        "binary_sensor.shadow_tariffs_flat_would_be_cheaper_so_far",
    ]
    assert all(registry.async_get(i).disabled_by is None for i in ids)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert "Shadow tariffs" in {d.name for d in devices}
    assert {registry.async_get(i).device_id for i in ids} != {None}

    await hass.config_entries.async_unload(entry.entry_id)


async def test_without_a_shadow_tariff_there_is_no_device_and_no_entity(hass_in_scenario):
    hass = hass_in_scenario
    entry = await _set_up(hass, shadows=False)

    assert _entity_id(hass, "sensor", entry, "bill") is None
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert "Shadow tariffs" not in {d.name for d in devices}

    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_sensors_re_price_the_stored_slots(hass_in_scenario):
    hass = hass_in_scenario
    entry = await _set_up(hass)

    coordinator = entry.runtime_data
    today = dt_util.now().date()
    history = coordinator._slots.history
    day = SlotDay(today, dt_util.get_default_time_zone())
    for index in range(10):
        day.flows["import"][index] = 1.0
        day.seconds[index] = 1800
    history._days[today] = day
    coordinator._shadow_cache = None
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    bill = hass.states.get("sensor.shadow_tariffs_flat_bill_so_far")
    difference = hass.states.get("sensor.shadow_tariffs_flat_difference_from_your_tariff")
    cheaper = hass.states.get("binary_sensor.shadow_tariffs_flat_would_be_cheaper_so_far")
    assert float(bill.state) == pytest.approx(4.0)  # 10 kWh at 0.40, no other charge
    assert float(difference.state) == pytest.approx(
        float(bill.state) - bill.attributes["active_tariff_total"]
    )
    assert bill.attributes["note"].startswith("Re-priced")
    assert bill.attributes["data_from"] == today.isoformat()
    assert bill.attributes["days_with_data"] == 1
    assert bill.attributes["would_be_cheaper"] in ("Yes", "No")
    assert "| Band | kWh | Energy cost |" in bill.attributes["bands_table"]
    assert cheaper.state in ("on", "off")

    await hass.config_entries.async_unload(entry.entry_id)


async def test_removing_the_last_shadow_tariff_removes_the_device(hass_in_scenario):
    hass = hass_in_scenario
    entry = await _set_up(hass)
    registry = dr.async_get(hass)
    assert "Shadow tariffs" in {d.name for d in dr.async_entries_for_config_entry(registry, entry.entry_id)}

    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_SHADOW_TARIFFS: []})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert "Shadow tariffs" not in {
        d.name for d in dr.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert _entity_id(hass, "sensor", entry, "bill") is None

    await hass.config_entries.async_unload(entry.entry_id)
