"""The test instance marker file makes the whole integration read dry run.

The real Home Assistant checks (the file in the config folder, the switch, the sensor, the
diagnostics download) are in tests/ha_e2e/test_test_instance_e2e.py. Here the coordinator is
the real class over test doubles, so every write site is checked with the saved option off.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_DRY_RUN,
    CONF_IMMERSION_SWITCH,
    TEST_INSTANCE_MARKER,
)
from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision
from custom_components.givenergy_inverter_manager.discovery import (
    EVCharger,
    EVChargerBrand,
    EVChargerState,
)
from custom_components.givenergy_inverter_manager.repairs import ClearOutcome
from custom_components.givenergy_inverter_manager.sensor_values import dry_run_attributes
from tests.conftest import _raw
from tests.test_charge_slot_repair import _coord
from tests.test_coordinator import FakeCoordinator, _cfg, _default_states, _write_coord


def _test_instance(**cfg_overrides) -> FakeCoordinator:
    """A coordinator whose saved dry run option is off, on a test instance."""
    coord = FakeCoordinator(cfg=_cfg(**{CONF_DRY_RUN: False, **cfg_overrides}))
    coord.test_instance = True
    coord.set_states(_default_states())
    return coord


def _decision() -> ChargeDecision:
    return ChargeDecision(
        target_soc=80,
        skip_charge=False,
        reason="test",
        forecast_kwh=10.0,
        current_soc=60.0,
        battery_capacity=19.0,
        car_plugged_in=False,
        cost_to_charge=1.0,
    )


class TestTheMarkerForcesDryRun:
    def test_dry_run_is_true_whatever_the_saved_option_says(self):
        coord = _test_instance()
        assert coord.entry.data[CONF_DRY_RUN] is False
        assert coord.is_dry_run is True

    def test_the_merged_config_every_reader_uses_says_dry_run(self):
        assert _test_instance()._effective_cfg()[CONF_DRY_RUN] is True

    def test_without_the_marker_the_saved_option_rules(self):
        coord = FakeCoordinator(cfg=_cfg(**{CONF_DRY_RUN: False}))
        assert coord.test_instance is False
        assert coord.is_dry_run is False
        coord.entry.data = {**coord.entry.data, CONF_DRY_RUN: True}
        assert coord.is_dry_run is True

    @pytest.mark.asyncio
    async def test_the_snapshot_reads_dry_run_and_carries_the_flag(self):
        data = await _test_instance().run_cycle()
        assert data.dry_run is True
        assert data.test_instance is True

    @pytest.mark.asyncio
    async def test_without_the_marker_the_snapshot_reads_the_saved_option(self):
        coord = FakeCoordinator(cfg=_cfg(**{CONF_DRY_RUN: False}))
        coord.set_states(_default_states())
        data = await coord.run_cycle()
        assert data.dry_run is False
        assert data.test_instance is False

    def test_the_sensor_attributes_flag_a_test_instance_and_no_other(self):
        on = SimpleNamespace(dry_run=True, test_instance=True)
        saved = SimpleNamespace(dry_run=True, test_instance=False)
        assert dry_run_attributes(on) == {"summary": "On", "test_instance": True}
        assert dry_run_attributes(saved) == {"summary": "On"}


class TestEveryWriteSiteSendsNothing:
    def test_the_charge_target_write_sends_nothing(self):
        coord = _test_instance()
        coord.data = MagicMock()
        coord.data.charge_decision = _decision()
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        assert coord.tasks_created == []
        assert coord.service_calls == []
        assert coord._dry_run_last_skipped.startswith("Would write charge target 80%")

    @pytest.mark.asyncio
    async def test_the_cheap_rate_floor_top_up_sends_nothing(self):
        coord, cfg = _write_coord(**{CONF_DRY_RUN: False})
        coord.test_instance = True
        now = datetime(2024, 7, 10, 2, 30, tzinfo=ZoneInfo("Europe/Dublin"))

        result = await coord._maybe_apply_cheap_rate_floor(
            now, _raw(battery_soc=20.0), coord._effective_cfg()
        )

        assert result.startswith("DRY RUN:")
        assert coord.service_calls == []

    def test_the_ev_mode_change_sends_nothing(self):
        coord = _test_instance()
        coord._ev_charger = EVCharger(
            brand=EVChargerBrand.ZAPPI,
            name="Zappi",
            serial="12345",
            display_name="Zappi 12345",
            state=EVChargerState.CHARGING,
            charge_mode="Fast",
            charge_mode_entity="select.zappi_mode",
        )
        coord.data = SimpleNamespace(dry_run_last_skipped="")
        coord._apply_ev_action("Stopped")
        assert coord.tasks_created == []
        assert coord.service_calls == []

    @pytest.mark.asyncio
    async def test_clearing_other_charge_slots_sends_nothing(self):
        coord = _coord(**{CONF_DRY_RUN: False})
        coord.test_instance = True

        outcome = await coord.async_clear_other_charge_slots()

        assert outcome is ClearOutcome.DRY_RUN
        assert coord.service_calls == []

    def test_the_immersion_switch_is_not_pressed(self):
        coord = _test_instance(**{CONF_IMMERSION_SWITCH: "switch.heater"})
        coord.set_state("switch.heater", "off")
        coord.data = SimpleNamespace(dry_run_last_skipped="")

        asyncio.run(coord.immersion.manual_on())

        assert coord.service_calls == []
        assert coord.tasks_created == []
        assert coord._dry_run_last_skipped


class FakeHass:
    """Just the two things the marker check uses: the config path and the executor."""

    def __init__(self, config_dir) -> None:
        self.config = SimpleNamespace(path=lambda name: os.path.join(config_dir, name))
        self.executor_jobs: list = []

    async def async_add_executor_job(self, func, *args):
        self.executor_jobs.append(func)
        return func(*args)


class TestFindingTheMarker:
    def _coord(self, tmp_path) -> FakeCoordinator:
        coord = FakeCoordinator(cfg=_cfg())
        coord.hass = FakeHass(str(tmp_path))
        return coord

    def test_the_file_is_found(self, tmp_path):
        (tmp_path / TEST_INSTANCE_MARKER).write_text("")
        coord = self._coord(tmp_path)
        asyncio.run(coord.async_detect_test_instance())
        assert coord.test_instance is True

    def test_no_file_is_no_test_instance(self, tmp_path):
        coord = self._coord(tmp_path)
        asyncio.run(coord.async_detect_test_instance())
        assert coord.test_instance is False

    def test_a_directory_of_that_name_still_counts_as_the_marker(self, tmp_path):
        """Only its presence is read, never its content."""
        (tmp_path / TEST_INSTANCE_MARKER).mkdir()
        coord = self._coord(tmp_path)
        asyncio.run(coord.async_detect_test_instance())
        assert coord.test_instance is True

    def test_the_file_is_looked_for_in_the_executor_not_the_event_loop(self, tmp_path):
        coord = self._coord(tmp_path)
        asyncio.run(coord.async_detect_test_instance())
        assert coord.hass.executor_jobs == [os.path.exists]

    def test_it_is_looked_for_once_then_remembered(self, tmp_path, monkeypatch):
        marker = tmp_path / TEST_INSTANCE_MARKER
        marker.write_text("")
        coord = self._coord(tmp_path)
        asyncio.run(coord.async_detect_test_instance())
        calls = []
        monkeypatch.setattr(os.path, "exists", lambda path: calls.append(path) or False)

        marker.unlink()
        for _ in range(3):
            assert coord.is_dry_run is True
            coord._effective_cfg()

        assert calls == []
        assert coord.test_instance is True

    def test_finding_it_logs_how_to_leave_test_mode(self, tmp_path, caplog):
        (tmp_path / TEST_INSTANCE_MARKER).write_text("")
        coord = self._coord(tmp_path)
        with caplog.at_level(logging.WARNING):
            asyncio.run(coord.async_detect_test_instance())
        message = next(r.getMessage() for r in caplog.records if "marker" in r.getMessage())
        assert TEST_INSTANCE_MARKER in message
        assert "Delete the file" in message
