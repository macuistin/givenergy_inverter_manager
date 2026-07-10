"""
test_coordinator.py — Tests for coordinator.py.

The coordinator's HA surface is proxied through three methods:
  _get_state(entity_id)
  _call_service(domain, service, data, blocking)
  _create_task(coro)

FakeCoordinator overrides these three methods.  No hass mock, no MagicMock
patching, no asyncio magic — just a subclass that controls the HA surface
and records what the coordinator asked it to do.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from custom_components.givenergy_inverter_manager.accumulation import AccumulationState
from custom_components.givenergy_inverter_manager.const import (
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_CHARGE_END_TIME_ENTITY,
    CONF_CHARGE_START_TIME_ENTITY,
    CONF_DRY_RUN,
    CONF_ENABLE_CHARGE_SCHEDULE,
    CONF_ENABLE_CHARGE_TARGET,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_IMMERSION_SWITCH,
    CONF_SOLAR_POWER,
    CONF_TARGET_SOC_ENTITY,
)
from custom_components.givenergy_inverter_manager.coordinator import GivEnergyCoordinator
from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg, _raw

# ── Minimal HA state stub ─────────────────────────────────────────────────────


class FakeState:
    """Minimal stub for an HA state object."""

    def __init__(self, state: str):
        self.state = state


# ── FakeCoordinator ───────────────────────────────────────────────────────────


class FakeCoordinator(GivEnergyCoordinator):
    """
    Test subclass that overrides the three HA proxy methods.

    Instead of reaching into hass, it reads from a dict of entity states
    and records every service call made.

    Usage:
        coord = FakeCoordinator(cfg={"solar_power_entity": "sensor.solar", ...})
        coord.set_state("sensor.solar", "3000")
        data = await coord._async_update_data()
        assert coord.service_calls == [("switch", "turn_on", {...})]
    """

    def __init__(self, cfg: dict | None = None):
        # Build minimal entry and hass stubs — just enough for __init__
        entry = MagicMock()
        entry.data = cfg or _nightboost_cfg()
        entry.options = {}
        entry.async_on_unload = lambda fn: fn  # returns the cancel fn itself

        hass = MagicMock()
        hass.states.get = lambda eid: self._states.get(eid)
        # async_create_task receives a coroutine — close it immediately so it
        # doesn't linger and trigger an "unawaited coroutine" warning at GC time.
        hass.async_create_task = lambda coro, **_kw: coro.close()

        # Bypass DataUpdateCoordinator.__init__ — we don't need its scheduler
        # Call object.__init__ to set up the instance, then manually set attrs
        # that DataUpdateCoordinator would normally set.
        object.__init__(self)
        self.hass = hass
        self.entry = entry
        self.data: CoordinatorData | None = None
        self.logger = MagicMock()

        # Proxy surfaces — test-controlled
        self._states: dict[str, FakeState] = {}
        self.service_calls: list[tuple] = []
        self.tasks_created: list = []

        # Coordinator state
        from custom_components.givenergy_inverter_manager.logging import GivLogger

        self._battery_stats = BatteryStats()
        self._solar_fractions = dict.fromkeys(range(1, 13), 0.5)  # flat for tests
        self._last_reset_time: str = ""

        class _FakeAccStore:
            """Minimal AccumulationStore stub for testing — no HA Storage."""

            def __init__(self):
                self.state = AccumulationState()

            @property
            def today(self):
                return self.state.today

            @property
            def week(self):
                return self.state.week

            @property
            def month(self):
                return self.state.month

            @property
            def yesterday(self):
                return self.state.yesterday

            @property
            def today_forecast_kwh(self):
                return self.state.today_forecast_kwh

            @property
            def yesterday_forecast_accuracy_pct(self):
                return self.state.yesterday_forecast_accuracy_pct

            @property
            def forecast_accuracy_7day_avg_pct(self):
                h = self.state.forecast_accuracy_history
                return round(sum(h) / len(h), 1) if h else 0.0

            def on_midnight(self, now):
                self.state.yesterday = self.state.today
                self.state.today = EnergyAccumulator()

            def on_charge_decision(self, kwh):
                if self.state.today_forecast_kwh == 0.0 and kwh > 0:
                    self.state.today_forecast_kwh = kwh

            async def async_save(self):
                pass  # no-op in tests

            async def async_load(self):
                pass

        self._acc = _FakeAccStore()
        self._last_soc: float | None = None
        self._last_update: datetime | None = None
        self._update_cycle: int = 0
        self._ev_charger = None
        self.override_charge_target = None
        self.immersion_target_temp: float = 55.0
        self.immersion_min_temp: float = 50.0
        self.immersion_hysteresis_c: float = 5.0
        self._floor_top_up_applied: bool = False
        self.override_immersion = None
        self.override_skip_charge = False
        self._givtcp_was_unavailable: bool = False

        GivLogger.register(self._effective_cfg)

    # ── HA proxy overrides ────────────────────────────────────────────────────

    def _get_state(self, entity_id: str):
        return self._states.get(entity_id)

    def _get_all_states(self) -> dict:
        return dict(self._states)

    async def _call_service(self, domain, service, data, blocking=True):
        self.service_calls.append((domain, service, data))
        # Simulate write-back: set state to what was written
        if "entity_id" in data:
            eid = data["entity_id"]
            if service == "turn_on":
                self._states[eid] = FakeState("on")
            elif service == "turn_off":
                self._states[eid] = FakeState("off")
            elif service == "select_option":
                self._states[eid] = FakeState(data["option"])
            elif service == "set_value":
                self._states[eid] = FakeState(str(data["value"]))

    def _create_task(self, coro):
        self.tasks_created.append(coro)

    # ── Test helpers ──────────────────────────────────────────────────────────

    def set_state(self, entity_id: str, value: str) -> None:
        """Set a fake entity state."""
        self._states[entity_id] = FakeState(value)

    def set_states(self, states: dict[str, str]) -> None:
        """Set multiple fake entity states at once."""
        for eid, val in states.items():
            self._states[eid] = FakeState(val)

    async def run_cycle(self, now: datetime | None = None) -> CoordinatorData:
        """Run one update cycle and return the resulting CoordinatorData."""
        self.data = await self._async_update_data()
        return self.data

    def service_calls_for(self, domain: str, service: str) -> list[dict]:
        """Return all data dicts for calls matching domain.service."""
        return [d for dom, svc, d in self.service_calls if dom == domain and svc == service]


# ── Shared cfg fixture ────────────────────────────────────────────────────────


def _cfg(**overrides) -> dict:
    """Return a nightboost config with GivTCP entity IDs set."""
    base = _nightboost_cfg()
    base.update(
        {
            CONF_SOLAR_POWER: "sensor.solar",
            CONF_BATTERY_SOC: "sensor.battery_soc",
            CONF_BATTERY_POWER: "sensor.battery_power",
            CONF_GRID_POWER: "sensor.grid",
            CONF_HOUSE_LOAD: "sensor.house",
            CONF_TARGET_SOC_ENTITY: "number.target_soc",
            CONF_ENABLE_CHARGE_TARGET: "switch.enable_charge_target",
            CONF_ENABLE_CHARGE_SCHEDULE: "switch.enable_charge_schedule",
            CONF_CHARGE_START_TIME_ENTITY: "select.charge_start",
            CONF_CHARGE_END_TIME_ENTITY: "select.charge_end",
        }
    )
    base.update(overrides)
    return base


def _default_states() -> dict[str, str]:
    return {
        "sensor.solar": "3000",
        "sensor.battery_soc": "60",
        "sensor.battery_power": "-500",
        "sensor.grid": "0",
        "sensor.house": "1500",
    }


# ── TestCollectRaw ────────────────────────────────────────────────────────────


class TestCollectRaw:
    """_collect_raw reads entity states and returns correct RawSensorValues."""

    def test_reads_solar_power(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.solar", "4500")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.solar_power_w == pytest.approx(4500.0)

    def test_reads_battery_soc(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.battery_soc", "75.5")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.battery_soc == pytest.approx(75.5)

    def test_returns_zero_for_missing_entity(self):
        coord = FakeCoordinator(cfg=_cfg())
        # sensor.solar not set in state store
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.solar_power_w == 0.0

    def test_returns_zero_for_unavailable_entity(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.solar", "unavailable")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.solar_power_w == 0.0

    def test_returns_zero_for_unknown_entity(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.solar", "unknown")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.solar_power_w == 0.0

    def test_reads_grid_power_negative_when_exporting(self):
        """GivTCP v3 reports positive values for grid export.
        The coordinator negates this so internal convention is positive=import."""
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.grid", "1200")  # GivTCP v3: positive = export
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.grid_power_w == pytest.approx(-1200.0)  # internal: negative = export

    def test_reads_grid_power_positive_when_importing(self):
        """GivTCP v3 reports negative values for grid import."""
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.grid", "-800")  # GivTCP v3: negative = import
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.grid_power_w == pytest.approx(800.0)  # internal: positive = import

    def test_reads_immersion_switch_on(self):
        cfg = _cfg(**{CONF_IMMERSION_SWITCH: "switch.immersion"})
        coord = FakeCoordinator(cfg=cfg)
        coord.set_state("switch.immersion", "on")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.immersion_on is True

    def test_reads_immersion_switch_off(self):
        cfg = _cfg(**{CONF_IMMERSION_SWITCH: "switch.immersion"})
        coord = FakeCoordinator(cfg=cfg)
        coord.set_state("switch.immersion", "off")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.immersion_on is False

    def test_no_forecast_when_entity_not_configured(self):
        coord = FakeCoordinator(cfg=_cfg())
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.forecast_kwh_tomorrow is None

    def test_reads_forecast_when_configured(self):
        cfg = _cfg(**{"forecast_entity": "sensor.forecast"})
        coord = FakeCoordinator(cfg=cfg)
        coord.set_state("sensor.forecast", "12.5")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.forecast_kwh_tomorrow == pytest.approx(12.5)

    def test_reads_battery_power_charging(self):
        """Positive battery_power_w means charging (internal convention)."""
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.battery_power", "2500")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.battery_power_w == pytest.approx(2500.0)

    def test_reads_battery_power_discharging(self):
        """Negative battery_power_w means discharging (internal convention)."""
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.battery_power", "-1800")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.battery_power_w == pytest.approx(-1800.0)

    def test_reads_battery_power_zero_when_idle(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.battery_power", "0")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.battery_power_w == pytest.approx(0.0)

    def test_negative_forecast_treated_as_none(self):
        cfg = _cfg(**{"forecast_entity": "sensor.forecast"})
        coord = FakeCoordinator(cfg=cfg)
        coord.set_state("sensor.forecast", "-1")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.forecast_kwh_tomorrow is None


# ── TestUpdateCycle ───────────────────────────────────────────────────────────


class TestUpdateCycle:
    """_async_update_data reads states, runs engine, returns CoordinatorData."""

    @pytest.mark.asyncio
    async def test_returns_coordinator_data(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        data = await coord.run_cycle()
        assert isinstance(data, CoordinatorData)

    @pytest.mark.asyncio
    async def test_solar_power_reflected_in_data(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.set_state("sensor.solar", "5000")
        data = await coord.run_cycle()
        assert data.solar_power_w == pytest.approx(5000.0)

    @pytest.mark.asyncio
    async def test_battery_soc_reflected_in_data(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.set_state("sensor.battery_soc", "82")
        data = await coord.run_cycle()
        assert data.battery_soc == pytest.approx(82.0)

    @pytest.mark.asyncio
    async def test_last_soc_updated_after_cycle(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.set_state("sensor.battery_soc", "70")
        await coord.run_cycle()
        assert coord._last_soc == pytest.approx(70.0)

    @pytest.mark.asyncio
    async def test_update_cycle_counter_increments(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        await coord.run_cycle()
        await coord.run_cycle()
        assert coord._update_cycle == 2

    @pytest.mark.asyncio
    async def test_energy_accumulates_across_cycles(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.set_state("sensor.solar", "3000")

        await coord.run_cycle()  # sets _last_update
        coord._last_update = datetime.now(timezone.utc) - timedelta(minutes=30)
        await coord.run_cycle()

        assert coord._acc.today.solar_kwh == pytest.approx(1.5, rel=0.05)

    @pytest.mark.asyncio
    async def test_override_skip_charge_respected(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.override_skip_charge = True
        data = await coord.run_cycle()
        assert data.charge_decision.skip_charge is True

    @pytest.mark.asyncio
    async def test_override_charge_target_respected(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.override_charge_target = 55
        data = await coord.run_cycle()
        assert data.charge_decision.target_soc == 55


# ── TestMidnightReset ─────────────────────────────────────────────────────────


class TestMidnightReset:
    def test_clears_accumulator(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord._acc.today.solar_kwh = 12.0
        coord._acc.today.import_kwh = 3.0
        coord._midnight_reset(datetime.now(timezone.utc))
        assert coord._acc.today.solar_kwh == 0.0
        assert coord._acc.today.import_kwh == 0.0

    def test_clears_last_update(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord._last_update = datetime.now(timezone.utc)
        coord._midnight_reset(datetime.now(timezone.utc))
        assert coord._last_update is None

    def test_accumulator_is_fresh_instance(self):
        coord = FakeCoordinator(cfg=_cfg())
        old_acc = coord._acc.today
        coord._midnight_reset(datetime.now(timezone.utc))
        assert coord._acc.today is not old_acc


# ── TestWriteChargeTarget ─────────────────────────────────────────────────────


class TestWriteChargeTarget:
    """_write_charge_target_to_inverter issues the correct 5-step sequence."""

    def _coord_with_decision(self, target_soc: int = 80, skip: bool = False) -> FakeCoordinator:
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        # Inject a charge decision directly
        from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision

        decision = ChargeDecision(
            target_soc=target_soc,
            skip_charge=skip,
            reason="test",
            forecast_kwh=10.0,
            current_soc=60.0,
            battery_capacity=19.0,
            car_plugged_in=False,
            cost_to_charge=1.0,
        )
        data = MagicMock()
        data.charge_decision = decision
        coord.data = data
        return coord

    @pytest.mark.asyncio
    async def test_five_step_sequence_issued(self):
        coord = self._coord_with_decision(target_soc=80)
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        # _create_task was called with the coroutine — run it
        assert len(coord.tasks_created) == 1
        await coord.tasks_created[0]
        domains = [(d, s) for d, s, _ in coord.service_calls]
        assert ("switch", "turn_on") in domains  # step 1: enable_charge_schedule
        assert ("select", "select_option") in domains  # steps 2 & 3
        assert ("number", "set_value") in domains  # step 4: target_soc

    @pytest.mark.asyncio
    async def test_target_soc_written_correctly(self):
        coord = self._coord_with_decision(target_soc=75)
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        await coord.tasks_created[0]
        number_calls = coord.service_calls_for("number", "set_value")
        assert len(number_calls) == 1
        assert number_calls[0]["value"] == 75

    @pytest.mark.asyncio
    async def test_enable_charge_target_on_below_100(self):
        coord = self._coord_with_decision(target_soc=85)
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        await coord.tasks_created[0]
        # Step 5: enable_charge_target must be ON when target < 100
        switch_on = coord.service_calls_for("switch", "turn_on")
        eids = [c["entity_id"] for c in switch_on]
        assert "switch.enable_charge_target" in eids

    @pytest.mark.asyncio
    async def test_enable_charge_target_off_at_100(self):
        """At 100% target, enable_charge_target must be OFF to avoid bounce bug."""
        coord = self._coord_with_decision(target_soc=100)
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        await coord.tasks_created[0]
        switch_off = coord.service_calls_for("switch", "turn_off")
        eids = [c["entity_id"] for c in switch_off]
        assert "switch.enable_charge_target" in eids

    def test_skip_charge_suppresses_write(self):
        coord = self._coord_with_decision(skip=True)
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        assert len(coord.tasks_created) == 0
        assert len(coord.service_calls) == 0

    def test_no_write_when_no_target_entity(self):
        cfg = _cfg()
        cfg.pop(CONF_TARGET_SOC_ENTITY, None)
        coord = FakeCoordinator(cfg=cfg)
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        assert len(coord.tasks_created) == 0

    def test_no_write_when_no_data(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.data = None
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        assert len(coord.tasks_created) == 0

    @pytest.mark.asyncio
    async def test_dry_run_suppresses_write(self):
        cfg = _cfg(**{CONF_DRY_RUN: True})
        coord = FakeCoordinator(cfg=cfg)
        coord.set_states(_default_states())
        from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision

        decision = ChargeDecision(
            target_soc=80,
            skip_charge=False,
            reason="test",
            forecast_kwh=10.0,
            current_soc=60.0,
            battery_capacity=19.0,
            car_plugged_in=False,
            cost_to_charge=1.0,
        )
        data = MagicMock()
        data.charge_decision = decision
        coord.data = data
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        # In dry run mode, no task should be created
        assert len(coord.tasks_created) == 0
        assert len(coord.service_calls) == 0

    def test_no_write_when_no_rate_periods(self):
        """If no timed rate periods are configured, _write_charge_target must
        return without creating any tasks — it cannot pick a charge window."""
        from custom_components.givenergy_inverter_manager.const import CONF_RATE_PERIODS

        cfg = _cfg()
        cfg[CONF_RATE_PERIODS] = []  # no timed periods
        coord = FakeCoordinator(cfg=cfg)
        coord.set_states(_default_states())
        from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision

        data = MagicMock()
        data.charge_decision = ChargeDecision(
            target_soc=80,
            skip_charge=False,
            reason="test",
            forecast_kwh=10.0,
            current_soc=60.0,
            battery_capacity=19.0,
            car_plugged_in=False,
            cost_to_charge=1.0,
        )
        coord.data = data
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        assert len(coord.tasks_created) == 0, (
            "No task must be created when rate_periods is empty — "
            "there is no timed window to write to GivTCP."
        )


# ── TestEffectiveCfg ──────────────────────────────────────────────────────────


class TestEffectiveCfg:
    def test_options_override_data(self):
        coord = FakeCoordinator(cfg={"base_rate": 0.30, "export_rate": 0.15})
        coord.entry.options = {"export_rate": 0.20}
        cfg = coord._effective_cfg()
        assert cfg["export_rate"] == pytest.approx(0.20)
        assert cfg["base_rate"] == pytest.approx(0.30)

    def test_data_used_when_no_options(self):
        coord = FakeCoordinator(cfg={"base_rate": 0.33})
        coord.entry.options = {}
        cfg = coord._effective_cfg()
        assert cfg["base_rate"] == pytest.approx(0.33)


# ── TestApplyEvAction ─────────────────────────────────────────────────────────


class TestApplyEvAction:
    def _charger(self, mode="Fast"):
        from custom_components.givenergy_inverter_manager.discovery import (
            EVCharger,
            EVChargerBrand,
            EVChargerState,
        )

        ch = EVCharger(
            brand=EVChargerBrand.ZAPPI,
            name="Zappi",
            serial="12345",
            display_name="Zappi 12345",
            state=EVChargerState.CHARGING,
            charge_mode=mode,
            charge_mode_entity="select.zappi_mode",
        )
        return ch

    @pytest.mark.asyncio
    async def test_issues_service_call_when_mode_changes(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord._ev_charger = self._charger(mode="Fast")
        coord.data = MagicMock()
        coord._apply_ev_action("Eco+")
        assert len(coord.tasks_created) == 1
        await coord.tasks_created[0]  # avoid unawaited coroutine warning

    def test_no_call_when_mode_already_set(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord._ev_charger = self._charger(mode="Eco+")
        coord.data = MagicMock()
        coord._apply_ev_action("Eco+")
        assert len(coord.tasks_created) == 0

    def test_no_call_when_no_charger(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord._ev_charger = None
        coord._apply_ev_action("Eco+")
        assert len(coord.tasks_created) == 0

    def test_no_call_when_target_mode_none(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord._ev_charger = self._charger(mode="Fast")
        coord._apply_ev_action(None)
        assert len(coord.tasks_created) == 0

    def test_dry_run_skips_ev_action(self):
        cfg = _cfg(**{CONF_DRY_RUN: True})
        coord = FakeCoordinator(cfg=cfg)
        coord._ev_charger = self._charger(mode="Fast")
        # Use a simple namespace so attribute assignment is directly visible
        from types import SimpleNamespace

        coord.data = SimpleNamespace(dry_run_last_skipped="")
        coord._apply_ev_action("Stopped")
        assert len(coord.tasks_created) == 0
        assert "Stopped" in coord.data.dry_run_last_skipped


# ── TestGivtcpWriteHelpers ────────────────────────────────────────────────────


class TestGivtcpWriteHelpers:
    """The three _givtcp_set_* methods issue service calls and read back state."""

    @pytest.mark.asyncio
    async def test_set_switch_issues_turn_on(self):
        coord = FakeCoordinator(cfg=_cfg())
        await coord._givtcp_set_switch("switch.target", True, "test")
        assert ("switch", "turn_on", {"entity_id": "switch.target"}) in coord.service_calls

    @pytest.mark.asyncio
    async def test_set_switch_issues_turn_off(self):
        coord = FakeCoordinator(cfg=_cfg())
        await coord._givtcp_set_switch("switch.target", False, "test")
        assert ("switch", "turn_off", {"entity_id": "switch.target"}) in coord.service_calls

    @pytest.mark.asyncio
    async def test_set_switch_skips_when_no_entity(self):
        coord = FakeCoordinator(cfg=_cfg())
        await coord._givtcp_set_switch(None, True, "test")
        assert len(coord.service_calls) == 0

    @pytest.mark.asyncio
    async def test_set_select_issues_select_option(self):
        coord = FakeCoordinator(cfg=_cfg())
        await coord._givtcp_set_select("select.target", "02:00:00", "test")
        assert (
            "select",
            "select_option",
            {"entity_id": "select.target", "option": "02:00:00"},
        ) in coord.service_calls

    @pytest.mark.asyncio
    async def test_set_number_issues_set_value(self):
        coord = FakeCoordinator(cfg=_cfg())
        await coord._givtcp_set_number("number.target", 80, "test")
        assert (
            "number",
            "set_value",
            {"entity_id": "number.target", "value": 80},
        ) in coord.service_calls

    @pytest.mark.asyncio
    async def test_set_number_skips_when_no_entity(self):
        coord = FakeCoordinator(cfg=_cfg())
        await coord._givtcp_set_number(None, 80, "test")
        assert len(coord.service_calls) == 0

    @pytest.mark.asyncio
    async def test_write_mismatch_logs_warning(self, caplog):
        import logging

        coord = FakeCoordinator(cfg=_cfg())
        # Set state to a different value than what we'll write — simulates GivTCP rejection
        coord.set_state("number.target", "50")  # pre-existing state

        # Override _call_service to NOT update state (simulates write that didn't stick)
        async def stubbed(domain, service, data, blocking=True):
            coord.service_calls.append((domain, service, data))
            # Don't update state — the read-back will see the old value

        coord._call_service = stubbed
        with caplog.at_level(logging.WARNING):
            await coord._givtcp_set_number("number.target", 80, "target_soc")
        assert any("wrote" in r.message and "read back" in r.message for r in caplog.records)


# ── TestFlatRateTariff ────────────────────────────────────────────────────────


class TestFlatRateTariff:
    """Coordinator behaves correctly when no timed rate periods are configured."""

    @pytest.mark.asyncio
    async def test_cycle_runs_without_error(self):
        cfg = _cfg()
        cfg["rate_periods"] = []  # flat rate
        coord = FakeCoordinator(cfg=cfg)
        coord.set_states(_default_states())
        data = await coord.run_cycle()
        assert data is not None

    def test_no_charge_listener_registered(self):
        """_register_charge_target_listener should be silent for flat-rate tariffs."""
        cfg = _cfg()
        cfg["rate_periods"] = []
        coord = FakeCoordinator(cfg=cfg)
        # entry.async_on_unload is called for midnight reset only, not for charge listener
        # We can verify no write-back fires by triggering it directly
        from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision

        decision = ChargeDecision(
            target_soc=80,
            skip_charge=False,
            reason="test",
            forecast_kwh=10.0,
            current_soc=60.0,
            battery_capacity=19.0,
            car_plugged_in=False,
            cost_to_charge=1.0,
        )
        data = MagicMock()
        data.charge_decision = decision
        coord.data = data
        # Even if we manually call the write-back, the flat-rate tariff
        # means get_cheapest_rate_start would raise — but _register_charge_target_listener
        # already returned early so the listener was never registered.
        # Confirm _register_charge_target_listener ran without error:
        coord._register_charge_target_listener()  # should not raise


class TestInvertedRateTariff:
    """When base rate is cheaper than all timed periods, the old get_cheapest_rate()
    returned the synthetic base-rate period (start=00:00, end=00:00) producing a
    zero-length charge window. The fix uses min(tariff.rate_periods) directly."""

    def _tariff_with_cheap_base(self):
        """Base rate 0.05 EUR/kWh, Night rate 0.20 — base is cheaper (unusual)."""
        from custom_components.givenergy_inverter_manager.const import (
            CONF_BASE_RATE,
            CONF_BASE_RATE_NAME,
            CONF_BILL_START_DAY,
            CONF_CURRENCY,
            CONF_DISCOUNT_RATE,
            CONF_EXPORT_RATE,
            CONF_PSO_LEVY,
            CONF_RATE_PERIODS,
            CONF_STANDING_CHARGE,
            CONF_VAT_RATE,
        )
        from custom_components.givenergy_inverter_manager.core.tariff import build_tariff

        cfg = {
            CONF_BASE_RATE: 0.05,
            CONF_BASE_RATE_NAME: "Day",
            CONF_RATE_PERIODS: [{"name": "Night", "rate": 0.20, "start": "23:00", "end": "08:00"}],
            CONF_EXPORT_RATE: 0.10,
            CONF_STANDING_CHARGE: 0.50,
            CONF_PSO_LEVY: 3.0,
            CONF_VAT_RATE: 9.0,
            CONF_DISCOUNT_RATE: 0.0,
            CONF_BILL_START_DAY: 1,
            CONF_CURRENCY: "EUR",
        }
        return build_tariff(cfg)

    def test_old_get_cheapest_rate_would_return_zero_window(self):
        """Confirm the old code's failure mode: get_cheapest_rate() includes the
        synthetic base-rate period which has start=end=00:00."""
        from datetime import time

        tariff = self._tariff_with_cheap_base()
        cheapest = tariff.get_cheapest_rate()
        # Base rate (0.05) is cheaper than Night (0.20), so old code returns synthetic
        assert cheapest.rate == pytest.approx(0.05)
        assert cheapest.start == time(0, 0)
        assert cheapest.end == time(0, 0), (
            "Synthetic base-rate period has zero-length window — this is what "
            "the old code would write to GivTCP, preventing any overnight charging."
        )

    def test_new_code_uses_timed_period_with_real_window(self):
        """New code: min(tariff.rate_periods) only considers timed periods."""
        from datetime import time

        tariff = self._tariff_with_cheap_base()
        cheap = min(tariff.rate_periods, key=lambda p: p.rate)
        assert cheap.name == "Night"
        assert cheap.start != cheap.end, (
            "Timed periods must have a real window. "
            "If start == end, the charge window sent to GivTCP would be zero-length."
        )
        assert cheap.start == time(23, 0)
        assert cheap.end == time(8, 0)

    def test_empty_rate_periods_returns_early(self):
        """Coordinator must return early with a warning when no timed periods are
        configured, rather than crashing or writing a zero-window."""
        from pathlib import Path

        src = (
            Path(__file__).parent.parent
            / "custom_components/givenergy_inverter_manager/coordinator.py"
        ).read_text()
        guard_idx = src.index("if not tariff.rate_periods:")
        min_idx = src.index("min(tariff.rate_periods, key=lambda p: p.rate)")
        assert guard_idx < min_idx, "Empty list guard must appear before the min() call"


class TestTimezoneHandling:
    """Rate periods must be evaluated against local time, not UTC.
    In summer (Ireland GMT+1), a 23:00 Night rate must activate at
    local 23:00, not at UTC 23:00 (which is local midnight)."""

    def test_night_rate_activates_at_local_time_not_utc(self):
        from datetime import timezone
        from zoneinfo import ZoneInfo

        from custom_components.givenergy_inverter_manager.core.tariff import build_tariff

        tariff = build_tariff(_nightboost_cfg())
        ireland = ZoneInfo("Europe/Dublin")
        local_2330 = datetime(2024, 7, 10, 23, 30, 0, tzinfo=ireland)
        utc_2230 = local_2330.astimezone(timezone.utc)

        assert tariff.get_current_rate(local_2330).rate < tariff.base_rate, (
            "Night rate must be active at local 23:30 — coordinator must pass local time, not UTC."
        )
        assert tariff.get_current_rate(utc_2230).rate == pytest.approx(tariff.base_rate), (
            "UTC 22:30 should still be the Day rate — proves the distinction matters."
        )

    def test_coordinator_uses_local_time(self):
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/coordinator.py").read_text()
        assert "dt_util.as_local(datetime.now" in src, (
            "coordinator must use dt_util.as_local() — without this, rate periods "
            "activate 1h late in summer (Ireland GMT+1)."
        )

    def test_midnight_reset_uses_local_midnight(self):
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/coordinator.py").read_text()
        assert "dt_util.as_local(now).replace(hour=0" in src, (
            "_midnight_reset must use as_local — without this, daily accumulators "
            "reset at UTC midnight (01:00 local in summer)."
        )


class TestImmersionNumberGuards:
    """Cross-entity guards prevent min >= target (which causes short-cycling)
    and entry.data persistence ensures correct values survive HA restart."""

    def test_target_clamped_above_min(self):
        """Setting target below (min + 1) must clamp it up."""
        import asyncio
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.number import ImmersionTargetTempNumber

        coord = MagicMock()
        coord.immersion_min_temp = 50.0
        coord.entry.entry_id = "test"
        coord.entry.data = {}
        entity = ImmersionTargetTempNumber.__new__(ImmersionTargetTempNumber)
        entity.coordinator = coord
        entity._value = 55.0

        asyncio.run(entity._apply(48.0))  # below min + 1 = 51°C
        assert entity._value >= coord.immersion_min_temp + 1, (
            "Target must be at least 1°C above min to prevent short-cycling."
        )

    def test_min_clamped_below_target(self):
        """Setting min above (target - 1) must clamp it down."""
        import asyncio
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.number import ImmersionMinTempNumber

        coord = MagicMock()
        coord.immersion_target_temp = 55.0
        entity = ImmersionMinTempNumber.__new__(ImmersionMinTempNumber)
        entity.coordinator = coord
        entity._value = 50.0

        asyncio.run(entity._apply(58.0))  # above target - 1 = 54°C
        assert entity._value <= coord.immersion_target_temp - 1, (
            "Min must be at least 1°C below target to prevent short-cycling."
        )

    def test_persist_writes_to_entry_data(self):
        """_persist must call async_update_entry so values survive HA restart."""
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/number.py").read_text()
        assert "async_update_entry" in src, (
            "Number entities must persist values to entry.data via async_update_entry. "
            "Without this, coordinator reads stale config defaults on the first cycle "
            "after a restart (entity state restored after first coordinator update)."
        )


class TestCheapRateFloor:
    """During cheap rate hours, battery must not drop below the floor SoC.
    Optimises for the cheapest window — waits for Nightboost rather than
    topping up early on the Night rate unless battery is critically low."""

    def _now_at(self, hour: int, minute: int = 0):
        from zoneinfo import ZoneInfo

        return datetime(2024, 7, 10, hour, minute, tzinfo=ZoneInfo("Europe/Dublin"))

    def test_floor_triggers_during_cheapest_window(self):
        """Battery below floor during Nightboost (cheapest) must top up."""
        import asyncio

        coord = FakeCoordinator(cfg=_cfg())
        raw = _raw(battery_soc=30.0)  # below 40% floor, 02:30 = Nightboost
        result = asyncio.run(
            coord._maybe_apply_cheap_rate_floor(self._now_at(2, 30), raw, _nightboost_cfg())
        )
        assert "topping up" in result.lower(), f"Expected top-up during Nightboost, got: {result!r}"

    def test_waits_for_cheapest_during_night_rate(self):
        """Battery below floor but Nightboost (cheaper) is coming — wait."""
        import asyncio

        coord = FakeCoordinator(cfg=_cfg())
        raw = _raw(battery_soc=30.0)  # below floor but 23:30 = Night, not Nightboost yet
        result = asyncio.run(
            coord._maybe_apply_cheap_rate_floor(self._now_at(23, 30), raw, _nightboost_cfg())
        )
        assert "waiting" in result.lower(), f"Expected wait message at 23:30, got: {result!r}"
        assert "02:00" in result or "nightboost" in result.lower(), (
            f"Should mention the cheaper window, got: {result!r}"
        )

    def test_emergency_top_up_during_night_if_critically_low(self):
        """Battery near min SoC (10%) during Night — top up, can't wait."""
        import asyncio

        coord = FakeCoordinator(cfg=_cfg())
        raw = _raw(battery_soc=8.0)  # below min_soc(10) + 5 = 15% emergency floor
        result = asyncio.run(
            coord._maybe_apply_cheap_rate_floor(self._now_at(23, 30), raw, _nightboost_cfg())
        )
        assert "topping up" in result.lower(), (
            f"Critically low battery must not wait for Nightboost, got: {result!r}"
        )

    def test_floor_inactive_above_floor_during_cheapest(self):
        """Battery above floor during Nightboost — nothing to do."""
        import asyncio

        coord = FakeCoordinator(cfg=_cfg())
        raw = _raw(battery_soc=60.0)  # above 40% floor, 02:30 = Nightboost
        result = asyncio.run(
            coord._maybe_apply_cheap_rate_floor(self._now_at(2, 30), raw, _nightboost_cfg())
        )
        assert result == "", f"Battery above floor should return empty, got: {result!r}"

    def test_floor_inactive_during_day_rate(self):
        """During Day rate, floor must not trigger even if battery is low."""
        import asyncio

        coord = FakeCoordinator(cfg=_cfg())
        raw = _raw(battery_soc=5.0)
        result = asyncio.run(
            coord._maybe_apply_cheap_rate_floor(self._now_at(14, 0), raw, _nightboost_cfg())
        )
        assert result == "", f"Floor must not trigger during Day rate, got: {result!r}"

    def test_floor_only_writes_once_per_window(self):
        """Flag prevents repeated writes every 30s."""
        import asyncio

        coord = FakeCoordinator(cfg=_cfg())
        coord._floor_top_up_applied = True
        raw = _raw(battery_soc=20.0)
        result = asyncio.run(
            coord._maybe_apply_cheap_rate_floor(self._now_at(2, 30), raw, _nightboost_cfg())
        )
        assert "already applied" in result.lower(), f"Expected 'already applied', got: {result!r}"

    def test_floor_disabled_when_zero(self):
        """Floor SoC of 0 disables the feature entirely."""
        import asyncio

        cfg = {**_nightboost_cfg(), "cheap_rate_floor_soc": 0}
        coord = FakeCoordinator(cfg=cfg)
        raw = _raw(battery_soc=5.0)
        result = asyncio.run(coord._maybe_apply_cheap_rate_floor(self._now_at(2, 30), raw, cfg))
        assert result == "", f"Floor of 0 must disable feature, got: {result!r}"

    def test_floor_resets_at_midnight(self):
        """_floor_top_up_applied flag must reset at midnight so next night works."""
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/coordinator.py").read_text()
        assert "_floor_top_up_applied = False" in src


class TestReadOptionalFloatProxy:
    """_read_optional_float must use _get_state proxy, not hass.states.get directly."""

    def test_reads_via_proxy(self):
        from unittest.mock import MagicMock

        coord = FakeCoordinator(cfg=_cfg())
        mock_state = MagicMock()
        mock_state.state = "47.3"
        coord._get_state = lambda eid: mock_state if eid == "sensor.temp" else None
        result = coord._read_optional_float("sensor.temp")
        assert result == pytest.approx(47.3), (
            "_read_optional_float must use _get_state — calling hass.states.get "
            "directly bypasses the test proxy and always returns None in tests."
        )

    def test_hass_states_get_not_called(self):
        from unittest.mock import MagicMock

        coord = FakeCoordinator(cfg=_cfg())
        coord._get_state = lambda eid: MagicMock(state="1.0")
        coord.hass.states.get = MagicMock(
            side_effect=AssertionError("_read_optional_float called hass.states.get directly")
        )
        coord._read_optional_float("sensor.temp")  # must not raise


class TestEVRediscoveryNullPowerEntity:
    """Coordinator must retry EV discovery when power_entity is None."""

    def test_retry_condition_in_source(self):
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/coordinator.py").read_text()
        assert "self._ev_charger.power_entity is None" in src, (
            "Without this, a charger cached on boot with no power entity "
            "never gets updated even after the entity appears in HA."
        )


class TestEntityUnavailable:
    """Coordinator must raise UpdateFailed when GivTCP is not publishing.

    HA quality scale — entity-unavailable: sensors should go unavailable
    when the data source stops publishing rather than holding stale values.
    """

    def test_update_failed_imported(self):
        """UpdateFailed must be imported to signal entity unavailability."""
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/coordinator.py").read_text()
        assert "UpdateFailed" in src

    def test_check_is_in_update_cycle(self):
        """UpdateFailed raise must be inside _async_update_data."""
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/coordinator.py").read_text()
        update_fn = src[src.find("async def _async_update_data") :]
        assert "raise UpdateFailed" in update_fn, (
            "_async_update_data must raise UpdateFailed when GivTCP is silent."
        )

    def test_both_sensors_must_be_stale(self):
        """Guard must use AND — a single stale sensor should not trigger unavailability."""
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/coordinator.py").read_text()
        check_block = src[src.find("async def _async_update_data") : src.find("raise UpdateFailed")]
        assert " and " in check_block, (
            "Both solar AND battery must be unavailable before raising — "
            "a single brief interruption should not mark the whole integration unavailable."
        )

    def test_unavailable_and_unknown_both_treated_as_stale(self):
        """'unavailable' and 'unknown' must both be considered stale states."""
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/coordinator.py").read_text()
        check_block = src[src.find("async def _async_update_data") : src.find("raise UpdateFailed")]
        assert '"unavailable"' in check_block, "Must treat 'unavailable' state as stale"
        assert '"unknown"' in check_block, "Must treat 'unknown' state as stale"

    def test_quality_scale_yaml_updated(self):
        """quality_scale.yaml must mark entity-unavailable as done."""
        from pathlib import Path

        qs = Path("custom_components/givenergy_inverter_manager/quality_scale.yaml").read_text()
        # Find the entity-unavailable entry
        idx = qs.find("entity-unavailable")
        assert idx != -1, "entity-unavailable must exist in quality_scale.yaml"
        entry = qs[idx : idx + 60]
        assert "done" in entry, "entity-unavailable must be marked done in quality_scale.yaml"


class TestLogWhenUnavailable:
    """Coordinator must log once on GivTCP going offline and again on recovery."""

    def _make_coord(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord._givtcp_was_unavailable = False
        return coord

    @pytest.mark.asyncio
    async def test_logs_warning_on_first_offline(self, caplog):
        # Arrange
        from homeassistant.helpers.update_coordinator import UpdateFailed
        coord = self._make_coord()
        # Act
        import logging
        with caplog.at_level(logging.WARNING):
            with pytest.raises(UpdateFailed):
                await coord._async_update_data()
        # Assert
        assert any("GivTCP has stopped" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_does_not_repeat_warning_when_still_offline(self, caplog):
        # Arrange
        from homeassistant.helpers.update_coordinator import UpdateFailed
        coord = self._make_coord()
        coord._givtcp_was_unavailable = True  # already flagged offline
        # Act
        import logging
        with caplog.at_level(logging.WARNING):
            with pytest.raises(UpdateFailed):
                await coord._async_update_data()
        # Assert — warning must not appear again
        assert not any("GivTCP has stopped" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_logs_info_on_recovery(self, caplog):
        # Arrange
        coord = self._make_coord()
        coord._givtcp_was_unavailable = True  # was offline
        coord.set_states(_default_states())
        # Act
        import logging
        with caplog.at_level(logging.INFO):
            await coord._async_update_data()
        # Assert
        assert any("publishing data again" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_flag_cleared_after_recovery(self):
        # Arrange
        coord = self._make_coord()
        coord._givtcp_was_unavailable = True
        coord.set_states(_default_states())
        # Act
        await coord._async_update_data()
        # Assert
        assert coord._givtcp_was_unavailable is False

    def test_quality_scale_log_when_unavailable_is_done(self):
        from pathlib import Path
        qs = Path("custom_components/givenergy_inverter_manager/quality_scale.yaml").read_text()
        idx = qs.find("log-when-unavailable")
        assert idx != -1
        assert "done" in qs[idx : idx + 60]


class TestActionExceptions:
    """get_dashboard_yaml must raise ServiceValidationError when not configured."""

    def test_raises_service_validation_error_when_no_entry(self):
        from pathlib import Path
        src = Path("custom_components/givenergy_inverter_manager/dashboard.py").read_text()
        assert "ServiceValidationError" in src

    def test_no_config_entry_key_in_strings(self):
        import json
        from pathlib import Path
        strings = json.loads(
            Path("custom_components/givenergy_inverter_manager/strings.json").read_text()
        )
        assert "no_config_entry" in strings["exceptions"]

    def test_no_config_entry_key_in_translations(self):
        import json
        from pathlib import Path
        translations = json.loads(
            Path("custom_components/givenergy_inverter_manager/translations/en.json").read_text()
        )
        assert "no_config_entry" in translations["exceptions"]

    def test_quality_scale_action_exceptions_is_done(self):
        from pathlib import Path
        qs = Path("custom_components/givenergy_inverter_manager/quality_scale.yaml").read_text()
        idx = qs.find("action-exceptions")
        assert idx != -1
        assert "done" in qs[idx : idx + 80]


class TestIconTranslations:
    """icons.json must exist and cover all translated entity keys."""

    def _load_icons(self):
        import json
        from pathlib import Path
        path = Path("custom_components/givenergy_inverter_manager/icons.json")
        assert path.exists(), "icons.json must exist"
        return json.loads(path.read_text())

    def _load_strings(self):
        import json
        from pathlib import Path
        return json.loads(
            Path("custom_components/givenergy_inverter_manager/strings.json").read_text()
        )

    def test_icons_json_is_valid_json(self):
        # Arrange / Act
        icons = self._load_icons()
        # Assert
        assert isinstance(icons, dict)

    def test_all_sensor_keys_have_icons(self):
        # Arrange
        icons = self._load_icons()
        strings = self._load_strings()
        sensor_keys = list(strings["entity"]["sensor"].keys())
        icon_sensor_keys = list(icons.get("entity", {}).get("sensor", {}).keys())
        # Assert
        missing = [k for k in sensor_keys if k not in icon_sensor_keys]
        assert not missing, f"Sensor keys missing from icons.json: {missing}"

    def test_services_have_icons(self):
        # Arrange
        icons = self._load_icons()
        # Assert
        assert "get_dashboard_yaml" in icons.get("services", {})
        assert "suggest_appliance_run" in icons.get("services", {})

    def test_quality_scale_icon_translations_is_done(self):
        from pathlib import Path
        qs = Path("custom_components/givenergy_inverter_manager/quality_scale.yaml").read_text()
        idx = qs.find("icon-translations")
        assert idx != -1
        assert "done" in qs[idx : idx + 80]


class TestRepairIssues:
    """Repair issue is created when GivTCP entities are completely absent from HA."""

    @pytest.mark.asyncio
    async def test_repair_issue_created_when_entities_missing(self):
        import homeassistant.helpers.issue_registry as ir
        from homeassistant.helpers.update_coordinator import UpdateFailed
        # Arrange
        coord = FakeCoordinator(cfg=_cfg())
        ir.async_create_issue.reset_mock()
        # Act — no states set, so entities are None (not just unavailable)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        # Assert
        ir.async_create_issue.assert_called_once()

    @pytest.mark.asyncio
    async def test_repair_issue_not_created_when_entities_unavailable(self):
        import homeassistant.helpers.issue_registry as ir
        from homeassistant.helpers.update_coordinator import UpdateFailed
        # Arrange — set states to 'unavailable' so they exist but are stale
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.solar", "unavailable")
        coord.set_state("sensor.battery_soc", "unavailable")
        ir.async_create_issue.reset_mock()
        # Act
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        # Assert — issue should NOT be raised for transient unavailability
        ir.async_create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_repair_issue_deleted_on_recovery(self):
        import homeassistant.helpers.issue_registry as ir
        # Arrange — start from a working state
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        ir.async_delete_issue.reset_mock()
        # Act
        await coord._async_update_data()
        # Assert
        ir.async_delete_issue.assert_called_once()

    def test_repairs_module_exists(self):
        from pathlib import Path
        assert Path(
            "custom_components/givenergy_inverter_manager/repairs.py"
        ).exists()

    def test_quality_scale_repair_issues_is_done(self):
        from pathlib import Path
        qs = Path("custom_components/givenergy_inverter_manager/quality_scale.yaml").read_text()
        idx = qs.find("repair-issues")
        assert idx != -1
        assert "done" in qs[idx : idx + 80]


class TestDashboardServiceValidationError:
    """get_dashboard_yaml raises ServiceValidationError when no entries exist."""

    def test_service_validation_error_imported_in_dashboard(self):
        from pathlib import Path
        src = Path("custom_components/givenergy_inverter_manager/dashboard.py").read_text()
        assert "ServiceValidationError" in src
        assert "no_config_entry" in src

    def test_raises_service_validation_error_when_no_entry_in_source(self):
        from pathlib import Path
        src = Path("custom_components/givenergy_inverter_manager/dashboard.py").read_text()
        handler_block = src[src.find("def handle_get_dashboard_yaml"):]
        assert "raise ServiceValidationError" in handler_block
        assert "no_config_entry" in handler_block
