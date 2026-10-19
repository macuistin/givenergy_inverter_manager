"""The exact write sequence the integration sends to GivTCP, the immersion switch and the Zappi.

`tools/mock_givtcp.py` stands in for the devices. It publishes GivTCP's entities, records every
command in order and moves the written entity to the new value, the way a real device would.
Nothing here counts calls on a patched service: the assertions are on the device side.

Dry run is asserted on both sides: the mock saw no command, and the integration recorded what
it would have done.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import (
    CHEAP_NIGHT,
    IMMERSION_SWITCH,
    MIDDAY,
    SERIAL,
    full_config_data,
)
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.givenergy_inverter_manager.const import CONF_DRY_RUN, DOMAIN
from custom_components.givenergy_inverter_manager.coordinator import GivEnergyCoordinator
from custom_components.givenergy_inverter_manager.lib.givtcp.discovery import (
    discover_givtcp_inverters,
)
from tools.mock_givtcp import UNUSED_SLOT, MockGivTCP, Readings

# Taken at import, before the suite swaps the catch-up for a no-op.
REAL_CATCH_UP = GivEnergyCoordinator.async_catch_up_charge_write

PREFIX = f"givtcp_{SERIAL}"
TARGET = f"number.{PREFIX}_target_soc"
ENABLE_SCHEDULE = f"switch.{PREFIX}_enable_charge_schedule"
ENABLE_TARGET = f"switch.{PREFIX}_enable_charge_target"
WINDOW_START = f"select.{PREFIX}_charge_start_time_slot_1"
WINDOW_END = f"select.{PREFIX}_charge_end_time_slot_1"
ZAPPI_MODE = "select.myenergi_zappi_charge_mode"

COLD = 48.2  # below the 50 minimum: the engine wants the heater on
HOT = 56.0  # above the 55 target: the engine wants it off
# A winter night inside the cheap-rate window with the battery above the cheap-rate floor, so
# the setup cycle writes nothing and the charge target is the only thing the test sees.
NIGHT = Readings(solar_w=0, battery_soc=55, battery_w=0, grid_w=-600, load_w=600)
# Plenty of spare solar, a full battery and nothing charging it: enough surplus to start the car.
SURPLUS = Readings(solar_w=6000, battery_soc=95, battery_w=0, grid_w=4800, load_w=1200)


def _readings(scenario) -> Readings:
    return Readings(
        solar_w=scenario.solar_w,
        battery_soc=scenario.battery_soc,
        battery_w=scenario.battery_w,
        grid_w=scenario.grid_w,
        load_w=scenario.load_w,
    )


async def _set_up(
    hass, mock: MockGivTCP, *, dry_run: bool = False, keep_setup_writes: bool = False
) -> MockConfigEntry:
    data = full_config_data()
    if dry_run:
        data[CONF_DRY_RUN] = True
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GivEnergy Inverter Manager",
        data=data,
        unique_id=SERIAL,
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    # Setting up the switch and number platforms registers Home Assistant's own services of the
    # same names. The mock goes in after them. The setup cycle's own writes are dropped unless
    # the test is about them (the cheap-rate floor and the EV mode request can fire there).
    mock.install()
    if not keep_setup_writes:
        mock.clear()
    return entry


@pytest.fixture
def scenario():
    return MIDDAY


@pytest.fixture
def mock(hass_in_scenario, scenario) -> MockGivTCP:
    """The fake devices, published over the harness's own states."""
    hass = hass_in_scenario
    device = MockGivTCP(hass, serial=SERIAL)
    device.publish(_readings(scenario))
    device.add_immersion(temperature_c=COLD)
    device.install()
    return device


async def cycle(hass, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


# ── The mock is a faithful stand-in ─────────────────────────────────────────────────────────


async def test_discovery_finds_the_mock_as_a_fully_configured_inverter(hass_in_scenario, mock):
    inverters = discover_givtcp_inverters(
        {s.entity_id: s for s in hass_in_scenario.states.async_all()}
    )
    assert [i.serial for i in inverters] == [SERIAL]
    inverter = inverters[0]
    assert inverter.is_fully_configured
    assert inverter.has_charge_scheduling
    assert inverter.battery_capacity_kwh == pytest.approx(9.5)
    assert inverter.entities["target_soc"] == TARGET


async def test_a_write_moves_the_entity_and_is_recorded_with_its_value(hass_in_scenario, mock):
    hass = hass_in_scenario
    await hass.services.async_call(
        "number", "set_value", {"entity_id": TARGET, "value": 65}, blocking=True
    )
    await hass.services.async_call("switch", "turn_on", {"entity_id": ENABLE_TARGET}, blocking=True)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": WINDOW_START, "option": "02:00:00"}, blocking=True
    )
    assert mock.sequence() == [
        ("number.set_value", TARGET, 65),
        ("switch.turn_on", ENABLE_TARGET, None),
        ("select.select_option", WINDOW_START, "02:00:00"),
    ]
    assert hass.states.get(TARGET).state == "65"
    assert hass.states.get(ENABLE_TARGET).state == "on"
    assert hass.states.get(WINDOW_START).state == "02:00:00"


# ── Charge target ───────────────────────────────────────────────────────────────────────────


@pytest.fixture
def night(mock) -> Readings:
    mock.publish(NIGHT)
    return NIGHT


@pytest.mark.parametrize("scenario", [CHEAP_NIGHT], ids=lambda s: s.name)
async def test_setup_asks_for_the_catch_up_and_it_writes_the_target_once_inside_the_window(
    hass_in_scenario, mock, night, monkeypatch
):
    """The pending retries are lost with a restart, so a start at 02:30 makes the write."""
    hass = hass_in_scenario
    asked = []

    async def spy(self) -> None:
        asked.append(self)

    monkeypatch.setattr(GivEnergyCoordinator, "async_catch_up_charge_write", spy)
    entry = await _set_up(hass, mock, keep_setup_writes=True)
    coordinator = entry.runtime_data
    assert asked == [coordinator]
    assert mock.sequence() == []

    mock.install()  # setup put Home Assistant's own number and switch services back
    await REAL_CATCH_UP(coordinator)
    await hass.async_block_till_done()

    decision = coordinator.data.charge_decision
    assert mock.sequence() == [
        ("switch.turn_on", ENABLE_SCHEDULE, None),
        ("select.select_option", WINDOW_START, "02:00:00"),
        ("select.select_option", WINDOW_END, "04:00:00"),
        ("number.set_value", TARGET, decision.target_soc),
        ("switch.turn_on", ENABLE_TARGET, None),
    ]
    # Done once: the log now holds the manager's write, so asking again writes nothing.
    mock.clear()
    await REAL_CATCH_UP(coordinator)
    await hass.async_block_till_done()
    assert mock.sequence() == []


@pytest.mark.parametrize("scenario", [CHEAP_NIGHT], ids=lambda s: s.name)
async def test_charge_target_write_sequence_is_the_five_steps_in_order(
    hass_in_scenario, mock, night
):
    hass = hass_in_scenario
    entry = await _set_up(hass, mock, keep_setup_writes=True)
    assert mock.sequence() == []  # the setup cycle sends nothing at 55 %
    coordinator = entry.runtime_data
    decision = coordinator.data.charge_decision
    assert decision is not None
    assert decision.skip_charge is False

    # What the integration's one-minute-before-the-window timer calls.
    coordinator._write_charge_target_to_inverter(coordinator._now())
    await hass.async_block_till_done()

    assert mock.sequence() == [
        ("switch.turn_on", ENABLE_SCHEDULE, None),  # 1 enable the charge schedule
        ("select.select_option", WINDOW_START, "02:00:00"),  # 2 window start (Nightboost)
        ("select.select_option", WINDOW_END, "04:00:00"),  # 3 window end
        ("number.set_value", TARGET, decision.target_soc),  # 4 the target
        ("switch.turn_on", ENABLE_TARGET, None),  # 5 enable it (target below 100)
    ]
    assert 4 <= decision.target_soc < 100
    assert hass.states.get(WINDOW_START).state == "02:00:00"
    assert mock.other_calls == []


@pytest.mark.parametrize("scenario", [CHEAP_NIGHT], ids=lambda s: s.name)
async def test_a_second_apply_writes_nothing_because_the_device_already_holds_the_values(
    hass_in_scenario, mock, night
):
    hass = hass_in_scenario
    entry = await _set_up(hass, mock)
    coordinator = entry.runtime_data

    coordinator._write_charge_target_to_inverter(coordinator._now())
    await hass.async_block_till_done()
    first = mock.sequence()
    assert len(first) == 5

    coordinator._write_charge_target_to_inverter(coordinator._now())
    await hass.async_block_till_done()
    assert mock.sequence() == first  # read-before-write skipped all five


@pytest.mark.parametrize("scenario", [CHEAP_NIGHT], ids=lambda s: s.name)
async def test_a_rejected_target_write_stops_before_the_target_is_enabled(
    hass_in_scenario, mock, night
):
    hass = hass_in_scenario
    entry = await _set_up(hass, mock)
    coordinator = entry.runtime_data
    mock.fail_on(TARGET)

    coordinator._write_charge_target_to_inverter(coordinator._now())
    await hass.async_block_till_done()

    assert [w.entity_id for w in mock.writes] == [ENABLE_SCHEDULE, WINDOW_START, WINDOW_END]
    assert hass.states.get(ENABLE_TARGET).state == "off"


@pytest.mark.parametrize("scenario", [CHEAP_NIGHT], ids=lambda s: s.name)
async def test_dry_run_sends_no_charge_target_write_and_records_it(hass_in_scenario, mock, night):
    hass = hass_in_scenario
    entry = await _set_up(hass, mock, dry_run=True)
    coordinator = entry.runtime_data
    assert coordinator.is_dry_run

    coordinator._write_charge_target_to_inverter(coordinator._now())
    await hass.async_block_till_done()

    assert mock.sequence() == []
    assert coordinator.data.dry_run_last_skipped is not None
    assert coordinator._dry_run_last_skipped.startswith("Would write charge target ")
    assert "Night" in coordinator._dry_run_last_skipped or "Nightboost" in (
        coordinator._dry_run_last_skipped
    )
    # The device is exactly as it was.
    assert hass.states.get(ENABLE_SCHEDULE).state == "off"
    assert hass.states.get(WINDOW_START).state == UNUSED_SLOT


# ── Immersion ───────────────────────────────────────────────────────────────────────────────


async def test_immersion_on_then_off_decisions_are_the_only_writes(hass_in_scenario, mock):
    hass = hass_in_scenario
    entry = await _set_up(hass, mock)

    await cycle(hass, entry)  # cold water, surplus: the engine wants the heater on
    assert mock.sequence() == [("switch.turn_on", IMMERSION_SWITCH, None)]
    assert hass.states.get(IMMERSION_SWITCH).state == "on"

    mock.set_water_temperature(HOT)
    await cycle(hass, entry)
    assert mock.sequence() == [
        ("switch.turn_on", IMMERSION_SWITCH, None),
        ("switch.turn_off", IMMERSION_SWITCH, None),
    ]
    assert hass.states.get(IMMERSION_SWITCH).state == "off"
    assert mock.other_calls == []


async def test_an_immersion_already_in_the_wanted_state_is_not_written(hass_in_scenario, mock):
    hass = hass_in_scenario
    mock.add_immersion(on=True, temperature_c=COLD)
    entry = await _set_up(hass, mock)
    await cycle(hass, entry)
    assert mock.sequence() == []


async def test_dry_run_sends_no_immersion_command_and_records_it(hass_in_scenario, mock):
    hass = hass_in_scenario
    entry = await _set_up(hass, mock, dry_run=True)
    await cycle(hass, entry)
    assert mock.sequence() == []
    assert hass.states.get(IMMERSION_SWITCH).state == "off"
    assert "Would turn_on immersion heater" in entry.runtime_data.data.dry_run_last_skipped


# ── EV charger ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def surplus(mock) -> Readings:
    """Spare solar and a car that wants it. Hot water keeps the immersion out of the picture."""
    mock.publish(SURPLUS)
    mock.set_water_temperature(HOT)
    return SURPLUS


async def test_an_ev_mode_request_is_one_select_write_to_the_zappi(hass_in_scenario, mock, surplus):
    hass = hass_in_scenario
    assert mock.add_zappi(plugged_in=True, mode="Fast") == ZAPPI_MODE
    entry = await _set_up(hass, mock, keep_setup_writes=True)  # the setup cycle finds the Zappi
    await hass.async_block_till_done()

    assert mock.sequence() == [("select.select_option", ZAPPI_MODE, "Eco+")]
    assert hass.states.get(ZAPPI_MODE).state == "Eco+"

    # Already in Eco+: later cycles send nothing more.
    await cycle(hass, entry)
    await cycle(hass, entry)
    assert mock.sequence() == [("select.select_option", ZAPPI_MODE, "Eco+")]


async def test_no_ev_request_when_the_car_is_not_plugged_in(hass_in_scenario, mock, surplus):
    hass = hass_in_scenario
    mock.add_zappi(plugged_in=False, mode="Fast")
    entry = await _set_up(hass, mock, keep_setup_writes=True)
    await cycle(hass, entry)
    assert mock.sequence() == []
    assert hass.states.get(ZAPPI_MODE).state == "Fast"


async def test_dry_run_sends_no_ev_command_and_records_it(hass_in_scenario, mock, surplus):
    hass = hass_in_scenario
    mock.add_zappi(plugged_in=True, mode="Fast")
    entry = await _set_up(hass, mock, dry_run=True, keep_setup_writes=True)
    assert mock.sequence() == []
    assert hass.states.get(ZAPPI_MODE).state == "Fast"
    skipped = entry.runtime_data.data.dry_run_last_skipped
    assert "→ Eco+" in skipped
    assert "currently 'Fast'" in skipped


# ── The cheap-rate floor ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("scenario", [CHEAP_NIGHT], ids=lambda s: s.name)
async def test_cheap_rate_floor_top_up_writes_the_target_then_enables_it(hass_in_scenario, mock):
    """At 31 % inside the cheap window the setup cycle tops the battery up to the 40 % floor."""
    hass = hass_in_scenario
    mock.publish(replace(_readings(CHEAP_NIGHT), target_soc=20))
    await _set_up(hass, mock, keep_setup_writes=True)
    assert mock.sequence() == [
        ("number.set_value", TARGET, 40),
        ("switch.turn_on", ENABLE_TARGET, None),
    ]
    assert hass.states.get(TARGET).state == "40"


@pytest.mark.parametrize("scenario", [CHEAP_NIGHT], ids=lambda s: s.name)
async def test_the_floor_only_raises_the_target_so_a_higher_one_is_kept(hass_in_scenario, mock):
    """A 50 % target already on the inverter is above the 40 % floor: only the enable is sent."""
    hass = hass_in_scenario
    await _set_up(hass, mock, keep_setup_writes=True)
    assert mock.sequence() == [("switch.turn_on", ENABLE_TARGET, None)]
    assert hass.states.get(TARGET).state == "50"


@pytest.mark.parametrize("scenario", [CHEAP_NIGHT], ids=lambda s: s.name)
async def test_dry_run_sends_no_floor_top_up(hass_in_scenario, mock):
    hass = hass_in_scenario
    await _set_up(hass, mock, dry_run=True, keep_setup_writes=True)
    assert mock.sequence() == []
    assert hass.states.get(TARGET).state == "50"


# ── Dry run, as a whole ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("scenario", [CHEAP_NIGHT], ids=lambda s: s.name)
async def test_dry_run_leaves_every_device_untouched_through_every_path(hass_in_scenario, mock):
    """Low battery, cold water, a plugged-in car and a charge target due: nothing is sent."""
    hass = hass_in_scenario
    mock.add_zappi(plugged_in=True, mode="Fast")
    mock.publish(Readings(solar_w=0, battery_soc=31, battery_w=0, grid_w=-600, load_w=600))
    entry = await _set_up(hass, mock, dry_run=True, keep_setup_writes=True)
    coordinator = entry.runtime_data
    before = {s.entity_id: s.state for s in hass.states.async_all() if s.entity_id in mock._owned}

    coordinator._write_charge_target_to_inverter(coordinator._now())
    await hass.async_block_till_done()
    await cycle(hass, entry)
    await cycle(hass, entry)

    assert mock.sequence() == []
    assert mock.other_calls == []
    after = {s.entity_id: s.state for s in hass.states.async_all() if s.entity_id in mock._owned}
    assert after == before
