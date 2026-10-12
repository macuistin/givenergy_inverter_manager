"""The setup tariff pages start from the rates GivTCP holds. Configure never reads them."""

from __future__ import annotations

import pytest
from conftest import MIDDAY, SERIAL, full_config_data, set_givtcp_states
from homeassistant.config_entries import SOURCE_USER
from pytest_homeassistant_custom_component.common import MockConfigEntry
from wizard_support import every_field, open_options, serialised, submit

from custom_components.givenergy_inverter_manager.const import DOMAIN

NOTE = "Taken from GivTCP. Check them against your bill."


@pytest.fixture
def scenario():
    return MIDDAY


def _hold(hass, **rates: float) -> None:
    for name, value in rates.items():
        hass.states.async_set(f"sensor.givtcp_{SERIAL}_{name}_rate", value)


async def _tariff_form(hass):
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await submit(flow, result, pages=["tariff"])
    assert result["step_id"] == "tariff"
    return flow, result


def _field(result, name: str) -> dict:
    return next(f for f in every_field(serialised(result)) if f["name"] == name)


def _suggested(result, name: str):
    return (_field(result, name).get("description") or {}).get("suggested_value")


async def test_rates_the_user_set_start_the_tariff_page(hass):
    set_givtcp_states(hass, MIDDAY)
    _hold(hass, day=0.2918, night=0.1432, export=0.1)

    flow, result = await _tariff_form(hass)

    assert _suggested(result, "base_rate") == 0.2918
    assert _suggested(result, "export_rate") == 0.1
    assert NOTE in result["description_placeholders"]["rate_note"]
    # A suggestion is not a default: the field still has to be filled in.
    assert "default" not in _field(result, "base_rate")

    rows = await submit(flow, result, rate_count="1")
    assert rows["step_id"] == "tariff_rates"
    first = next(f for f in serialised(rows) if f["name"] == "rate_period_1")["schema"]
    rate = next(f for f in first if f["name"] == "rate")
    window = {f["name"]: f.get("default") for f in first if f["name"] in ("start", "end")}
    assert rate["default"] == 0.1432
    assert window == {"start": "23:00:00", "end": "07:00:00"}  # not GivTCP's 23:30 and 05:30
    assert NOTE in rows["description_placeholders"]["rate_note"]


async def test_the_rates_givtcp_ships_with_start_nothing(hass):
    set_givtcp_states(hass, MIDDAY)
    _hold(hass, day=0.395, night=0.155, export=0.04)

    flow, result = await _tariff_form(hass)

    assert _suggested(result, "base_rate") is None
    assert _suggested(result, "export_rate") is None
    assert result["description_placeholders"]["rate_note"] == ""
    rows = await submit(flow, result, base_rate=0.3, export_rate=0.1, rate_count="1")
    first = next(f for f in serialised(rows) if f["name"] == "rate_period_1")["schema"]
    assert "default" not in next(f for f in first if f["name"] == "rate")
    assert rows["description_placeholders"]["rate_note"] == ""


async def test_no_givtcp_rates_start_nothing(hass):
    set_givtcp_states(hass, MIDDAY)

    _, result = await _tariff_form(hass)

    assert _suggested(result, "base_rate") is None
    assert result["description_placeholders"]["rate_note"] == ""


async def test_only_the_rates_that_were_set_start_their_field(hass):
    set_givtcp_states(hass, MIDDAY)
    _hold(hass, day=0.395, night=0.155, export=0.12)

    _, result = await _tariff_form(hass)

    assert _suggested(result, "base_rate") is None
    assert _suggested(result, "export_rate") == 0.12


async def test_configure_does_not_read_givtcp_rates(hass):
    set_givtcp_states(hass, MIDDAY)
    _hold(hass, day=0.2918, night=0.1432, export=0.1)
    entry = MockConfigEntry(
        domain=DOMAIN, data=full_config_data(), unique_id=SERIAL, version=1, title="GivEnergy"
    )
    entry.add_to_hass(hass)

    result = await open_options(hass, entry, {"tariff": {}})

    saved = full_config_data()
    assert _field(result, "base_rate")["default"] == saved["base_rate"]
    assert _field(result, "export_rate")["default"] == saved["export_rate"]
