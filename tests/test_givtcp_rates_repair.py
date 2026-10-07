"""The repair that shows GivTCP rates that differ from the tariff entered here."""

from __future__ import annotations

import homeassistant.helpers.issue_registry as ir
import pytest

from custom_components.givenergy_inverter_manager.const import CONF_INVERTER_SERIAL
from custom_components.givenergy_inverter_manager.repairs import (
    ISSUE_GIVTCP_RATES_DIFFER,
    LEARN_MORE_URLS,
)
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states

SERIAL = "ab1234g567"
DAY, NIGHT, EXPORT = (f"sensor.givtcp_{SERIAL}_{name}_rate" for name in ("day", "night", "export"))


@pytest.fixture(autouse=True)
def _fresh_issue_mocks():
    ir.async_create_issue.reset_mock()
    ir.async_delete_issue.reset_mock()


def _coord(**cfg_overrides) -> FakeCoordinator:
    coord = FakeCoordinator(cfg=_cfg(**{CONF_INVERTER_SERIAL: SERIAL, **cfg_overrides}))
    coord.set_states(_default_states())
    return coord


def _raised() -> list[dict]:
    return [
        c.kwargs
        for c in ir.async_create_issue.call_args_list
        if c.args[2] == ISSUE_GIVTCP_RATES_DIFFER
    ]


def _cleared() -> int:
    return sum(
        1 for c in ir.async_delete_issue.call_args_list if c.args[2] == ISSUE_GIVTCP_RATES_DIFFER
    )


@pytest.mark.asyncio
async def test_a_differing_day_and_export_rate_raise_one_issue_with_both_values():
    coord = _coord()
    coord.set_states({DAY: "0.395", NIGHT: "0.1644", EXPORT: "0.2"})

    await coord._async_update_data()

    (issue,) = _raised()
    assert issue["is_fixable"] is False
    assert issue["severity"] == "warning"
    assert issue["learn_more_url"] == LEARN_MORE_URLS[ISSUE_GIVTCP_RATES_DIFFER]
    assert issue["translation_placeholders"] == {
        "rates": (
            "- Day rate: 0.3334 here, 0.395 in GivTCP\n- Export rate: 0.195 here, 0.2 in GivTCP"
        )
    }


@pytest.mark.asyncio
async def test_matching_rates_raise_nothing_and_clear_the_issue():
    coord = _coord()
    coord.set_states({DAY: "0.3334", NIGHT: "0.0965", EXPORT: "0.195"})

    await coord._async_update_data()

    assert _raised() == []
    assert _cleared() == 1


@pytest.mark.asyncio
async def test_the_issue_clears_once_givtcp_is_corrected():
    coord = _coord()
    coord.set_states({DAY: "0.395"})
    await coord._async_update_data()
    coord.set_states({DAY: "0.3334"})

    await coord._async_update_data()

    assert len(_raised()) == 1
    assert _cleared() == 1


@pytest.mark.asyncio
async def test_no_rate_entities_shows_nothing_and_touches_no_issue():
    coord = _coord()

    await coord._async_update_data()

    assert _raised() == []
    assert _cleared() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["unavailable", "unknown", "", "not a number", "0"])
async def test_a_rate_that_cannot_be_read_is_ignored(state):
    coord = _coord()
    coord.set_states({DAY: state, NIGHT: state, EXPORT: state})

    await coord._async_update_data()

    assert _raised() == []
    assert _cleared() == 0


@pytest.mark.asyncio
async def test_a_givtcp_outage_leaves_a_raised_issue_alone():
    coord = _coord()
    coord.set_states({DAY: "0.395"})
    await coord._async_update_data()
    coord.set_states({DAY: "unavailable"})

    await coord._async_update_data()

    assert _cleared() == 0


@pytest.mark.asyncio
async def test_the_tariff_saved_in_the_options_is_the_one_compared():
    coord = _coord()
    coord.entry.options = {"base_rate": 0.395}
    coord.set_states({DAY: "0.395"})

    await coord._async_update_data()

    assert _raised() == []


@pytest.mark.asyncio
async def test_no_serial_in_the_config_means_no_comparison():
    coord = _coord(**{CONF_INVERTER_SERIAL: None})
    coord.set_states({DAY: "0.395"})

    await coord._async_update_data()

    assert _raised() == []
