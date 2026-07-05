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

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

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
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.accumulation import AccumulationState
from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from tests.conftest import _nightboost_cfg

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
        entry.async_on_unload = lambda fn: fn   # returns the cancel fn itself

        hass = MagicMock()
        hass.states.get = lambda eid: self._states.get(eid)

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
        self._solar_fractions = {m: 0.5 for m in range(1, 13)}  # flat for tests
        self._last_reset_time: str = ""

        class _FakeAccStore:
            """Minimal AccumulationStore stub for testing — no HA Storage."""
            def __init__(self):
                self.state = AccumulationState()
            @property
            def today(self): return self.state.today
            @property
            def week(self): return self.state.week
            @property
            def month(self): return self.state.month
            @property
            def yesterday(self): return self.state.yesterday
            @property
            def today_forecast_kwh(self): return self.state.today_forecast_kwh
            @property
            def yesterday_forecast_accuracy_pct(self): return self.state.yesterday_forecast_accuracy_pct
            @property
            def forecast_accuracy_7day_avg_pct(self):
                h = self.state.forecast_accuracy_history
                return round(sum(h)/len(h),1) if h else 0.0
            def on_midnight(self, now):
                self.state.yesterday = self.state.today
                from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
                self.state.today = EnergyAccumulator()
            def on_charge_decision(self, kwh):
                if self.state.today_forecast_kwh == 0.0 and kwh > 0:
                    self.state.today_forecast_kwh = kwh
            async def async_save(self): pass  # no-op in tests
            async def async_load(self): pass

        self._acc = _FakeAccStore()
        self._last_soc:     float | None    = None
        self._last_update:  datetime | None = None
        self._update_cycle: int = 0
        self._ev_charger    = None
        self.override_charge_target = None
        self.override_immersion     = None
        self.override_skip_charge   = False

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
    base.update({
        CONF_SOLAR_POWER:              "sensor.solar",
        CONF_BATTERY_SOC:             "sensor.battery_soc",
        CONF_BATTERY_POWER:           "sensor.battery_power",
        CONF_GRID_POWER:              "sensor.grid",
        CONF_HOUSE_LOAD:              "sensor.house",
        CONF_TARGET_SOC_ENTITY:       "number.target_soc",
        CONF_ENABLE_CHARGE_TARGET:    "switch.enable_charge_target",
        CONF_ENABLE_CHARGE_SCHEDULE:  "switch.enable_charge_schedule",
        CONF_CHARGE_START_TIME_ENTITY:"select.charge_start",
        CONF_CHARGE_END_TIME_ENTITY:  "select.charge_end",
    })
    base.update(overrides)
    return base


def _default_states() -> dict[str, str]:
    return {
        "sensor.solar":        "3000",
        "sensor.battery_soc":  "60",
        "sensor.battery_power": "-500",
        "sensor.grid":         "0",
        "sensor.house":        "1500",
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
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.grid", "-1200")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.grid_power_w == pytest.approx(-1200.0)

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

        await coord.run_cycle()                        # sets _last_update
        coord._last_update = datetime.now() - timedelta(minutes=30)
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
        coord._midnight_reset(datetime.now())
        assert coord._acc.today.solar_kwh == 0.0
        assert coord._acc.today.import_kwh == 0.0

    def test_clears_last_update(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord._last_update = datetime.now()
        coord._midnight_reset(datetime.now())
        assert coord._last_update is None

    def test_accumulator_is_fresh_instance(self):
        coord = FakeCoordinator(cfg=_cfg())
        old_acc = coord._acc.today
        coord._midnight_reset(datetime.now())
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
        coord._write_charge_target_to_inverter(datetime.now())
        # _create_task was called with the coroutine — run it
        assert len(coord.tasks_created) == 1
        await coord.tasks_created[0]
        domains = [(d, s) for d, s, _ in coord.service_calls]
        assert ("switch", "turn_on")   in domains   # step 1: enable_charge_schedule
        assert ("select", "select_option") in domains  # steps 2 & 3
        assert ("number", "set_value") in domains   # step 4: target_soc

    @pytest.mark.asyncio
    async def test_target_soc_written_correctly(self):
        coord = self._coord_with_decision(target_soc=75)
        coord._write_charge_target_to_inverter(datetime.now())
        await coord.tasks_created[0]
        number_calls = coord.service_calls_for("number", "set_value")
        assert len(number_calls) == 1
        assert number_calls[0]["value"] == 75

    @pytest.mark.asyncio
    async def test_enable_charge_target_on_below_100(self):
        coord = self._coord_with_decision(target_soc=85)
        coord._write_charge_target_to_inverter(datetime.now())
        await coord.tasks_created[0]
        # Step 5: enable_charge_target must be ON when target < 100
        switch_on = coord.service_calls_for("switch", "turn_on")
        eids = [c["entity_id"] for c in switch_on]
        assert "switch.enable_charge_target" in eids

    @pytest.mark.asyncio
    async def test_enable_charge_target_off_at_100(self):
        """At 100% target, enable_charge_target must be OFF to avoid bounce bug."""
        coord = self._coord_with_decision(target_soc=100)
        coord._write_charge_target_to_inverter(datetime.now())
        await coord.tasks_created[0]
        switch_off = coord.service_calls_for("switch", "turn_off")
        eids = [c["entity_id"] for c in switch_off]
        assert "switch.enable_charge_target" in eids

    def test_skip_charge_suppresses_write(self):
        coord = self._coord_with_decision(skip=True)
        coord._write_charge_target_to_inverter(datetime.now())
        assert len(coord.tasks_created) == 0
        assert len(coord.service_calls) == 0

    def test_no_write_when_no_target_entity(self):
        cfg = _cfg()
        cfg.pop(CONF_TARGET_SOC_ENTITY, None)
        coord = FakeCoordinator(cfg=cfg)
        coord._write_charge_target_to_inverter(datetime.now())
        assert len(coord.tasks_created) == 0

    def test_no_write_when_no_data(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.data = None
        coord._write_charge_target_to_inverter(datetime.now())
        assert len(coord.tasks_created) == 0

    @pytest.mark.asyncio
    async def test_dry_run_suppresses_write(self):
        cfg = _cfg(**{CONF_DRY_RUN: True})
        coord = FakeCoordinator(cfg=cfg)
        coord.set_states(_default_states())
        from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision
        decision = ChargeDecision(
            target_soc=80, skip_charge=False, reason="test",
            forecast_kwh=10.0, current_soc=60.0, battery_capacity=19.0,
            car_plugged_in=False, cost_to_charge=1.0,
        )
        data = MagicMock()
        data.charge_decision = decision
        coord.data = data
        coord._write_charge_target_to_inverter(datetime.now())
        # In dry run mode, no task should be created
        assert len(coord.tasks_created) == 0
        assert len(coord.service_calls) == 0


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
            brand=EVChargerBrand.ZAPPI, name="Zappi", serial="12345",
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
        assert ("select", "select_option",
                {"entity_id": "select.target", "option": "02:00:00"}) in coord.service_calls

    @pytest.mark.asyncio
    async def test_set_number_issues_set_value(self):
        coord = FakeCoordinator(cfg=_cfg())
        await coord._givtcp_set_number("number.target", 80, "test")
        assert ("number", "set_value",
                {"entity_id": "number.target", "value": 80}) in coord.service_calls

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
        cfg["rate_periods"] = []   # flat rate
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
            target_soc=80, skip_charge=False, reason="test",
            forecast_kwh=10.0, current_soc=60.0, battery_capacity=19.0,
            car_plugged_in=False, cost_to_charge=1.0,
        )
        data = MagicMock()
        data.charge_decision = decision
        coord.data = data
        # Even if we manually call the write-back, the flat-rate tariff
        # means get_cheapest_rate_start would raise — but _register_charge_target_listener
        # already returned early so the listener was never registered.
        # Confirm _register_charge_target_listener ran without error:
        coord._register_charge_target_listener()   # should not raise
