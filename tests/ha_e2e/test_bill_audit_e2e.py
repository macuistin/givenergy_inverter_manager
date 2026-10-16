"""The bill audit sensors in a real Home Assistant."""

from __future__ import annotations

from tests.dashboard_support import default_entity_ids

IDS = default_entity_ids()


async def test_the_audit_sensors_have_a_state_and_html(hass, loaded_entry):
    for key in ("bill_audit", "previous_bill_audit"):
        state = hass.states.get(IDS[key])
        assert state is not None, key
        assert state.state not in ("unknown", "unavailable", ""), key
        assert "html" in state.attributes, key

    assert hass.states.get(IDS["bill_audit"]).state.startswith("Bill €")
    assert "This bill period" in hass.states.get(IDS["bill_audit"]).attributes["html"]


async def test_a_first_install_has_no_previous_bill(hass, loaded_entry):
    assert hass.states.get(IDS["previous_bill_audit"]).state == "Not recorded"


async def test_the_bill_without_solar_is_a_bill_not_an_energy_cost(hass, loaded_entry):
    bill = float(hass.states.get(IDS["bill_without_solar"]).state)
    energy = float(hass.states.get(IDS["cost_without_solar_this_month"]).state)

    # The bill carries the standing charge and the levy, so it is more than the energy alone.
    assert bill >= energy
    assert bill > 0


async def test_the_html_attribute_is_not_recorded(hass, loaded_entry):
    from custom_components.givenergy_inverter_manager.sensor import _UNRECORDED_ATTRIBUTES

    assert "html" in _UNRECORDED_ATTRIBUTES


async def test_the_audit_sensors_publish_markdown_tables(hass, loaded_entry):
    current = hass.states.get(IDS["bill_audit"]).attributes
    previous = hass.states.get(IDS["previous_bill_audit"]).attributes

    assert current["bill_table"].startswith("| | You paid | Would have paid | Saved |")
    assert "| **Total** |" in current["bill_table"]
    assert current["days_table"].startswith("| Day | Imported | You paid |")
    assert "(today)" in current["days_table"]
    assert previous["summary_table"] == "No audit of the last bill period was recorded."
    assert previous["period"] == ""
