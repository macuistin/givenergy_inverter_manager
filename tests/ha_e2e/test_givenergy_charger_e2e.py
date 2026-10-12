"""The GivEnergy EV charger through the mock GivTCP: found, set to Solar, never anything else.

`tools/mock_givtcp.py` publishes the charger the way GivTCP's datapoint reference says (Charging
State, Connection Status, Active Power, Charging Mode, Charge Control, Plug and Go) and records
every command it receives. No real GivEnergy charger has been read: what these tests prove is that
the integration follows its own rules against that layout.
"""

from __future__ import annotations

import pytest
from conftest import MIDDAY
from test_write_sequence_e2e import (
    SURPLUS,
    _set_up,
    cycle,
    mock,  # noqa: F401  (the shared mock fixture)
)

from tools.mock_givtcp import EVC_PREFIX

MODE = f"select.{EVC_PREFIX}_charging_mode"
CONTROL = f"select.{EVC_PREFIX}_charge_control"
PLUG_AND_GO = f"switch.{EVC_PREFIX}_plug_and_go"
HOT = 56.0


@pytest.fixture
def scenario():
    return MIDDAY


@pytest.fixture
def surplus(mock):  # noqa: F811
    """Spare solar and a car that wants it. Hot water keeps the immersion out of the picture."""
    mock.publish(SURPLUS)
    mock.set_water_temperature(HOT)
    return SURPLUS


async def test_the_charger_is_found_and_set_to_solar_with_one_select_write(
    hass_in_scenario, mock, surplus  # noqa: F811
):
    hass = hass_in_scenario
    assert mock.add_givevc(plugged_in=True, mode="Grid") == MODE
    entry = await _set_up(hass, mock, keep_setup_writes=True)
    await hass.async_block_till_done()

    charger = entry.runtime_data._ev_charger
    assert charger is not None and charger.display_name == "GivEnergy EVC (EV1234A567)"
    assert mock.sequence() == [("select.select_option", MODE, "Solar")]
    assert hass.states.get(MODE).state == "Solar"

    await cycle(hass, entry)
    await cycle(hass, entry)
    assert mock.sequence() == [("select.select_option", MODE, "Solar")]  # already there


async def test_charge_control_and_plug_and_go_are_never_touched(hass_in_scenario, mock, surplus):  # noqa: F811
    hass = hass_in_scenario
    mock.add_givevc(plugged_in=True, mode="Hybrid")
    entry = await _set_up(hass, mock, keep_setup_writes=True)
    for _ in range(4):
        await cycle(hass, entry)

    assert mock.other_calls == []
    assert hass.states.get(CONTROL).state == "Start"
    assert hass.states.get(PLUG_AND_GO).state == "on"
    assert {w.value for w in mock.writes_to(MODE)} <= {"Solar"}


async def test_no_request_when_the_car_is_not_plugged_in(hass_in_scenario, mock, surplus):  # noqa: F811
    hass = hass_in_scenario
    mock.add_givevc(plugged_in=False, mode="Grid")
    entry = await _set_up(hass, mock, keep_setup_writes=True)
    await cycle(hass, entry)
    assert mock.sequence() == []
    assert hass.states.get(MODE).state == "Grid"


async def test_dry_run_records_the_change_and_sends_nothing(hass_in_scenario, mock, surplus):  # noqa: F811
    hass = hass_in_scenario
    mock.add_givevc(plugged_in=True, mode="Grid")
    entry = await _set_up(hass, mock, dry_run=True, keep_setup_writes=True)
    assert mock.sequence() == []
    assert mock.other_calls == []
    assert hass.states.get(MODE).state == "Grid"
    skipped = entry.runtime_data.data.dry_run_last_skipped
    assert "→ Solar" in skipped and "currently 'Grid'" in skipped


async def test_a_charger_added_after_setup_is_found_and_set(hass_in_scenario, mock, surplus):  # noqa: F811
    hass = hass_in_scenario
    entry = await _set_up(hass, mock, keep_setup_writes=True)
    assert entry.runtime_data._ev_charger is None
    assert mock.sequence() == []

    mock.add_givevc(plugged_in=True, mode="Grid")
    mock.install()
    for _ in range(11):  # discovery repeats every tenth cycle
        await cycle(hass, entry)

    assert entry.runtime_data._ev_charger is not None
    assert mock.sequence() == [("select.select_option", MODE, "Solar")]


async def test_with_no_charger_nothing_about_one_exists(hass_in_scenario, mock, surplus):  # noqa: F811
    hass = hass_in_scenario
    entry = await _set_up(hass, mock, keep_setup_writes=True)
    await cycle(hass, entry)
    assert entry.runtime_data._ev_charger is None
    assert entry.runtime_data.data.ev_available is False
    assert mock.sequence() == [] and mock.other_calls == []


async def test_a_charger_whose_mode_select_offers_no_surplus_option_is_left_alone(
    hass_in_scenario, mock, surplus  # noqa: F811
):
    hass = hass_in_scenario
    mock.add_givevc(plugged_in=True, mode="Grid")
    hass.states.async_set(MODE, "Grid", {"options": ["Grid", "Hybrid"]})
    entry = await _set_up(hass, mock, keep_setup_writes=True)
    await cycle(hass, entry)
    assert mock.sequence() == []
    assert "no surplus-only mode" in entry.runtime_data.data.ev_protection_reason
