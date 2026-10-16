"""Reading GivTCP's battery pause: the option strings, the times, and every fixture system.

GivTCP's Battery_pause_mode offers Disabled, PauseCharge, PauseDischarge and PauseBoth. The two
that stop discharge give a window. Anything else, and any pause that cannot be read, gives none,
so an install without a pause reads as it did before the pause was modelled.
"""

from __future__ import annotations

import logging
from datetime import time
from types import SimpleNamespace

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_BATTERY_POWER,
    CONF_INVERTER_SERIAL,
    CONF_SOLAR_POWER,
)
from custom_components.givenergy_inverter_manager.core.battery_pause import PauseWindow
from custom_components.givenergy_inverter_manager.core.system_types import select_controller
from custom_components.givenergy_inverter_manager.inverter.givtcp.battery_pause import (
    charge_pause_window,
    parse_clock,
    pause_window,
    pauses_charge,
    pauses_discharge,
)
from custom_components.givenergy_inverter_manager.inverter.givtcp.discovery import (
    battery_pause_entities,
    discover_givtcp_inverters,
)
from custom_components.givenergy_inverter_manager.inverter.givtcp.reader import GivTCPReader
from tests.fixtures import givtcp_systems as fixtures

NIGHT = PauseWindow(time(23, 0), time(8, 0))


class TestTheModeOptions:
    @pytest.mark.parametrize(
        ("option", "pauses_discharge_expected"),
        [
            # GivTCP's own options.
            ("Disabled", False),
            ("PauseCharge", False),
            ("PauseDischarge", True),
            ("PauseBoth", True),
            # The same words with other case or separators.
            ("pausedischarge", True),
            ("PAUSEBOTH", True),
            ("Pause Discharge", True),
            ("pause_both", True),
            ("pause-charge", False),
            ("  PauseDischarge  ", True),
            # Text GivTCP does not use.
            ("", None),
            ("Eco", None),
            ("Pause", None),
            ("PauseDischargeAndCharge", None),
            ("unavailable", None),
            (None, None),
        ],
    )
    def test_whether_an_option_stops_discharge(self, option, pauses_discharge_expected):
        assert pauses_discharge(option) is pauses_discharge_expected


class TestWhichOptionsStopCharging:
    @pytest.mark.parametrize(
        ("option", "expected"),
        [
            ("Disabled", False),
            ("PauseCharge", True),
            ("PauseDischarge", False),
            ("PauseBoth", True),
            ("pause_charge", True),
            ("Pause Both", True),
            ("Eco", None),
            ("", None),
            (None, None),
        ],
    )
    def test_whether_an_option_stops_charging(self, option, expected):
        assert pauses_charge(option) is expected

    @pytest.mark.parametrize(
        ("mode", "discharge", "charge"),
        [
            ("Disabled", None, None),
            ("PauseCharge", None, NIGHT),
            ("PauseDischarge", NIGHT, None),
            ("PauseBoth", NIGHT, NIGHT),
            ("Eco", None, None),
        ],
    )
    def test_each_mode_gives_the_windows_it_pauses(self, mode, discharge, charge):
        assert pause_window(mode, "23:00:00", "08:00:00") == discharge
        assert charge_pause_window(mode, "23:00:00", "08:00:00") == charge

    def test_a_charge_window_needs_two_times(self):
        assert charge_pause_window("PauseCharge", None, "08:00:00") is None
        assert charge_pause_window("PauseBoth", "23:00:00", "23:00:00") is None


class TestTheTimes:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("23:00:00", time(23, 0)),
            ("08:00", time(8, 0)),
            ("8:05", time(8, 5)),
            ("00:00:00", time(0, 0)),
            ("23:59:00", time(23, 59)),
            ("24:00:00", None),
            ("25:00", None),
            ("12:60:00", None),
            ("noon", None),
            ("unavailable", None),
            ("", None),
            (None, None),
        ],
    )
    def test_a_clock_time(self, text, expected):
        assert parse_clock(text) == expected


class TestTheWindow:
    @pytest.mark.parametrize(
        ("mode", "start", "end", "expected"),
        [
            ("PauseDischarge", "23:00:00", "08:00:00", NIGHT),
            ("PauseBoth", "23:00:00", "08:00:00", NIGHT),
            ("PauseDischarge", "09:00:00", "11:30:00", PauseWindow(time(9, 0), time(11, 30))),
            ("Disabled", "23:00:00", "08:00:00", None),
            ("PauseCharge", "23:00:00", "08:00:00", None),
            ("Eco", "23:00:00", "08:00:00", None),
            (None, "23:00:00", "08:00:00", None),
            ("PauseDischarge", None, "08:00:00", None),
            ("PauseDischarge", "23:00:00", None, None),
            ("PauseDischarge", "late", "08:00:00", None),
            ("PauseDischarge", "23:00:00", "08:00:00", NIGHT),
            ("PauseDischarge", "08:00:00", "08:00:00", None),
            ("PauseDischarge", "00:00:00", "00:00:00", None),
        ],
    )
    def test_the_window_from_the_three_states(self, mode, start, end, expected):
        assert pause_window(mode, start, end) == expected


# ── The reader, on every fixture system ─────────────────────────────────────

# Fixtures whose entity list has the pause entities, whose mode is PauseDischarge from 23:00 to
# 08:00 (the one real hybrid, and the rest built from it).
WITH_PAUSE = [
    "ac_coupled_3_6_3",
    "all_in_one_3_6_3",
    "all_in_one_and_gateway_3_6_3",
    "gateway_parallel_two_aio_3_6_3",
    "hv_gen3_after_3_6",
    "hv_gen3_before_3_6",
    "hybrid_custom_prefix_3_6_3",
    "hybrid_gen3_two_batteries_3_6_3",
    "hybrid_with_ev_charger_3_6_3",
    "hybrid_with_ghost_battery_3_6_3",
    "three_phase_3_6_3",
    "two_hybrids_3_6_3",
]
# Fixtures that have no pause entities at all.
WITHOUT_PAUSE = [
    "ems_3_6_3",
    "harness_ac",
    "harness_all_in_one",
    "harness_ems",
    "harness_hybrid_3ph",
    "harness_hybrid_gen1",
    "harness_hybrid_gen2",
    "harness_hybrid_hv_gen3",
]
# A fixture whose pause entities exist and report unknown, as GivTCP's own capture of a Gateway.
UNKNOWN_PAUSE = ["harness_gateway"]
# A charger on its own has no inverter, so there is nothing to read the pause from.
NO_INVERTER = ["givenergy_charger_only"]


def test_every_fixture_is_listed_once():
    listed = WITH_PAUSE + WITHOUT_PAUSE + UNKNOWN_PAUSE + NO_INVERTER

    assert sorted(listed) == fixtures.names()


def _device(name: str):
    """The fixture's states and the config the reader needs for the inverter it would manage."""
    states = fixtures.states(name)
    controller = select_controller(
        [i.facts() for i in discover_givtcp_inverters(states)]
    ).controller
    prefix = controller.prefix
    cfg = {
        CONF_INVERTER_SERIAL: controller.serial,
        CONF_SOLAR_POWER: f"sensor.{prefix}_pv_power",
        CONF_BATTERY_POWER: f"sensor.{prefix}_battery_power",
    }
    return states, cfg, prefix


def _read(states, cfg):
    return GivTCPReader(states.get).read(cfg).battery_pause


def _set(states, entity_id, state):
    states[entity_id] = SimpleNamespace(state=state, attributes={})


@pytest.mark.parametrize("name", WITH_PAUSE)
class TestASystemWithAPause:
    def test_the_window_is_read(self, name):
        states, cfg, _ = _device(name)

        assert _read(states, cfg) == NIGHT

    def test_a_pause_that_is_off_gives_none(self, name):
        states, cfg, prefix = _device(name)
        _set(states, battery_pause_entities(prefix).mode, "Disabled")

        assert _read(states, cfg) is None

    def test_a_pause_that_only_stops_charging_is_no_discharge_pause(self, name):
        states, cfg, prefix = _device(name)
        _set(states, battery_pause_entities(prefix).mode, "PauseCharge")

        values = GivTCPReader(states.get).read(cfg)

        assert values.battery_pause is None
        assert values.charge_pause == NIGHT

    def test_a_pause_that_stops_both_gives_both_windows(self, name):
        states, cfg, prefix = _device(name)
        _set(states, battery_pause_entities(prefix).mode, "PauseBoth")

        values = GivTCPReader(states.get).read(cfg)

        assert values.battery_pause == NIGHT
        assert values.charge_pause == NIGHT

    def test_a_discharge_pause_is_no_charge_pause(self, name):
        states, cfg, _ = _device(name)

        assert GivTCPReader(states.get).read(cfg).charge_pause is None

    def test_a_pause_that_is_off_has_no_charge_pause_either(self, name):
        states, cfg, prefix = _device(name)
        _set(states, battery_pause_entities(prefix).mode, "Disabled")

        assert GivTCPReader(states.get).read(cfg).charge_pause is None

    def test_unavailable_entities_give_none(self, name):
        states, cfg, prefix = _device(name)
        entities = battery_pause_entities(prefix)
        for entity_id in (entities.mode, *entities.start, *entities.end):
            if entity_id in states:
                _set(states, entity_id, "unavailable")

        assert _read(states, cfg) is None

    def test_a_missing_mode_gives_none(self, name):
        states, cfg, prefix = _device(name)
        del states[battery_pause_entities(prefix).mode]

        assert _read(states, cfg) is None


@pytest.mark.parametrize("name", WITHOUT_PAUSE + UNKNOWN_PAUSE)
def test_a_system_with_no_readable_pause_has_none(name):
    states, cfg, _ = _device(name)

    assert _read(states, cfg) is None
    assert GivTCPReader(states.get).read(cfg).charge_pause is None


def test_the_real_hybrid_publishes_the_three_entities_as_the_reader_expects():
    states, _, prefix = _device("hybrid_gen3_two_batteries_3_6_3")
    entities = battery_pause_entities(prefix)

    assert states[entities.mode].state == "PauseDischarge"
    assert states[entities.start[0]].state == "23:00:00"
    assert states[entities.end[0]].state == "08:00:00"


class TestWhereTheTimesAre:
    def test_a_system_that_publishes_only_the_time_pickers_is_read(self):
        states, cfg, prefix = _device("hybrid_gen3_two_batteries_3_6_3")
        entities = battery_pause_entities(prefix)
        for select_id in (entities.start[0], entities.end[0]):
            del states[select_id]

        assert _read(states, cfg) == NIGHT

    def test_the_select_is_read_first_and_the_time_picker_is_the_fallback(self):
        states, cfg, prefix = _device("hybrid_gen3_two_batteries_3_6_3")
        entities = battery_pause_entities(prefix)
        _set(states, entities.start[0], "22:00:00")
        _set(states, entities.end[1], "unavailable")

        assert _read(states, cfg) == PauseWindow(time(22, 0), time(8, 0))

    def test_an_unavailable_select_falls_back_to_the_time_picker(self):
        states, cfg, prefix = _device("hybrid_gen3_two_batteries_3_6_3")
        entities = battery_pause_entities(prefix)
        _set(states, entities.start[0], "unavailable")

        assert _read(states, cfg) == NIGHT

    def test_a_system_without_the_start_gives_none(self):
        states, cfg, prefix = _device("hybrid_gen3_two_batteries_3_6_3")
        for entity_id in battery_pause_entities(prefix).start:
            del states[entity_id]

        assert _read(states, cfg) is None


class TestAPauseThatComesAndGoes:
    """The pause is read again on every read, so one added later is found and one removed is gone."""

    def test_added_later_is_found_and_removed_is_dropped(self):
        states, cfg, prefix = _device("hybrid_gen3_two_batteries_3_6_3")
        entities = battery_pause_entities(prefix)
        pause_states = {
            entity_id: states.pop(entity_id)
            for entity_id in (entities.mode, *entities.start, *entities.end)
        }
        reader = GivTCPReader(states.get)

        assert reader.read(cfg).battery_pause is None

        states.update(pause_states)
        assert reader.read(cfg).battery_pause == NIGHT

        for entity_id in pause_states:
            del states[entity_id]
        assert reader.read(cfg).battery_pause is None

    def test_a_window_that_moves_is_read_again(self):
        states, cfg, prefix = _device("hybrid_gen3_two_batteries_3_6_3")
        reader = GivTCPReader(states.get)
        entities = battery_pause_entities(prefix)

        _set(states, entities.end[0], "06:30:00")

        assert reader.read(cfg).battery_pause == PauseWindow(time(23, 0), time(6, 30))

    def test_a_config_without_a_prefix_has_no_pause(self):
        states, _, _ = _device("hybrid_gen3_two_batteries_3_6_3")

        assert GivTCPReader(states.get).read({}).battery_pause is None


class TestAnOptionTheReaderDoesNotKnow:
    def test_it_gives_no_pause_and_says_so_once(self, caplog):
        states, cfg, prefix = _device("hybrid_gen3_two_batteries_3_6_3")
        _set(states, battery_pause_entities(prefix).mode, "PauseNightly")
        reader = GivTCPReader(states.get)

        with caplog.at_level(logging.WARNING):
            first = reader.read(cfg).battery_pause
            second = reader.read(cfg).battery_pause

        assert first is None and second is None
        warnings = [r for r in caplog.records if "PauseNightly" in r.getMessage()]
        assert len(warnings) == 1

    def test_a_known_option_says_nothing(self, caplog):
        states, cfg, _ = _device("hybrid_gen3_two_batteries_3_6_3")

        with caplog.at_level(logging.WARNING):
            GivTCPReader(states.get).read(cfg)

        assert not [r for r in caplog.records if "pause" in r.getMessage().lower()]
