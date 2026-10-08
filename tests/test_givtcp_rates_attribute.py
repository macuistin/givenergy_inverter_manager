"""GivTCP rates that differ from the tariff show as attributes of Current Rate, never as a repair."""

from __future__ import annotations

import homeassistant.helpers.issue_registry as ir
import pytest

from custom_components.givenergy_inverter_manager.const import CONF_INVERTER_SERIAL
from custom_components.givenergy_inverter_manager.sensor import SENSOR_DESCRIPTIONS
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states

SERIAL = "ab1234g567"
DAY, NIGHT, EXPORT = (f"sensor.givtcp_{SERIAL}_{name}_rate" for name in ("day", "night", "export"))
ATTRS_FN = next(d for d in SENSOR_DESCRIPTIONS if d.key == "current_rate").attrs_fn


@pytest.fixture(autouse=True)
def _fresh_issue_mocks():
    ir.async_create_issue.reset_mock()
    ir.async_delete_issue.reset_mock()


def _coord(**cfg_overrides) -> FakeCoordinator:
    coord = FakeCoordinator(cfg=_cfg(**{CONF_INVERTER_SERIAL: SERIAL, **cfg_overrides}))
    coord.set_states(_default_states())
    return coord


async def _attributes(coord: FakeCoordinator) -> dict | None:
    data = await coord._async_update_data()
    return ATTRS_FN(data) if ATTRS_FN else None


def _rate_issue_calls() -> list:
    calls = ir.async_create_issue.call_args_list + ir.async_delete_issue.call_args_list
    return [c for c in calls if c.args[2] == "givtcp_rates_differ"]


@pytest.mark.asyncio
async def test_a_differing_day_and_export_rate_are_listed_with_both_values():
    coord = _coord()
    coord.set_states({DAY: "0.395", NIGHT: "0.1644", EXPORT: "0.2"})

    assert await _attributes(coord) == {
        "givtcp_rates_differ": True,
        "givtcp_rate_differences": [
            "Day rate: 0.3334 here, 0.395 in GivTCP",
            "Export rate: 0.195 here, 0.2 in GivTCP",
        ],
    }


@pytest.mark.asyncio
async def test_a_mismatch_creates_no_repair_and_touches_no_issue():
    coord = _coord()
    coord.set_states({DAY: "0.395", NIGHT: "0.1644", EXPORT: "0.2"})

    await coord._async_update_data()

    assert _rate_issue_calls() == []


@pytest.mark.asyncio
async def test_matching_rates_report_false_and_an_empty_list():
    coord = _coord()
    coord.set_states({DAY: "0.3334", NIGHT: "0.0965", EXPORT: "0.195"})

    assert await _attributes(coord) == {
        "givtcp_rates_differ": False,
        "givtcp_rate_differences": [],
    }


@pytest.mark.asyncio
async def test_the_attribute_follows_givtcp_once_it_is_corrected():
    coord = _coord()
    coord.set_states({DAY: "0.395"})
    assert (await _attributes(coord))["givtcp_rates_differ"] is True
    coord.set_states({DAY: "0.3334"})

    assert (await _attributes(coord))["givtcp_rates_differ"] is False


@pytest.mark.asyncio
async def test_no_rate_entities_means_no_attributes():
    coord = _coord()

    assert await _attributes(coord) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["unavailable", "unknown", "", "not a number", "0"])
async def test_a_rate_that_cannot_be_read_means_no_attributes(state):
    coord = _coord()
    coord.set_states({DAY: state, NIGHT: state, EXPORT: state})

    assert await _attributes(coord) is None


@pytest.mark.asyncio
async def test_a_givtcp_outage_removes_the_attributes_again():
    coord = _coord()
    coord.set_states({DAY: "0.395"})
    assert await _attributes(coord) is not None
    coord.set_states({DAY: "unavailable"})

    assert await _attributes(coord) is None


@pytest.mark.asyncio
async def test_the_tariff_saved_in_the_options_is_the_one_compared():
    coord = _coord()
    coord.entry.options = {"base_rate": 0.395}
    coord.set_states({DAY: "0.395"})

    assert (await _attributes(coord))["givtcp_rates_differ"] is False


@pytest.mark.asyncio
async def test_no_serial_in_the_config_means_no_comparison():
    coord = _coord(**{CONF_INVERTER_SERIAL: None})
    coord.set_states({DAY: "0.395"})

    assert await _attributes(coord) is None


def test_the_attributes_belong_to_the_current_rate_sensor_only():
    others = [d.key for d in SENSOR_DESCRIPTIONS if d.attrs_fn is ATTRS_FN and d.key != "current_rate"]
    assert ATTRS_FN is not None
    assert others == []
