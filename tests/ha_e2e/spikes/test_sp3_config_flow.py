"""SP3, part 1: the setup flow. Checklist, routing, last_step, nothing stored until confirm.

The throwaway flows and fixtures are in sp3_support.py. See docs/design/spikes/SP3.md.
"""

# ruff: noqa: F811
# The fixtures come from sp3_support and are used by name, which ruff reads as a redefinition.

from __future__ import annotations

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from homeassistant.setup import async_setup_component
from sp3_support import (  # noqa: F401
    DOMAIN,
    PAGES,
    Counters,
    ReloadFlow,
    SetupFlow,
    StaleSnapshotOptionsWizard,
    _fresh_deprecation_log,
    counters,
    loaded_entry,
    wizard,
    wizard_without_listener,
)

# ---------------------------------------------------------------------------------------------
# 1. Config flow: checklist, routing, last_step, nothing stored until confirm
# ---------------------------------------------------------------------------------------------


async def test_config_flow_checklist_routes_only_to_ticked_pages(hass, wizard):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert (flow["type"], flow["step_id"], flow["last_step"]) == (
        FlowResultType.FORM,
        "system",
        False,
    )

    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {"pages": ["battery", "tariff"]},  # order from the client is ignored
    )
    assert (flow["step_id"], flow["last_step"]) == ("tariff", False)

    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"base_rate": 0.31, "rate_count": "0"}
    )
    # hot_water was not ticked, so the next page is battery, then the confirm step.
    assert (flow["step_id"], flow["last_step"]) == ("battery", False)

    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"battery_capacity_kwh": 9.5}
    )
    assert (flow["type"], flow["step_id"], flow["last_step"]) == (
        FlowResultType.FORM,
        "confirm",
        True,
    )
    assert flow["description_placeholders"]["summary"] == (
        "base_rate, battery_capacity_kwh, rate_count, serial"
    )

    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert flow["data"] == {
        "serial": "ab1234g567",
        "base_rate": 0.31,
        "rate_count": 0,
        "battery_capacity_kwh": 9.5,
    }


async def test_config_flow_with_nothing_ticked_goes_straight_to_confirm(hass, wizard):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"pages": []})
    assert (flow["step_id"], flow["last_step"]) == ("confirm", True)
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert flow["data"] == {"serial": "ab1234g567"}


async def test_config_flow_answer_decides_how_many_rate_rows_the_next_form_has(hass, wizard):
    """The count asked on the tariff form builds the next form's schema (rule 2 and 5)."""
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"pages": ["tariff"]})
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"base_rate": 0.3, "rate_count": "2"}
    )
    assert (flow["step_id"], flow["last_step"]) == ("tariff_rates", False)
    names = [f["name"] for f in cv.to_field_list(flow["data_schema"])]
    assert names == ["name_0", "rate_0", "name_1", "rate_1"]

    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {"name_0": "Night", "rate_0": 0.1, "name_1": "Peak", "rate_1": 0.4},
    )
    assert flow["step_id"] == "confirm"
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert flow["data"]["rates"] == [
        {"name": "Night", "rate": 0.1},
        {"name": "Peak", "rate": 0.4},
    ]


async def test_config_flow_stores_nothing_until_confirm(hass, wizard, hass_storage):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    flow_id = flow["flow_id"]
    for user_input in (
        {"pages": ["tariff", "hot_water", "battery"]},
        {"base_rate": 0.3, "rate_count": "0"},
        {},
        {"battery_capacity_kwh": 9.5},
    ):
        flow = await hass.config_entries.flow.async_configure(flow_id, user_input)
        # After every screen: no entry, nothing in the config entries store, no setup.
        assert hass.config_entries.async_entries(DOMAIN) == []
        stored = hass_storage.get("core.config_entries", {}).get("data", {}).get("entries", [])
        assert [e for e in stored if e["domain"] == DOMAIN] == []
    assert flow["step_id"] == "confirm"
    assert wizard.setups == 0

    # Walking away at the confirm step (the abort the frontend sends on close) leaves nothing.
    hass.config_entries.flow.async_abort(flow_id)
    assert hass.config_entries.async_entries(DOMAIN) == []
    assert wizard.setups == 0


async def test_config_flow_step_counts_are_recomputed_per_screen(hass, wizard):
    """'Step n of about m' comes from description_placeholders, so it can change per screen."""
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert flow["description_placeholders"]["total"] == "3"
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"pages": ["tariff", "hot_water", "battery"]}
    )
    assert flow["description_placeholders"] == {"step": "2", "total": "5"}


async def test_checklist_form_serialises_for_the_frontend_api(hass, wizard, hass_client):
    """The REST view the frontend uses returns last_step and a multi-select schema."""
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()
    response = await client.post("/api/config/config_entries/flow", json={"handler": DOMAIN})
    assert response.status == 200
    body = await response.json()
    assert body["type"] == "form"
    assert body["step_id"] == "system"
    assert body["last_step"] is False
    (field,) = body["data_schema"]
    assert field["name"] == "pages"
    assert field["selector"]["select"]["multiple"] is True
    assert field["selector"]["select"]["mode"] == "list"
    assert field["selector"]["select"]["options"] == PAGES

    response = await client.post(
        f"/api/config/config_entries/flow/{body['flow_id']}", json={"pages": ["tariff"]}
    )
    body = await response.json()
    assert (body["step_id"], body["last_step"]) == ("tariff", False)
    hass.config_entries.flow.async_abort(body["flow_id"])
