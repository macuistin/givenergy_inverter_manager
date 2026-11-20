"""The EV command log: each command sent to the charger, with its time and result.

It proves what the integration sent to the Zappi and when, and which mode changes it did not
send. It is separate from the charge write log, is saved with the accumulation state and shows as
the recent_commands attribute of the EV Charger Mode Decision sensor.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.givenergy_inverter_manager.accumulation import (
    AccumulationState,
    _deserialize,
    _serialize,
)
from custom_components.givenergy_inverter_manager.const import EV_COMMAND_LOG_MAX_ENTRIES
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.discovery import (
    EVCharger,
    EVChargerBrand,
    EVChargerState,
)
from custom_components.givenergy_inverter_manager.sensor_values import ev_command_attributes
from custom_components.givenergy_inverter_manager.write_audit import WriteAudit
from tests.test_coordinator import FakeCoordinator, _cfg

MODE = "select.zappi_mode"
NOW = datetime(2026, 11, 20, 2, 0, 5, tzinfo=timezone.utc)


def _charger(mode="Eco+"):
    return EVCharger(
        brand=EVChargerBrand.ZAPPI,
        name="Zappi",
        serial="12345",
        display_name="Zappi 12345",
        state=EVChargerState.CONNECTED,
        charge_mode=mode,
        charge_mode_entity=MODE,
    )


def _coordinator(mode="Eco+", **cfg):
    coord = FakeCoordinator(cfg=_cfg(**cfg))
    coord._ev_charger = _charger(mode)
    coord._now = lambda: NOW
    coord.data = SimpleNamespace(dry_run_last_skipped="")
    return coord


def _log(coord):
    return coord._acc.state.ev_command_log


class TestCommandsSent:
    @pytest.mark.asyncio
    async def test_a_command_is_logged_with_time_entity_mode_and_reason(self):
        coord = _coordinator()
        coord._apply_ev_action("Fast", "Charge window — switching to Fast to charge the car")
        await coord.tasks_created[0]
        assert _log(coord) == [
            {
                "time": NOW.isoformat(),
                "entity_id": MODE,
                "value": "Fast",
                "reason": "sent: Charge window — switching to Fast to charge the car",
            }
        ]

    @pytest.mark.asyncio
    async def test_a_command_that_fails_is_logged_as_failed_and_not_as_sent(self):
        coord = _coordinator()

        async def refuse(domain, service, data):
            raise RuntimeError("the cloud said no")

        coord._call_service = refuse
        coord._apply_ev_action("Fast", "Charge window")
        with pytest.raises(RuntimeError):
            await coord.tasks_created[0]
        (entry,) = _log(coord)
        assert entry["value"] == "Fast"
        assert entry["reason"] == "failed (the cloud said no): Charge window"

    def test_nothing_is_logged_when_the_charger_is_already_in_the_mode(self):
        coord = _coordinator(mode="Fast")
        coord._apply_ev_action("Fast", "Charge window, already charging in Fast")
        assert _log(coord) == []
        assert coord.tasks_created == []

    def test_nothing_is_logged_without_a_decision(self):
        coord = _coordinator()
        coord._apply_ev_action(None, "no action")
        assert _log(coord) == []

    @pytest.mark.asyncio
    async def test_a_decision_the_cooldown_holds_back_is_logged_as_not_sent(self):
        coord = _coordinator(mode="Fast")
        coord._apply_ev_action("Eco+", "Charge window over — back to Eco+")
        await coord.tasks_created[0]
        coord._ev_charger = _charger("Fast")
        coord._apply_ev_action("Eco+", "Charge window over — back to Eco+")
        assert len(coord.tasks_created) == 1
        assert [e["reason"] for e in _log(coord)] == [
            "sent: Charge window over — back to Eco+",
            "not sent, cooldown: Charge window over — back to Eco+",
        ]

    def test_dry_run_is_logged_as_not_sent(self):
        coord = _coordinator(mode="Fast", dry_run=True)
        coord._apply_ev_action("Eco+", "Charge window over — back to Eco+")
        (entry,) = _log(coord)
        assert entry["value"] == "Eco+"
        assert entry["reason"] == "dry run, not sent"
        assert coord.tasks_created == []

    @pytest.mark.asyncio
    async def test_the_charge_write_log_is_left_alone(self):
        coord = _coordinator()
        coord._apply_ev_action("Fast", "Charge window")
        await coord.tasks_created[0]
        assert coord._acc.state.register_write_log == []


def _change(old, new, user_id=None, parent_id=None):
    def state(value):
        return SimpleNamespace(
            state=value, context=SimpleNamespace(user_id=user_id, parent_id=parent_id)
        )

    return SimpleNamespace(data={"entity_id": MODE, "old_state": state(old), "new_state": state(new)})


class TestOutsideChanges:
    @pytest.fixture
    def acc(self):
        return SimpleNamespace(state=AccumulationState(), schedule_save=MagicMock())

    @pytest.fixture
    def audit(self, acc):
        return WriteAudit(acc, now=lambda: NOW, log="ev_command_log", limit=50)

    def test_a_mode_change_the_integration_did_not_send_is_logged_as_external(self, audit, acc):
        audit._on_state_change(_change("Fast", "Eco+"))
        (entry,) = acc.state.ev_command_log
        assert entry["entity_id"] == MODE
        assert entry["value"] == "Eco+"
        assert entry["reason"] == "external"

    def test_the_context_of_an_outside_change_is_kept(self, audit, acc):
        audit._on_state_change(_change("Fast", "Stopped", user_id="abc", parent_id="def"))
        (entry,) = acc.state.ev_command_log
        assert entry["user_id"] == "abc"
        assert entry["parent_id"] == "def"

    def test_the_echo_of_a_command_the_integration_sent_is_not_an_outside_change(self, audit, acc):
        from custom_components.givenergy_inverter_manager.core.write_log import WriteRecord

        record = WriteRecord(MODE, "Fast", "Charge window")
        audit.before_write(record)
        audit.after_write(WriteRecord(MODE, "Fast", "sent: Charge window"))
        audit._on_state_change(_change("Eco+", "Fast"))
        assert [e["reason"] for e in acc.state.ev_command_log] == ["sent: Charge window"]

    def test_it_never_writes_into_the_charge_write_log(self, audit, acc):
        audit._on_state_change(_change("Fast", "Eco+"))
        assert acc.state.register_write_log == []


class TestWatching:
    def test_the_charger_mode_is_watched_once(self):
        coord = _coordinator()
        coord.entry = MagicMock()
        coord.hass = MagicMock()
        coord._ev_audit.watch = MagicMock()
        coord._watch_ev_mode(coord._ev_charger)
        coord._watch_ev_mode(coord._ev_charger)
        coord._ev_audit.watch.assert_called_once_with(coord.hass, [MODE])

    def test_a_charger_with_no_mode_entity_is_not_watched(self):
        coord = _coordinator()
        coord._ev_charger.charge_mode_entity = None
        coord._ev_audit.watch = MagicMock()
        coord._watch_ev_mode(coord._ev_charger)
        coord._ev_audit.watch.assert_not_called()


class TestKeptAndShown:
    def test_the_log_is_bounded(self):
        acc = SimpleNamespace(state=AccumulationState(), schedule_save=MagicMock())
        audit = WriteAudit(
            acc, now=lambda: NOW, log="ev_command_log", limit=EV_COMMAND_LOG_MAX_ENTRIES
        )
        for number in range(EV_COMMAND_LOG_MAX_ENTRIES + 7):
            audit.note(MODE, str(number), "x")
        assert len(acc.state.ev_command_log) == EV_COMMAND_LOG_MAX_ENTRIES
        assert acc.state.ev_command_log[-1]["value"] == str(EV_COMMAND_LOG_MAX_ENTRIES + 6)
        assert acc.state.ev_command_log[0]["value"] == "7"

    def test_the_log_survives_a_restart(self):
        state = AccumulationState()
        state.ev_command_log = [
            {"time": NOW.isoformat(), "entity_id": MODE, "value": "Fast", "reason": "sent: x"}
        ]
        assert _deserialize(_serialize(state)).ev_command_log == state.ev_command_log

    def test_a_missing_or_damaged_log_loads_empty(self):
        assert _deserialize({}).ev_command_log == []
        assert _deserialize({"ev_command_log": "oops"}).ev_command_log == []

    def test_the_sensor_shows_the_newest_command_first(self):
        data = CoordinatorData()
        data.ev_command_log = [{"value": "Fast"}, {"value": "Eco+"}]
        assert ev_command_attributes(data) == {
            "recent_commands": [{"value": "Eco+"}, {"value": "Fast"}]
        }
