"""The hot water status and the source attributes, in a real Home Assistant."""

from __future__ import annotations

from conftest import IMMERSION_SWITCH, IMMERSION_TEMP


def _state(hass, sensor_entries, entry, key):
    entity = next(e for e in sensor_entries(hass, entry) if e.unique_id.endswith(f"_{key}"))
    return hass.states.get(entity.entity_id)


async def test_the_hot_water_status_is_ok_then_error_when_a_source_goes_unavailable(
    hass, loaded_entry, sensor_entries
):
    coordinator = loaded_entry.runtime_data
    await coordinator.async_refresh()
    status = _state(hass, sensor_entries, loaded_entry, "immersion_status")
    assert status.state == "ok"
    roles = {row["role"]: row for row in status.attributes["sources"]}
    assert roles["water temperature"]["entity_id"] == IMMERSION_TEMP
    assert roles["heater switch"]["entity_id"] == IMMERSION_SWITCH
    assert roles["water temperature"]["last_reported"] is not None

    hass.states.async_set(IMMERSION_TEMP, "unavailable")
    await coordinator.async_refresh()
    status = _state(hass, sensor_entries, loaded_entry, "immersion_status")
    assert status.state == "error"
    assert IMMERSION_TEMP in status.attributes["cause"]


async def test_a_live_inverter_sensor_names_the_givtcp_entity_it_reads(
    hass, loaded_entry, sensor_entries
):
    await loaded_entry.runtime_data.async_refresh()
    for key in ("solar_power", "battery_soc", "battery_power", "grid_power", "house_load"):
        sensor = _state(hass, sensor_entries, loaded_entry, key)
        (source,) = sensor.attributes["sources"]
        assert source["entity_id"].startswith("sensor.")
        assert source["last_reported"] is not None
