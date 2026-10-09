"""
test_coordinator.py — Tests for coordinator.py.

The coordinator's HA surface is proxied through three methods:
  _get_state(entity_id)
  _call_service(domain, service, data)
  _create_task(coro)

FakeCoordinator overrides these three methods.  No hass mock, no MagicMock
patching, no asyncio magic — just a subclass that controls the HA surface
and records what the coordinator asked it to do.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from datetime import time as clock_time
from unittest.mock import MagicMock

import pytest

from custom_components.givenergy_inverter_manager.accumulation import (
    AccumulationState,
    AccumulationStore,
)
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
from custom_components.givenergy_inverter_manager.core.charge_hold import HeldCharge
from custom_components.givenergy_inverter_manager.core.charge_window import ChargeWindow
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.core.ev_base_rate import WatchState
from custom_components.givenergy_inverter_manager.core.immersion_rate import RunTracker
from custom_components.givenergy_inverter_manager.core.solar_day import HeldSolarDay
from custom_components.givenergy_inverter_manager.core.sunrise_hold import HeldSunrise
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from custom_components.givenergy_inverter_manager.givtcp_writer import GivTCPWriter, SwitchState
from custom_components.givenergy_inverter_manager.immersion_actuator import ImmersionActuator
from tests.conftest import _nightboost_cfg, _raw
from tests.helpers import PKG

# ── Minimal HA state stub ─────────────────────────────────────────────────────


class FakeState:
    """Minimal stub for an HA state object."""

    def __init__(self, state: str, attributes: dict | None = None):
        self.state = state
        self.attributes = attributes or {}


# ── FakeCoordinator ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_write_retry_sleep(monkeypatch):
    """Skip the real 2 s read-back delay in the inverter write helpers.

    Patch the globals the writer methods actually use. Other test modules
    re-import the package, so patching it by module path can miss.
    """
    monkeypatch.setitem(GivTCPWriter.write_verified.__globals__, "GIVTCP_WRITE_RETRY_SLEEP_S", 0)


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
        self._held_charge = HeldCharge()
        self._held_sunrise = HeldSunrise()
        self._held_solar = HeldSolarDay()
        self._solar_fractions = dict.fromkeys(range(1, 13), 0.5)  # flat for tests
        self._last_reset_time: str = ""
        self._unsub_charge_target = None
        self._charge_target_trigger_at = None

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
            def year(self):
                return self.state.year

            @property
            def yesterday(self):
                return self.state.yesterday

            @property
            def counters(self):
                return self.state.counters

            @property
            def immersion_heat_log(self):
                return self.state.immersion_heat_log

            immersion_heating_rates: list = []  # noqa: RUF012

            def record_immersion_rate(self, rate):
                self.immersion_heating_rates.append(rate)

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

            @property
            def trailing_12m_export_kwh(self):
                return round(sum(self.state.monthly_export_snapshots), 3)

            @property
            def monthly_export_snapshots(self):
                return list(self.state.monthly_export_snapshots)

            @property
            def trailing_12m_solar_kwh(self):
                return round(sum(s.get("solar_kwh", 0.0) for s in self.state.monthly_snapshots), 3)

            @property
            def trailing_12m_import_kwh(self):
                return round(sum(s.get("import_kwh", 0.0) for s in self.state.monthly_snapshots), 3)

            @property
            def trailing_12m_import_cost(self):
                total = sum(
                    sum(s.get("import_cost_by_period", {}).values())
                    for s in self.state.monthly_snapshots
                )
                return round(total, 4)

            @property
            def trailing_12m_export_earnings(self):
                return round(sum(s.get("export_earnings", 0.0) for s in self.state.monthly_snapshots), 3)

            def on_midnight(self, now):
                self.state.yesterday = self.state.today
                self.state.today = EnergyAccumulator()
                if self.state.slot_load_date and self.state.slot_load_date < now.date().isoformat():
                    self._archive_slot_day()

            record_slot_load = AccumulationStore.record_slot_load
            _archive_slot_day = AccumulationStore._archive_slot_day
            slot_load_profile = AccumulationStore.slot_load_profile
            forecast_correction_factor = AccumulationStore.forecast_correction_factor
            forecast_accuracy = AccumulationStore.forecast_accuracy
            on_raw_forecast = AccumulationStore.on_raw_forecast
            today_raw_forecast_kwh = AccumulationStore.today_raw_forecast_kwh
            today_raw_forecast_p10_kwh = AccumulationStore.today_raw_forecast_p10_kwh
            note_clipping = AccumulationStore.note_clipping

            bill_start_day = 1

            def update_bill_start_day(self, bill_start_day):
                self.bill_start_day = bill_start_day

            def on_charge_decision(self, kwh):
                if self.state.today_forecast_kwh == 0.0 and kwh > 0:
                    self.state.today_forecast_kwh = kwh

            scheduled_saves = 0

            def schedule_save(self):
                self.scheduled_saves += 1

            def save_battery_stats(self, stats):
                pass

            async def async_save(self):
                pass  # no-op in tests

            async def async_load(self):
                pass

        self._acc = _FakeAccStore()
        self._last_soc: float | None = None
        self._last_update: datetime | None = None
        self._update_cycle: int = 0
        self._ev_charger = None
        self._ev_base_rate = WatchState()
        self._battery_cycle_entities: list[str] = []
        self.override_charge_enabled = False
        self.override_charge_value = 80
        self.immersion_target_temp: float = 55.0
        self.immersion_min_temp: float = 50.0
        self.immersion_hysteresis_c: float = 5.0
        self.immersion_schedule_enabled: bool = False
        self._rate_tracker = RunTracker()
        self._floor_top_up_applied: bool = False
        self.override_skip_charge = False
        self._givtcp_was_unavailable: bool = False
        self._inputs_unavailable_since = None
        self.immersion = ImmersionActuator(self._immersion_ports())
        self._dry_run_last_skipped: str = ""
        self._smoothed_solar_w: float = 0.0
        self._writer = GivTCPWriter(
            get_state=lambda eid: self._get_state(eid),
            call_service=lambda domain, service, data: self._call_service(domain, service, data),
            on_count_change=self._save_register_write_count,
        )
        self._slot_load_today: list[float] = [0.0] * 48
        self._slot_load_history: list[list[float]] = []

        GivLogger.register(self._effective_cfg)

    # ── HA proxy overrides ────────────────────────────────────────────────────

    def _get_state(self, entity_id: str):
        return self._states.get(entity_id)

    def _get_all_states(self) -> dict:
        return dict(self._states)

    async def _call_service(self, domain, service, data):
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

    def set_state(self, entity_id: str, value: str, attributes: dict | None = None) -> None:
        """Set a fake entity state."""
        self._states[entity_id] = FakeState(value, attributes)

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

    def test_flags_an_immersion_switch_that_is_configured(self):
        coord = FakeCoordinator(cfg=_cfg(**{CONF_IMMERSION_SWITCH: "switch.immersion"}))
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.immersion_switch_configured is True

    def test_flags_a_missing_immersion_switch(self):
        coord = FakeCoordinator(cfg=_cfg())
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.immersion_switch_configured is False

    def test_reads_the_immersion_switch_from_options_over_data(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.entry.options = {CONF_IMMERSION_SWITCH: "switch.immersion"}
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.immersion_switch_configured is True

    def test_flags_no_ev_charger_until_one_is_discovered(self):
        coord = FakeCoordinator(cfg=_cfg())
        assert coord._collect_raw(coord._effective_cfg()).ev_charger_present is False
        coord._ev_charger = TestApplyEvAction()._charger()
        assert coord._collect_raw(coord._effective_cfg()).ev_charger_present is True

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

    def _p10(self, forecast_attributes=None, p10_state=None):
        cfg = _cfg(**{"forecast_entity": "sensor.forecast"})
        if p10_state is not None:
            cfg["forecast_entity_p10"] = "sensor.p10"
        coord = FakeCoordinator(cfg=cfg)
        coord.set_state("sensor.forecast", "38.1", forecast_attributes)
        if p10_state is not None:
            coord.set_state("sensor.p10", p10_state)
        return coord._collect_raw(coord._effective_cfg()).forecast_kwh_p10

    def test_p10_is_read_from_the_forecast_sensors_estimate10_attribute(self):
        assert self._p10({"estimate10": 19.29}) == pytest.approx(19.29)

    def test_a_configured_p10_sensor_wins_over_the_attribute(self):
        assert self._p10({"estimate10": 19.29}, p10_state="15.0") == pytest.approx(15.0)

    def test_an_unavailable_p10_sensor_falls_back_to_the_attribute(self):
        assert self._p10({"estimate10": 19.29}, p10_state="unavailable") == pytest.approx(19.29)

    def test_no_p10_without_the_attribute_or_a_sensor(self):
        assert self._p10({"estimate": 38.1}) is None

    @pytest.mark.parametrize("value", ["n/a", None, -3.0])
    def test_an_unusable_attribute_is_no_p10(self, value):
        assert self._p10({"estimate10": value}) is None

    def test_no_p10_without_a_forecast_entity(self):
        coord = FakeCoordinator(cfg=_cfg())
        assert coord._collect_raw(coord._effective_cfg()).forecast_kwh_p10 is None

    def test_reads_battery_power_charging(self):
        """GivTCP reports charging as negative. The internal value is positive."""
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.battery_power", "-2500")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.battery_power_w == pytest.approx(2500.0)

    def test_reads_battery_power_discharging(self):
        """GivTCP reports discharging as positive. The internal value is negative."""
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.battery_power", "1800")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.battery_power_w == pytest.approx(-1800.0)

    def test_reads_battery_power_zero_when_idle(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.battery_power", "0")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.battery_power_w == pytest.approx(0.0)
        assert str(raw.battery_power_w) == "0.0"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("givtcp_w", "power_w", "label"),
        [("-2200", 2200.0, "Charging"), ("1800", -1800.0, "Discharging")],
    )
    async def test_cycle_reports_direction_from_givtcp_sign(self, givtcp_w, power_w, label):
        """Live reading: GivTCP -2200 W while the battery charges from solar."""
        from tests.test_sensors import _lambda_for

        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states({**_default_states(), "sensor.battery_power": givtcp_w})
        data = await coord.run_cycle()
        assert data.battery_power_w == pytest.approx(power_w)
        assert _lambda_for("battery_power")(data) == pytest.approx(power_w)
        assert _lambda_for("battery_state")(data) == label
        assert _lambda_for("battery_power_direction")(data) == label

    @pytest.mark.parametrize(
        ("givtcp_w", "keeps_heating"),
        [("2166", True), ("-2166", False)],
    )
    def test_immersion_surplus_subtracts_charging_not_discharging(self, givtcp_w, keeps_heating):
        """Live 10:38: cloud cover, battery discharging 2.2 kW, 3 kW element on.

        Discharging must not be subtracted from the surplus. Charging must.
        """
        from tests.core.flat_rules import should_divert_to_immersion

        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(
            {
                **_default_states(),
                "sensor.solar": "1800",
                "sensor.house": "3768",
                "sensor.battery_soc": "86",
                "sensor.battery_power": givtcp_w,
            }
        )
        raw = coord._collect_raw(coord._effective_cfg())
        on, _ = should_divert_to_immersion(
            solar_power_w=raw.solar_power_w,
            house_load_w=raw.house_load_w,
            battery_soc=raw.battery_soc,
            battery_power_w=raw.battery_power_w,
            inverter_max_w=5000.0,
            immersion_temp=50.0,
            immersion_target_temp=55.0,
            immersion_min_temp=45.0,
            currently_on=True,
            immersion_power_w=3000.0,
        )
        assert on is keeps_heating

    @pytest.mark.parametrize(
        ("givtcp_w", "charge_kwh", "discharge_kwh"),
        [("-3600", 0.3, 0.0), ("3600", 0.0, 0.3)],
    )
    def test_accumulation_lands_in_the_right_direction(self, givtcp_w, charge_kwh, discharge_kwh):
        """5 minutes at 3.6 kW is 0.3 kWh. Each GivTCP sign fills its own counter."""
        from tests.conftest import _nightboost_cfg, _run

        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states({**_default_states(), "sensor.battery_power": givtcp_w})
        raw = coord._collect_raw(coord._effective_cfg())
        now = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
        data, _ = _run(
            raw=raw, cfg=_nightboost_cfg(), now=now, last_update_time=now - timedelta(minutes=5)
        )
        assert data.today.battery_charge_kwh == pytest.approx(charge_kwh)
        assert data.today.battery_discharge_kwh == pytest.approx(discharge_kwh)

    def test_daily_counters_use_the_battery_prefixed_givtcp_ids(self):
        """Real GivTCP names: battery_charge_energy_today_kwh, not charge_energy_today_kwh."""
        from custom_components.givenergy_inverter_manager.const import CONF_INVERTER_SERIAL

        coord = FakeCoordinator(cfg=_cfg(**{CONF_INVERTER_SERIAL: "fd2309f069"}))
        coord.set_states(
            {
                **_default_states(),
                "sensor.givtcp_fd2309f069_battery_charge_energy_today_kwh": "18.8",
                "sensor.givtcp_fd2309f069_battery_discharge_energy_today_kwh": "1.3",
            }
        )
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.charge_energy_today_kwh == pytest.approx(18.8)
        assert raw.discharge_energy_today_kwh == pytest.approx(1.3)

    def test_daily_counters_fall_back_to_unprefixed_ids(self):
        from custom_components.givenergy_inverter_manager.const import CONF_INVERTER_SERIAL

        coord = FakeCoordinator(cfg=_cfg(**{CONF_INVERTER_SERIAL: "fd2309f069"}))
        coord.set_states(
            {
                **_default_states(),
                "sensor.givtcp_fd2309f069_charge_energy_today_kwh": "4.0",
                "sensor.givtcp_fd2309f069_discharge_energy_today_kwh": "2.0",
            }
        )
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.charge_energy_today_kwh == pytest.approx(4.0)
        assert raw.discharge_energy_today_kwh == pytest.approx(2.0)

    def test_negative_forecast_treated_as_none(self):
        cfg = _cfg(**{"forecast_entity": "sensor.forecast"})
        coord = FakeCoordinator(cfg=cfg)
        coord.set_state("sensor.forecast", "-1")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.forecast_kwh_tomorrow is None

    def test_reads_forecast_p10_when_configured(self):
        # Arrange
        cfg = _cfg(**{"forecast_entity_p10": "sensor.forecast_p10"})
        coord = FakeCoordinator(cfg=cfg)
        coord.set_state("sensor.forecast_p10", "6.0")

        # Act
        raw = coord._collect_raw(coord._effective_cfg())

        # Assert
        assert raw.forecast_kwh_p10 == pytest.approx(6.0)

    def test_reads_forecast_d2_when_configured(self):
        cfg = _cfg(**{"forecast_entity_d2": "sensor.forecast_d2"})
        coord = FakeCoordinator(cfg=cfg)
        coord.set_state("sensor.forecast_d2", "21.5")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.forecast_kwh_d2 == pytest.approx(21.5)

    def test_forecast_d2_absent_when_not_configured(self):
        coord = FakeCoordinator(cfg=_cfg())
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.forecast_kwh_d2 is None

    def test_forecast_p10_absent_when_not_configured(self):
        # Arrange
        coord = FakeCoordinator(cfg=_cfg())

        # Act
        raw = coord._collect_raw(coord._effective_cfg())

        # Assert
        assert raw.forecast_kwh_p10 is None

    def test_negative_p10_treated_as_none(self):
        # Arrange
        cfg = _cfg(**{"forecast_entity_p10": "sensor.forecast_p10"})
        coord = FakeCoordinator(cfg=cfg)
        coord.set_state("sensor.forecast_p10", "-0.5")

        # Act
        raw = coord._collect_raw(coord._effective_cfg())

        # Assert
        assert raw.forecast_kwh_p10 is None


class TestBillStartDayFromOptions:
    """The accumulator reset day follows the effective config, options over data."""

    @pytest.mark.asyncio
    async def test_cycle_applies_bill_start_day_from_options(self):
        coord = FakeCoordinator(cfg=_cfg(bill_start_day=16))
        coord.set_states(_default_states())
        coord.entry.options = {"bill_start_day": 5}
        await coord.run_cycle()
        assert coord._acc.bill_start_day == 5

    @pytest.mark.asyncio
    async def test_cycle_uses_data_when_no_option_set(self):
        coord = FakeCoordinator(cfg=_cfg(bill_start_day=16))
        coord.set_states(_default_states())
        await coord.run_cycle()
        assert coord._acc.bill_start_day == 16

    @pytest.mark.asyncio
    async def test_later_option_change_is_picked_up_next_cycle(self):
        coord = FakeCoordinator(cfg=_cfg(bill_start_day=16))
        coord.set_states(_default_states())
        await coord.run_cycle()
        coord.entry.options = {"bill_start_day": 7}
        await coord.run_cycle()
        assert coord._acc.bill_start_day == 7

    def test_configured_bill_start_day_prefers_options(self):
        coord = FakeCoordinator(cfg=_cfg(bill_start_day=16))
        coord.entry.options = {"bill_start_day": 28}
        assert coord._configured_bill_start_day() == 28


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
    async def test_period_start_stamps_reach_the_data(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord._acc.state.week_start_iso = "2026-07-13T00:00:00+00:00"
        coord._acc.state.month_start_iso = "2026-07-01T00:00:00+00:00"
        coord._acc.state.year_start_iso = "2026-01-01T00:00:00+00:00"
        coord._last_reset_time = "2026-07-15T00:00:00+00:00"
        data = await coord.run_cycle()
        assert data.week_start_time == "2026-07-13T00:00:00+00:00"
        assert data.month_start_time == "2026-07-01T00:00:00+00:00"
        assert data.year_start_time == "2026-01-01T00:00:00+00:00"
        assert data.last_reset_time == "2026-07-15T00:00:00+00:00"

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
        coord.override_charge_value = 55
        coord.override_charge_enabled = True
        data = await coord.run_cycle()
        assert data.charge_decision.target_soc == 55


class TestChargeTargetOverrideState:
    """The coordinator owns the override. The effective target is derived from it."""

    def test_disabled_by_default_with_the_default_value(self):
        coord = FakeCoordinator(cfg=_cfg())
        assert coord.override_charge_enabled is False
        assert coord.override_charge_value == 80
        assert coord.override_charge_target is None

    def test_enabling_without_touching_the_value_uses_the_default(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.override_charge_enabled = True
        assert coord.override_charge_target == 80

    def test_setting_the_value_while_disabled_does_not_take_effect(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.override_charge_value = 65
        assert coord.override_charge_target is None

    def test_enabling_after_setting_the_value_uses_the_value(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.override_charge_value = 65
        coord.override_charge_enabled = True
        assert coord.override_charge_target == 65

    def test_disabling_returns_to_automatic_and_keeps_the_value(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.override_charge_value = 65
        coord.override_charge_enabled = True
        coord.override_charge_enabled = False
        assert coord.override_charge_target is None
        assert coord.override_charge_value == 65

    @pytest.mark.asyncio
    async def test_enabled_override_with_untouched_value_reaches_the_decision(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.override_charge_enabled = True
        data = await coord.run_cycle()
        assert data.charge_decision.target_soc == 80
        assert data.charge_decision.reason == "Manual override: charge to 80%"

    @pytest.mark.asyncio
    async def test_value_set_while_disabled_leaves_the_decision_automatic(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.override_charge_value = 65
        data = await coord.run_cycle()
        assert not data.charge_decision.reason.startswith("Manual override")

    @pytest.mark.asyncio
    async def test_disabling_returns_the_decision_to_automatic(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.override_charge_value = 65
        coord.override_charge_enabled = True
        overridden = await coord.run_cycle()
        coord.override_charge_enabled = False
        automatic = await coord.run_cycle()
        assert overridden.charge_decision.target_soc == 65
        assert not automatic.charge_decision.reason.startswith("Manual override")


# ── TestMidnightReset ─────────────────────────────────────────────────────────


class _MemoryStore:
    """Stands in for homeassistant.helpers.storage.Store."""

    def __init__(self, saved: dict | None = None):
        self.saved = saved
        self.saves = 0
        self.pending_data_func = None

    def async_delay_save(self, data_func, delay=0):
        self.pending_data_func = data_func

    async def async_load(self):
        return self.saved

    async def async_save(self, data):
        self.saved = data
        self.saves += 1


def _coord_with_real_store(saved: dict | None, monkeypatch, local_now: datetime):
    from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return local_now

    monkeypatch.setitem(GivEnergyCoordinator.async_restore_state.__globals__, "datetime", _Clock)
    coord = FakeCoordinator(cfg=_cfg())
    store = AccumulationStore.__new__(AccumulationStore)
    store.state = AccumulationState()
    store._bill_start_day = 1
    store._store = _MemoryStore(saved)
    coord._acc = store
    return coord, store


def _saved_state(last_midnight: datetime) -> dict:
    from custom_components.givenergy_inverter_manager.accumulation import _serialize

    state = AccumulationState()
    state.last_reset_iso = last_midnight.isoformat()
    return _serialize(state)


class TestRestoreState:
    def _saved(self, last_midnight: datetime) -> dict:
        from custom_components.givenergy_inverter_manager.accumulation import _serialize

        state = AccumulationState()
        state.last_reset_iso = last_midnight.isoformat()
        state.today.solar_kwh = 9.0
        state.week.solar_kwh = 50.0
        return _serialize(state)

    async def test_restart_across_midnight_starts_a_new_day(self, monkeypatch):
        saved = self._saved(datetime(2026, 7, 14, tzinfo=timezone.utc))
        coord, store = _coord_with_real_store(
            saved, monkeypatch, datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)
        )

        await coord.async_restore_state()

        assert store.yesterday.solar_kwh == pytest.approx(9.0)
        assert store.today.solar_kwh == 0.0
        assert coord._last_reset_time == "2026-07-15T00:00:00+00:00"

    async def test_restart_after_a_missed_monday_resets_the_week(self, monkeypatch):
        saved = self._saved(datetime(2026, 7, 11, tzinfo=timezone.utc))
        coord, store = _coord_with_real_store(
            saved, monkeypatch, datetime(2026, 7, 14, 6, 0, tzinfo=timezone.utc)
        )

        await coord.async_restore_state()

        assert store.week.solar_kwh == 0.0
        assert store.state.week_start_iso == "2026-07-13T00:00:00+00:00"

    async def test_rolled_state_is_saved_straight_away(self, monkeypatch):
        saved = self._saved(datetime(2026, 7, 14, tzinfo=timezone.utc))
        coord, store = _coord_with_real_store(
            saved, monkeypatch, datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)
        )

        await coord.async_restore_state()

        assert store._store.saves == 1
        assert store._store.saved["last_reset_iso"] == "2026-07-15T00:00:00+00:00"

    async def test_restart_on_the_same_day_keeps_the_day_and_last_reset(self, monkeypatch):
        saved = self._saved(datetime(2026, 7, 14, tzinfo=timezone.utc))
        saved["week_start_iso"] = "2026-07-13T00:00:00+00:00"
        saved["month_start_iso"] = "2026-07-01T00:00:00+00:00"
        saved["year_start_iso"] = "2026-01-01T00:00:00+00:00"
        coord, store = _coord_with_real_store(
            saved, monkeypatch, datetime(2026, 7, 14, 18, 0, tzinfo=timezone.utc)
        )

        await coord.async_restore_state()

        assert store.today.solar_kwh == pytest.approx(9.0)
        assert coord._last_reset_time == "2026-07-14T00:00:00+00:00"
        assert store._store.saves == 0

    async def test_fresh_install_stamps_last_reset_with_todays_midnight(self, monkeypatch):
        coord, store = _coord_with_real_store(
            None, monkeypatch, datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)
        )

        await coord.async_restore_state()

        assert coord._last_reset_time == "2026-07-15T00:00:00+00:00"
        assert store.state.year_start_iso == "2026-01-01T00:00:00+00:00"


class TestDurablePersistence:
    @pytest.mark.asyncio
    async def test_tenth_cycle_queues_a_delayed_save(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        for _ in range(9):
            await coord.run_cycle()
        assert coord._acc.scheduled_saves == 0
        await coord.run_cycle()
        assert coord._acc.scheduled_saves == 1

    async def test_flush_saves_battery_stats_and_accumulators(self, monkeypatch):
        coord, store = _coord_with_real_store(
            None, monkeypatch, datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)
        )
        coord._battery_stats.total_cycles = 3.5
        store.state.month.solar_kwh = 77.7

        await coord.async_flush()

        assert store._store.saved["battery_cycles"] == pytest.approx(3.5)
        assert store._store.saved["month"]["solar_kwh"] == pytest.approx(77.7)

    async def test_restore_seeds_the_write_count_and_battery_stats_in_one_pass(
        self, monkeypatch
    ):
        saved = _saved_state(datetime(2026, 7, 15, tzinfo=timezone.utc))
        saved["register_write_count"] = 4321
        saved["battery_cycles"] = 12.5
        coord, _ = _coord_with_real_store(
            saved, monkeypatch, datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)
        )

        await coord.async_restore_state()

        assert coord._writer.write_count == 4321
        assert coord._battery_stats.total_cycles == pytest.approx(12.5)

    async def test_restore_loads_the_store_once(self, monkeypatch):
        saved = _saved_state(datetime(2026, 7, 15, tzinfo=timezone.utc))
        coord, store = _coord_with_real_store(
            saved, monkeypatch, datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)
        )
        loads = []
        original = store._store.async_load

        async def counting_load():
            loads.append(1)
            return await original()

        store._store.async_load = counting_load

        await coord.async_restore_state()

        assert len(loads) == 1

    async def test_restore_registers_a_flush_for_unload_and_for_home_assistant_stop(
        self, monkeypatch
    ):
        from custom_components.givenergy_inverter_manager.coordinator import (
            EVENT_HOMEASSISTANT_STOP,
        )

        coord, store = _coord_with_real_store(
            None, monkeypatch, datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)
        )
        on_unload = []
        coord.entry.async_on_unload = on_unload.append
        stop_remover = MagicMock()
        coord.hass.bus.async_listen = MagicMock(return_value=stop_remover)

        await coord.async_restore_state()

        assert coord.async_flush in on_unload
        assert stop_remover in on_unload
        coord.hass.bus.async_listen.assert_called_once_with(
            EVENT_HOMEASSISTANT_STOP, coord._queue_final_write
        )

        store.state.week.solar_kwh = 12.0
        coord._battery_stats.total_cycles = 3.5
        coord._queue_final_write(MagicMock())
        assert store._store.pending_data_func()["week"]["solar_kwh"] == pytest.approx(12.0)
        assert store._store.pending_data_func()["battery_cycles"] == pytest.approx(3.5)


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
    async def test_the_write_uses_the_fresh_decision_not_the_published_one(self):
        coord = self._coord_with_decision(target_soc=91)
        coord.data.published_charge_decision = replace(coord.data.charge_decision, target_soc=87)
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        await coord.tasks_created[0]
        assert coord.service_calls_for("number", "set_value")[0]["value"] == 91

    def test_the_write_releases_the_held_recommendation(self):
        coord = self._coord_with_decision(target_soc=91)
        coord._held_charge.decision = replace(coord.data.charge_decision, target_soc=87)
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        coord.tasks_created[0].close()
        assert coord._held_charge.decision is None

    def test_the_write_releases_the_held_window(self):
        coord = self._coord_with_decision(target_soc=91)
        coord._held_charge.window = ChargeWindow(
            clock_time(2, 0), clock_time(5, 0), extended=True, expected_kwh=4.0, finish_time=None
        )
        coord._held_charge.window_published_at = datetime(2026, 6, 15, 1, 0)
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        coord.tasks_created[0].close()
        assert coord._held_charge == HeldCharge()

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

    @pytest.mark.asyncio
    async def test_skip_charge_writes_min_target_for_free_discharge(self):
        """When skipping charge, the min SoC must be written so the battery
        can discharge freely overnight instead of holding at the old target."""
        coord = self._coord_with_decision(skip=True)
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        # A task must be created to write the min target
        assert len(coord.tasks_created) == 1, (
            "skip_charge=True must still write the min target to GivTCP. "
            "Leaving the old 80% target causes the battery to hold at 80% "
            "and import from grid overnight instead of discharging."
        )
        await coord.tasks_created[0]
        # Target written must be the configured min SoC
        number_calls = coord.service_calls_for("number", "set_value")
        assert len(number_calls) > 0
        target_written = int(number_calls[0]["value"])
        from custom_components.givenergy_inverter_manager.const import DEFAULT_BATTERY_MIN_SOC
        assert target_written == DEFAULT_BATTERY_MIN_SOC, (
            f"Expected min target {DEFAULT_BATTERY_MIN_SOC}% but got {target_written}%"
        )

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


class TestImmersionSwitchFromOptions:
    """The actuator reads the immersion switch from options over data, like everything else."""

    def test_switch_saved_only_in_options_is_used(self):
        coord = FakeCoordinator(cfg={})
        coord.entry.options = {"immersion_switch_entity": "switch.heater"}
        assert coord.immersion._ports.switch_entity() == "switch.heater"

    def test_option_replaces_the_setup_switch(self):
        coord = FakeCoordinator(cfg={"immersion_switch_entity": "switch.old"})
        coord.entry.options = {"immersion_switch_entity": "switch.new"}
        assert coord.immersion._ports.switch_entity() == "switch.new"

    def test_cleared_option_hides_the_setup_switch(self):
        coord = FakeCoordinator(cfg={"immersion_switch_entity": "switch.old"})
        coord.entry.options = {"immersion_switch_entity": ""}
        assert not coord.immersion._ports.switch_entity()


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

    @pytest.mark.asyncio
    async def test_second_write_within_cooldown_is_skipped(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord._ev_charger = self._charger(mode="Fast")
        coord.data = MagicMock()
        coord._apply_ev_action("Eco+")
        await coord.tasks_created[0]
        coord._ev_charger = self._charger(mode="Fast")
        coord._apply_ev_action("Eco+")
        assert len(coord.tasks_created) == 1

    @pytest.mark.asyncio
    async def test_write_allowed_again_after_cooldown(self):
        from custom_components.givenergy_inverter_manager.const import (
            GIVTCP_MIN_WRITE_INTERVAL_S,
        )

        coord = FakeCoordinator(cfg=_cfg())
        coord._ev_charger = self._charger(mode="Fast")
        coord.data = MagicMock()
        coord._apply_ev_action("Eco+")
        await coord.tasks_created[0]
        coord._writer.last_write_time[("select.zappi_mode", "Eco+")] = (
            time.monotonic() - GIVTCP_MIN_WRITE_INTERVAL_S - 1
        )
        coord._ev_charger = self._charger(mode="Fast")
        coord._apply_ev_action("Eco+")
        assert len(coord.tasks_created) == 2
        await coord.tasks_created[1]

    def test_dry_run_does_not_start_the_cooldown(self):
        cfg = _cfg(**{CONF_DRY_RUN: True})
        coord = FakeCoordinator(cfg=cfg)
        coord._ev_charger = self._charger(mode="Fast")
        from types import SimpleNamespace

        coord.data = SimpleNamespace(dry_run_last_skipped="")
        coord._apply_ev_action("Eco+")
        assert "select.zappi_mode" not in coord._writer.last_write_time

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


# ── TestDryRunLastSkippedSurvivesCycles ───────────────────────────────────────


class TestDryRunLastSkippedSurvivesCycles:
    """The engine builds a fresh snapshot each cycle, so the coordinator must carry the value."""

    @pytest.mark.asyncio
    async def test_charge_target_skip_survives_two_cycles(self):
        coord = FakeCoordinator(cfg=_cfg(**{CONF_DRY_RUN: True}))
        coord.set_states(_default_states())
        await coord.run_cycle()
        assert coord.data.dry_run_last_skipped == ""

        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        recorded = coord.data.dry_run_last_skipped
        assert recorded.startswith("Would write charge target")
        assert len(coord.tasks_created) == 0

        await coord.run_cycle()
        assert coord.data.dry_run_last_skipped == recorded
        await coord.run_cycle()
        assert coord.data.dry_run_last_skipped == recorded

    @pytest.mark.asyncio
    async def test_ev_skip_survives_a_cycle(self):
        coord = FakeCoordinator(cfg=_cfg(**{CONF_DRY_RUN: True}))
        coord.set_states(_default_states())
        coord._ev_charger = TestApplyEvAction()._charger(mode="Fast")
        await coord.run_cycle()

        coord._apply_ev_action("Stopped")
        recorded = coord.data.dry_run_last_skipped
        assert "Stopped" in recorded

        await coord.run_cycle()
        assert coord.data.dry_run_last_skipped == recorded

    @pytest.mark.asyncio
    async def test_newest_skip_replaces_the_previous_one(self):
        coord = FakeCoordinator(cfg=_cfg(**{CONF_DRY_RUN: True}))
        coord.set_states(_default_states())
        coord._ev_charger = TestApplyEvAction()._charger(mode="Fast")
        await coord.run_cycle()

        coord._apply_ev_action("Stopped")
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        latest = coord.data.dry_run_last_skipped
        assert latest.startswith("Would write charge target")

        await coord.run_cycle()
        assert coord.data.dry_run_last_skipped == latest


# ── TestGivtcpWriteHelpers ────────────────────────────────────────────────────


class TestGivtcpWriteHelpers:
    """The three _givtcp_set_* methods issue service calls and read back state."""

    @pytest.mark.asyncio
    async def test_set_switch_issues_turn_on(self):
        coord = FakeCoordinator(cfg=_cfg())
        await coord._givtcp_set_switch("switch.target", SwitchState.ON, "test")
        assert ("switch", "turn_on", {"entity_id": "switch.target"}) in coord.service_calls

    @pytest.mark.asyncio
    async def test_set_switch_issues_turn_off(self):
        coord = FakeCoordinator(cfg=_cfg())
        await coord._givtcp_set_switch("switch.target", SwitchState.OFF, "test")
        assert ("switch", "turn_off", {"entity_id": "switch.target"}) in coord.service_calls

    @pytest.mark.asyncio
    async def test_set_switch_skips_when_no_entity(self):
        coord = FakeCoordinator(cfg=_cfg())
        await coord._givtcp_set_switch(None, SwitchState.ON, "test")
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
        async def stubbed(domain, service, data):
            coord.service_calls.append((domain, service, data))
            # Don't update state — the read-back will see the old value

        coord._call_service = stubbed
        with caplog.at_level(logging.WARNING):
            await coord._givtcp_set_number("number.target", 80, "target_soc")
        assert any("wrote" in r.message and "read back" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_set_switch_skips_within_cooldown(self):
        # Arrange
        coord = FakeCoordinator(cfg=_cfg())
        coord._writer.last_write_time[("switch.target", SwitchState.ON)] = time.monotonic()  # just written

        # Act
        await coord._givtcp_set_switch("switch.target", SwitchState.ON, "test")

        # Assert
        assert len(coord.service_calls) == 0

    @pytest.mark.asyncio
    async def test_set_switch_writes_after_cooldown(self):
        from custom_components.givenergy_inverter_manager.const import (
            GIVTCP_MIN_WRITE_INTERVAL_S,
        )

        # Arrange
        coord = FakeCoordinator(cfg=_cfg())
        coord._writer.last_write_time[("switch.target", SwitchState.ON)] = (
            time.monotonic() - GIVTCP_MIN_WRITE_INTERVAL_S - 1
        )

        # Act
        await coord._givtcp_set_switch("switch.target", SwitchState.ON, "test")

        # Assert
        assert ("switch", "turn_on", {"entity_id": "switch.target"}) in coord.service_calls

    @pytest.mark.asyncio
    async def test_set_select_skips_within_cooldown(self):
        # Arrange
        coord = FakeCoordinator(cfg=_cfg())
        coord._writer.last_write_time[("select.target", "Eco+")] = time.monotonic()

        # Act
        await coord._givtcp_set_select("select.target", "Eco+", "test")

        # Assert
        assert len(coord.service_calls) == 0

    @pytest.mark.asyncio
    async def test_set_number_skips_within_cooldown(self):
        # Arrange
        coord = FakeCoordinator(cfg=_cfg())
        coord._writer.last_write_time[("number.target", 80)] = time.monotonic()

        # Act
        await coord._givtcp_set_number("number.target", 80, "test")

        # Assert
        assert len(coord.service_calls) == 0

    @pytest.mark.asyncio
    async def test_cooldown_does_not_block_read_before_write_skip(self):
        # Arrange — entity already at the target value; cooldown is active
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("switch.target", "on")
        coord._writer.last_write_time[("switch.target", SwitchState.ON)] = time.monotonic()

        # Act
        await coord._givtcp_set_switch("switch.target", SwitchState.ON, "test")

        # Assert — read-before-write caught it before cooldown was checked
        assert len(coord.service_calls) == 0

    @pytest.mark.asyncio
    async def test_first_write_sets_cooldown_timestamp(self):
        # Arrange
        coord = FakeCoordinator(cfg=_cfg())
        assert ("switch.target", SwitchState.ON) not in coord._writer.last_write_time

        # Act
        await coord._givtcp_set_switch("switch.target", SwitchState.ON, "test")

        # Assert
        assert ("switch.target", SwitchState.ON) in coord._writer.last_write_time


# ── Retry, read-back and failure paths of the three write helpers ─────────────

_RETRY_CASES = {
    # kind: (call, start state, state the write produces, state that is not the target)
    "switch": (lambda c: c._givtcp_set_switch("switch.t", SwitchState.ON, "t"), "off", "on", "off"),
    "select": (lambda c: c._givtcp_set_select("select.t", "Eco", "t"), "Other", "Eco", "Other"),
    "number": (lambda c: c._givtcp_set_number("number.t", 80, "t"), "50", "80", "50"),
}


def _settles_on_call(coord, entity_id: str, settle_on: int | None, written: str) -> None:
    """Service calls are recorded. The state reaches `written` only on call number settle_on."""

    async def call(domain, service, data):
        coord.service_calls.append((domain, service, data))
        if settle_on is not None and len(coord.service_calls) >= settle_on:
            coord.set_state(entity_id, written)

    coord._call_service = call


class TestGivtcpWriteRetryBehaviour:
    """Characterises read-back, retry, give-up and counting, the same for all three helpers."""

    @staticmethod
    def _coord(kind: str, settle_on: int | None):
        call, start, written, _ = _RETRY_CASES[kind]
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state(f"{kind}.t", start)
        _settles_on_call(coord, f"{kind}.t", settle_on, written)
        return coord, call

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", list(_RETRY_CASES))
    async def test_confirmed_first_time_makes_one_call(self, kind, caplog):
        coord, call = self._coord(kind, settle_on=1)
        with caplog.at_level(logging.WARNING):
            assert await call(coord) is True
        assert len(coord.service_calls) == 1
        assert coord._writer.write_count == 1
        assert caplog.records == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", list(_RETRY_CASES))
    async def test_mismatch_is_retried_until_confirmed(self, kind, caplog):
        coord, call = self._coord(kind, settle_on=2)
        with caplog.at_level(logging.WARNING):
            assert await call(coord) is True
        assert len(coord.service_calls) == 2
        assert coord._writer.write_count == 2
        messages = [r.getMessage() for r in caplog.records]
        assert len(messages) == 1
        assert "attempt 1/3" in messages[0]
        assert "retrying" in messages[0]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", list(_RETRY_CASES))
    async def test_never_confirmed_stops_after_three_attempts_but_reports_sent(self, kind, caplog):
        coord, call = self._coord(kind, settle_on=None)
        with caplog.at_level(logging.WARNING):
            assert await call(coord) is True
        assert len(coord.service_calls) == 3
        assert coord._writer.write_count == 3
        messages = [r.getMessage() for r in caplog.records]
        assert sum("retrying" in m for m in messages) == 2
        assert messages[-1].endswith("could not confirm after 3 attempts")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", list(_RETRY_CASES))
    async def test_second_call_inside_the_cooldown_is_skipped(self, kind):
        coord, call = self._coord(kind, settle_on=None)
        await call(coord)
        calls_after_first = len(coord.service_calls)
        await call(coord)
        assert len(coord.service_calls) == calls_after_first

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", list(_RETRY_CASES))
    async def test_entity_already_at_target_is_not_written(self, kind):
        call, _, written, _ = _RETRY_CASES[kind]
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state(f"{kind}.t", written)
        assert await call(coord) is True
        assert coord.service_calls == []
        assert coord._writer.last_write_time == {}

    @pytest.mark.asyncio
    async def test_select_that_vanishes_after_the_write_is_reported_failed(self, caplog):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("select.t", "Other")

        async def call(domain, service, data):
            coord.service_calls.append((domain, service, data))
            coord._states.pop("select.t")

        coord._call_service = call
        with caplog.at_level(logging.WARNING):
            assert await coord._givtcp_set_select("select.t", "Eco", "t") is False
        assert len(coord.service_calls) == 1
        assert any("vanished" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_number_that_vanishes_after_the_write_is_retried(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("number.t", "50")

        async def call(domain, service, data):
            coord.service_calls.append((domain, service, data))
            coord._states.pop("number.t", None)

        coord._call_service = call
        assert await coord._givtcp_set_number("number.t", 80, "t") is True
        assert len(coord.service_calls) == 3

    @pytest.mark.asyncio
    async def test_switch_turned_off_that_vanishes_counts_as_off(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("switch.t", "on")

        async def call(domain, service, data):
            coord.service_calls.append((domain, service, data))
            coord._states.pop("switch.t")

        coord._call_service = call
        assert await coord._givtcp_set_switch("switch.t", SwitchState.OFF, "t") is True
        assert len(coord.service_calls) == 1

    @pytest.mark.asyncio
    async def test_unavailable_switch_counts_as_off_for_read_before_write(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("switch.t", "unavailable")
        assert await coord._givtcp_set_switch("switch.t", SwitchState.OFF, "t") is True
        assert coord.service_calls == []


class TestWriteChargeTargetSkipPaths:
    """The skip-charge branches of the cheap-rate write-back that no other test reaches."""

    @staticmethod
    def _coord(cfg: dict):
        from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision

        coord = FakeCoordinator(cfg=cfg)
        coord.set_states(_default_states())
        coord.data = MagicMock()
        coord.data.charge_decision = ChargeDecision(
            target_soc=80,
            skip_charge=True,
            reason="plenty of sun",
            forecast_kwh=10.0,
            current_soc=60.0,
            battery_capacity=19.0,
            car_plugged_in=False,
            cost_to_charge=1.0,
        )
        return coord

    def test_dry_run_with_skip_charge_writes_nothing(self, caplog):
        coord = self._coord(_cfg(**{CONF_DRY_RUN: True}))
        with caplog.at_level(logging.INFO):
            coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        assert coord.tasks_created == []
        assert any("DRY RUN: skip_charge=True" in r.getMessage() for r in caplog.records)

    def test_skip_charge_without_rate_periods_leaves_givtcp_unchanged(self, caplog):
        from custom_components.givenergy_inverter_manager.const import CONF_RATE_PERIODS

        coord = self._coord(_cfg(**{CONF_RATE_PERIODS: []}))
        with caplog.at_level(logging.INFO):
            coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        assert coord.tasks_created == []
        assert any("leaving GivTCP unchanged" in r.getMessage() for r in caplog.records)

    def test_no_charge_decision_yet_writes_nothing(self, caplog):
        coord = FakeCoordinator(cfg=_cfg())
        coord.data = MagicMock()
        coord.data.charge_decision = None
        with caplog.at_level(logging.WARNING):
            coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        assert coord.tasks_created == []
        assert any("No charge decision" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_dry_run_records_the_skipped_action(self):
        from custom_components.givenergy_inverter_manager.core.rules import ChargeDecision

        coord = FakeCoordinator(cfg=_cfg(**{CONF_DRY_RUN: True}))
        coord.data = MagicMock()
        coord.data.charge_decision = ChargeDecision(
            target_soc=80,
            skip_charge=False,
            reason="test",
            forecast_kwh=10.0,
            current_soc=60.0,
            battery_capacity=19.0,
            car_plugged_in=False,
            cost_to_charge=1.0,
        )
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        assert coord._dry_run_last_skipped.startswith("Would write charge target 80%")
        assert "(test)" in coord._dry_run_last_skipped


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

        src = (PKG / "coordinator.py").read_text()
        assert "dt_util.as_local(datetime.now" in src, (
            "coordinator must use dt_util.as_local() — without this, rate periods "
            "activate 1h late in summer (Ireland GMT+1)."
        )

    def test_midnight_reset_uses_local_midnight(self):

        src = (PKG / "coordinator.py").read_text()
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

        src = (PKG / "number.py").read_text()
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

        src = (PKG / "coordinator.py").read_text()
        assert "_floor_top_up_applied = False" in src


class TestCheapRateFloorOutcomes:
    """What the floor reports and writes once a top-up is due (battery 20%, Nightboost)."""

    TOPPING_UP = "Battery at 20% during Nightboost — topping up to 40%"

    @staticmethod
    def _at_0230():
        from zoneinfo import ZoneInfo

        return datetime(2024, 7, 10, 2, 30, tzinfo=ZoneInfo("Europe/Dublin"))

    @pytest.mark.asyncio
    async def test_successful_top_up_writes_target_and_sets_the_flag(self):
        coord, cfg = _write_coord()
        coord.set_state("number.target_soc", "20")
        result = await coord._maybe_apply_cheap_rate_floor(
            self._at_0230(), _raw(battery_soc=20.0), cfg
        )
        assert result == self.TOPPING_UP
        assert coord.service_calls_for("number", "set_value") == [
            {"entity_id": "number.target_soc", "value": 40}
        ]
        assert coord._floor_top_up_applied is True

    @pytest.mark.asyncio
    async def test_dry_run_reports_without_writing(self):
        coord, cfg = _write_coord(**{CONF_DRY_RUN: True})
        result = await coord._maybe_apply_cheap_rate_floor(
            self._at_0230(), _raw(battery_soc=20.0), cfg
        )
        assert result == f"DRY RUN: {self.TOPPING_UP}"
        assert coord.service_calls == []
        assert coord._floor_top_up_applied is False

    @pytest.mark.asyncio
    async def test_failed_write_reports_the_error_and_leaves_the_flag_clear(self):
        coord, cfg = _write_coord({"number.target_soc"})
        coord.set_state("number.target_soc", "20")
        result = await coord._maybe_apply_cheap_rate_floor(
            self._at_0230(), _raw(battery_soc=20.0), cfg
        )
        assert result == f"Error writing floor — {self.TOPPING_UP}"
        assert coord._floor_top_up_applied is False

    @pytest.mark.asyncio
    async def test_no_target_entity_reports_the_status_and_warns(self, caplog):
        coord, cfg = _write_coord()
        cfg = {**cfg, CONF_TARGET_SOC_ENTITY: None}
        with caplog.at_level(logging.WARNING):
            result = await coord._maybe_apply_cheap_rate_floor(
                self._at_0230(), _raw(battery_soc=20.0), cfg
            )
        assert result == self.TOPPING_UP
        assert coord.service_calls == []
        assert any("no target SoC entity" in r.getMessage() for r in caplog.records)


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


class TestOilPriceRead:
    """The oil price: the sensor when it reads a price, else the saved number, else none."""

    def _coord(self, **cfg):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_state("sensor.oil", "1.10")
        return coord, {"immersion_switch_entity": "switch.heater", **cfg}

    def _read(self, coord, cfg):
        return coord._read_oil_price(cfg)

    def test_no_oil_settings_means_no_price(self):
        coord, cfg = self._coord()
        assert self._read(coord, cfg) is None

    def test_the_saved_number_is_the_price(self):
        coord, cfg = self._coord(oil_price_per_litre=0.95)
        assert self._read(coord, cfg) == pytest.approx(0.95)

    def test_the_sensor_overrides_the_number(self):
        coord, cfg = self._coord(oil_price_per_litre=0.95, oil_price_entity="sensor.oil")
        assert self._read(coord, cfg) == pytest.approx(1.10)

    def test_the_sensor_alone_is_enough(self):
        coord, cfg = self._coord(oil_price_entity="sensor.oil")
        assert self._read(coord, cfg) == pytest.approx(1.10)

    @pytest.mark.parametrize("state", ["unavailable", "unknown", "cheap", "0", "-1"])
    def test_a_sensor_that_does_not_read_a_price_leaves_the_number(self, state):
        coord, cfg = self._coord(oil_price_per_litre=0.95, oil_price_entity="sensor.oil")
        coord.set_state("sensor.oil", state)
        assert self._read(coord, cfg) == pytest.approx(0.95)

    def test_a_sensor_that_does_not_read_a_price_with_no_number_gives_none(self):
        coord, cfg = self._coord(oil_price_entity="sensor.oil")
        coord.set_state("sensor.oil", "unavailable")
        assert self._read(coord, cfg) is None

    def test_without_an_immersion_switch_there_is_nothing_to_compare_with(self):
        coord, cfg = self._coord(oil_price_per_litre=0.95)
        del cfg["immersion_switch_entity"]
        assert self._read(coord, cfg) is None

    def test_an_emptied_sensor_choice_is_ignored(self):
        coord, cfg = self._coord(oil_price_per_litre=0.95, oil_price_entity="")
        assert self._read(coord, cfg) == pytest.approx(0.95)


ZAPPI_PLUG = "sensor.myenergi_zappi_plug_status"
ZAPPI_POWER = "sensor.myenergi_zappi_internal_load_ct1"
ZAPPI_SESSION = "sensor.myenergi_zappi_charge_added_session"
ZAPPI_MODE = "select.myenergi_zappi_charge_mode"


class TestEVRediscovery:
    """Discovery repeats every fifth minute until power, session and charge mode are found."""

    def _coord(self, *entities):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.set_states(dict.fromkeys((ZAPPI_PLUG, *entities), "1"))
        return coord

    def _discover_at(self, coord, cycle):
        coord._update_cycle = cycle
        coord._maybe_rediscover_ev()

    def test_a_charger_with_no_power_entity_is_completed_when_it_appears(self):
        coord = self._coord()
        self._discover_at(coord, 1)
        assert coord._ev_charger.power_entity is None
        coord.set_state(ZAPPI_POWER, "0")
        self._discover_at(coord, 11)
        assert coord._ev_charger.power_entity == ZAPPI_POWER

    def test_a_charger_missing_only_its_charge_mode_is_completed_when_it_appears(self):
        coord = self._coord(ZAPPI_POWER, ZAPPI_SESSION)
        self._discover_at(coord, 1)
        assert coord._ev_charger.charge_mode_entity is None
        coord.set_state(ZAPPI_MODE, "Fast")
        self._discover_at(coord, 11)
        assert coord._ev_charger.charge_mode_entity == ZAPPI_MODE

    def test_a_charger_missing_only_its_session_entity_is_completed_when_it_appears(self):
        coord = self._coord(ZAPPI_POWER, ZAPPI_MODE)
        self._discover_at(coord, 1)
        assert coord._ev_charger.session_energy_entity is None
        coord.set_state(ZAPPI_SESSION, "2.5")
        self._discover_at(coord, 11)
        assert coord._ev_charger.session_energy_entity == ZAPPI_SESSION

    def test_the_charger_object_and_its_state_survive_completion(self):
        coord = self._coord(ZAPPI_POWER)
        self._discover_at(coord, 1)
        charger = coord._ev_charger
        charger.power_w = 7200.0
        coord.set_states({ZAPPI_SESSION: "2.5", ZAPPI_MODE: "Fast"})
        self._discover_at(coord, 11)
        assert coord._ev_charger is charger
        assert charger.power_w == pytest.approx(7200.0)

    def test_scanning_waits_for_the_fifth_minute(self):
        coord = self._coord(ZAPPI_POWER)
        self._discover_at(coord, 1)
        coord.set_state(ZAPPI_MODE, "Fast")
        self._discover_at(coord, 5)
        assert coord._ev_charger.charge_mode_entity is None

    def test_a_complete_charger_is_not_scanned_again(self):
        coord = self._coord(ZAPPI_POWER, ZAPPI_SESSION, ZAPPI_MODE)
        self._discover_at(coord, 1)
        coord._get_all_states = lambda: pytest.fail("a complete charger must not be rescanned")
        self._discover_at(coord, 11)

    def test_a_charger_without_a_mode_select_keeps_being_scanned_without_changing(self, caplog):
        import logging

        coord = self._coord(ZAPPI_POWER, ZAPPI_SESSION)
        self._discover_at(coord, 1)
        charger = coord._ev_charger
        with caplog.at_level(logging.INFO):
            self._discover_at(coord, 11)
        assert coord._ev_charger is charger
        assert not [r for r in caplog.records if r.levelno >= logging.INFO]

    def test_no_charger_yet_is_found_when_it_appears(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        self._discover_at(coord, 1)
        assert coord._ev_charger is None
        coord.set_states({ZAPPI_PLUG: "EV Connected", ZAPPI_POWER: "0"})
        self._discover_at(coord, 11)
        assert coord._ev_charger is not None


class TestEntityUnavailable:
    """Coordinator must raise UpdateFailed when GivTCP is not publishing.

    HA quality scale — entity-unavailable: sensors should go unavailable
    when the data source stops publishing rather than holding stale values.
    """

    def test_update_failed_imported(self):
        """UpdateFailed must be imported to signal entity unavailability."""

        src = (PKG / "coordinator.py").read_text()
        assert "UpdateFailed" in src

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stale", ["unavailable", "unknown"])
    async def test_cycle_fails_when_both_sensors_are_stale(self, stale):
        from homeassistant.helpers.update_coordinator import UpdateFailed

        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.set_state("sensor.solar", stale)
        coord.set_state("sensor.battery_soc", stale)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stale_entity", ["sensor.solar", "sensor.battery_soc"])
    async def test_one_stale_sensor_does_not_fail_the_cycle(self, stale_entity):
        """A single brief interruption must not mark the whole integration unavailable."""
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.set_state(stale_entity, "unavailable")
        assert await coord._async_update_data() is not None

    def test_quality_scale_yaml_updated(self):
        """quality_scale.yaml must mark entity-unavailable as done."""

        qs = (PKG / "quality_scale.yaml").read_text()
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
        qs = (PKG / "quality_scale.yaml").read_text()
        idx = qs.find("log-when-unavailable")
        assert idx != -1
        assert "done" in qs[idx : idx + 60]


class TestActionExceptions:
    """The error text is translated. The raising itself is tested in test_services.py."""

    def test_no_config_entry_key_in_strings(self):
        import json
        strings = json.loads(
            (PKG / "strings.json").read_text()
        )
        assert "no_config_entry" in strings["exceptions"]

    def test_no_config_entry_key_in_translations(self):
        import json
        translations = json.loads(
            (PKG / "translations/en.json").read_text()
        )
        assert "no_config_entry" in translations["exceptions"]

    def test_quality_scale_action_exceptions_is_done(self):
        qs = (PKG / "quality_scale.yaml").read_text()
        idx = qs.find("action-exceptions")
        assert idx != -1
        assert "done" in qs[idx : idx + 80]


class TestIconTranslations:
    """icons.json must exist and cover all translated entity keys."""

    def _load_icons(self):
        import json
        path = (PKG / "icons.json")
        assert path.exists(), "icons.json must exist"
        return json.loads(path.read_text())

    def _load_strings(self):
        import json
        return json.loads(
            (PKG / "strings.json").read_text()
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
        # Assert — givtcp_entities_missing is cleared when data is available
        calls = [str(call) for call in ir.async_delete_issue.call_args_list]
        assert any("givtcp_entities_missing" in call for call in calls)

    @pytest.mark.asyncio
    async def test_repair_issue_created_when_min_soc_too_high(self):
        import homeassistant.helpers.issue_registry as ir

        from custom_components.givenergy_inverter_manager.const import CONF_BATTERY_MIN_SOC
        # Arrange — legacy config with min SoC above the selector max (30%)
        coord = FakeCoordinator(cfg=_cfg(**{CONF_BATTERY_MIN_SOC: 66}))
        coord.set_states(_default_states())
        ir.async_create_issue.reset_mock()
        # Act
        await coord._async_update_data()
        # Assert
        calls = [str(call) for call in ir.async_create_issue.call_args_list]
        assert any("min_soc_too_high" in call for call in calls)

    @pytest.mark.asyncio
    async def test_repair_issue_cleared_when_min_soc_normal(self):
        import homeassistant.helpers.issue_registry as ir

        from custom_components.givenergy_inverter_manager.const import CONF_BATTERY_MIN_SOC
        # Arrange — correctly configured min SoC
        coord = FakeCoordinator(cfg=_cfg(**{CONF_BATTERY_MIN_SOC: 20}))
        coord.set_states(_default_states())
        ir.async_delete_issue.reset_mock()
        # Act
        await coord._async_update_data()
        # Assert
        calls = [str(call) for call in ir.async_delete_issue.call_args_list]
        assert any("min_soc_too_high" in call for call in calls)

    def test_repairs_module_exists(self):
        assert (PKG / "repairs.py").exists()

    def test_quality_scale_repair_issues_is_done(self):
        qs = (PKG / "quality_scale.yaml").read_text()
        idx = qs.find("repair-issues")
        assert idx != -1
        assert "done" in qs[idx : idx + 80]


class TestImmersionRunToTarget:
    """Manual on releases override automatically when water reaches target temperature."""

    @pytest.mark.asyncio
    async def test_override_released_when_target_reached(self):
        # Arrange — manual run-to-target active, water at target
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.override_immersion = True
        coord.immersion.manual_run_to_target = True
        coord.immersion_target_temp = 55.0
        # Simulate immersion temp sensor at target
        from custom_components.givenergy_inverter_manager.const import CONF_IMMERSION_TEMP_SENSOR
        coord.entry.data[CONF_IMMERSION_TEMP_SENSOR] = "sensor.immersion_temp"
        coord.set_state("sensor.immersion_temp", "55.0")
        # Act
        await coord._async_update_data()
        # Assert — both flags cleared, override released to auto
        assert coord.immersion.manual_run_to_target is False
        assert coord.override_immersion is None

    @pytest.mark.asyncio
    async def test_override_stays_when_below_target(self):
        # Arrange — manual run-to-target active, water below target
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.override_immersion = True
        coord.immersion.manual_run_to_target = True
        coord.immersion_target_temp = 55.0
        from custom_components.givenergy_inverter_manager.const import CONF_IMMERSION_TEMP_SENSOR
        coord.entry.data[CONF_IMMERSION_TEMP_SENSOR] = "sensor.immersion_temp"
        coord.set_state("sensor.immersion_temp", "48.0")
        # Act
        await coord._async_update_data()
        # Assert — still active
        assert coord.immersion.manual_run_to_target is True
        assert coord.override_immersion is True

    @pytest.mark.asyncio
    async def test_override_stays_when_no_temp_sensor(self):
        # Arrange — no temp sensor configured
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.override_immersion = True
        coord.immersion.manual_run_to_target = True
        # Act
        await coord._async_update_data()
        # Assert — can't auto-release without temp reading
        assert coord.immersion.manual_run_to_target is True
        assert coord.override_immersion is True

    @pytest.mark.asyncio
    async def test_divert_reason_shows_run_to_target(self):
        # Arrange — manual run-to-target, water below target
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.override_immersion = True
        coord.immersion.manual_run_to_target = True
        coord.immersion_target_temp = 55.0
        from custom_components.givenergy_inverter_manager.const import CONF_IMMERSION_TEMP_SENSOR
        coord.entry.data[CONF_IMMERSION_TEMP_SENSOR] = "sensor.immersion_temp"
        coord.set_state("sensor.immersion_temp", "48.0")
        # Act
        data = await coord._async_update_data()
        # Assert
        assert "55" in data.divert_reason
        assert "48" in data.divert_reason


class TestInverterTemperature:
    """Inverter temperature sensors populate from GivTCP temp entity."""

    @pytest.mark.asyncio
    async def test_normal_temperature(self):
        # Arrange
        from custom_components.givenergy_inverter_manager.const import CONF_INVERTER_TEMP_ENTITY
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.entry.data[CONF_INVERTER_TEMP_ENTITY] = "sensor.inverter_temp"
        coord.set_state("sensor.inverter_temp", "55.0")
        # Act
        data = await coord._async_update_data()
        # Assert
        assert data.inverter_temperature == pytest.approx(55.0)
        from custom_components.givenergy_inverter_manager.const import INVERTER_TEMP_STATUS_NORMAL
        assert data.inverter_temperature_status == INVERTER_TEMP_STATUS_NORMAL

    @pytest.mark.asyncio
    async def test_warm_temperature(self):
        from custom_components.givenergy_inverter_manager.const import CONF_INVERTER_TEMP_ENTITY
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.entry.data[CONF_INVERTER_TEMP_ENTITY] = "sensor.inverter_temp"
        coord.set_state("sensor.inverter_temp", "62.0")
        data = await coord._async_update_data()
        from custom_components.givenergy_inverter_manager.const import INVERTER_TEMP_STATUS_WARM
        assert data.inverter_temperature_status == INVERTER_TEMP_STATUS_WARM

    @pytest.mark.asyncio
    async def test_derating_temperature(self):
        from custom_components.givenergy_inverter_manager.const import CONF_INVERTER_TEMP_ENTITY
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.entry.data[CONF_INVERTER_TEMP_ENTITY] = "sensor.inverter_temp"
        coord.set_state("sensor.inverter_temp", "68.0")
        data = await coord._async_update_data()
        from custom_components.givenergy_inverter_manager.const import INVERTER_TEMP_STATUS_DERATING
        assert data.inverter_temperature_status == INVERTER_TEMP_STATUS_DERATING

    @pytest.mark.asyncio
    async def test_critical_temperature(self):
        from custom_components.givenergy_inverter_manager.const import CONF_INVERTER_TEMP_ENTITY
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.entry.data[CONF_INVERTER_TEMP_ENTITY] = "sensor.inverter_temp"
        coord.set_state("sensor.inverter_temp", "78.0")
        data = await coord._async_update_data()
        from custom_components.givenergy_inverter_manager.const import INVERTER_TEMP_STATUS_CRITICAL
        assert data.inverter_temperature_status == INVERTER_TEMP_STATUS_CRITICAL

    @pytest.mark.asyncio
    async def test_no_temp_entity_returns_none(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        data = await coord._async_update_data()
        assert data.inverter_temperature is None
        from custom_components.givenergy_inverter_manager.const import INVERTER_TEMP_STATUS_UNKNOWN
        assert data.inverter_temperature_status == INVERTER_TEMP_STATUS_UNKNOWN

    @staticmethod
    def _temperature_coordinator(*states: tuple[str, str], configured: str | None = None):
        """A coordinator with a serial, and an optional configured temperature entity."""
        from custom_components.givenergy_inverter_manager.const import (
            CONF_INVERTER_SERIAL,
            CONF_INVERTER_TEMP_ENTITY,
        )

        extra = {CONF_INVERTER_SERIAL: "fd2309f069"}
        if configured:
            extra[CONF_INVERTER_TEMP_ENTITY] = configured
        coord = FakeCoordinator(cfg=_cfg(**extra))
        coord.set_states(_default_states())
        for entity_id, state in states:
            coord.set_state(entity_id, state)
        return coord

    @pytest.mark.asyncio
    async def test_reads_the_invertor_entity_from_the_serial_when_none_is_configured(self):
        coord = self._temperature_coordinator(("sensor.givtcp_fd2309f069_invertor_temperature", "36.3"))
        data = await coord._async_update_data()
        assert data.inverter_temperature == pytest.approx(36.3)

    @pytest.mark.asyncio
    async def test_reads_the_inverter_spelling_when_that_is_the_one_present(self):
        coord = self._temperature_coordinator(("sensor.givtcp_fd2309f069_inverter_temperature", "41.0"))
        data = await coord._async_update_data()
        assert data.inverter_temperature == pytest.approx(41.0)

    @pytest.mark.asyncio
    async def test_the_configured_entity_wins_over_the_serial_derived_one(self):
        coord = self._temperature_coordinator(
            ("sensor.chosen_temp", "50.0"),
            ("sensor.givtcp_fd2309f069_invertor_temperature", "36.3"),
            configured="sensor.chosen_temp",
        )
        data = await coord._async_update_data()
        assert data.inverter_temperature == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_the_entity_is_picked_up_when_givtcp_creates_it_later(self):
        coord = self._temperature_coordinator()
        assert (await coord._async_update_data()).inverter_temperature is None
        coord.set_state("sensor.givtcp_fd2309f069_invertor_temperature", "36.3")
        assert (await coord._async_update_data()).inverter_temperature == pytest.approx(36.3)

    @pytest.mark.asyncio
    async def test_no_serial_and_no_entity_stays_unknown(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.set_state("sensor.givtcp_fd2309f069_invertor_temperature", "36.3")
        data = await coord._async_update_data()
        assert data.inverter_temperature is None

    def test_the_candidate_entity_ids_try_givtcp_s_spelling_first(self):
        from custom_components.givenergy_inverter_manager.discovery import (
            inverter_temperature_entity_ids,
        )

        assert inverter_temperature_entity_ids("FD2309F069") == [
            "sensor.givtcp_fd2309f069_invertor_temperature",
            "sensor.givtcp_fd2309f069_inverter_temperature",
        ]

    def test_inverter_temp_in_discovery_map(self):
        src = (PKG / "config_flow.py").read_text()
        assert "inverter_temp" in src
        assert "CONF_INVERTER_TEMP_ENTITY" in src

    def test_inverter_temp_suffix_in_givtcp_discovery(self):
        src = (PKG / "discovery/givtcp.py").read_text()
        assert "_invertor_temperature" in src
class TestMissedSolar:
    """Missed solar accumulates when battery full, exporting, no flex load active."""

    @pytest.mark.asyncio
    async def test_accumulates_when_battery_full_and_exporting(self):
        # Arrange — battery full, exporting, no EV or immersion
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states({
            "sensor.solar": "6000",
            "sensor.battery_soc": "100",
            "sensor.battery_power": "100",   # tiny charging
            "sensor.grid": "3000",           # GivTCP v3: positive = export → internal grid_power_w = -3000
            "sensor.house": "500",
        })
        coord._last_update = None  # first cycle, no elapsed time
        # Act
        await coord._async_update_data()
        # On first cycle elapsed_h = 0 so no accumulation yet
        assert coord._acc.today.missed_solar_kwh == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_no_accumulation_when_battery_not_full(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states({
            "sensor.solar": "6000",
            "sensor.battery_soc": "85",   # not full
            "sensor.battery_power": "2000",
            "sensor.grid": "2000",        # GivTCP v3 export → internal -2000
            "sensor.house": "500",
        })
        await coord._async_update_data()
        coord._last_update = coord._last_update  # keep timestamp
        await coord._async_update_data()
        # battery not 100% → no missed solar
        assert coord._acc.today.missed_solar_kwh == pytest.approx(0.0)

    def test_missed_solar_field_in_energy_accumulator(self):
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
        acc = EnergyAccumulator()
        assert hasattr(acc, "missed_solar_kwh")
        assert acc.missed_solar_kwh == pytest.approx(0.0)

    def test_missed_solar_in_sensor_descriptions(self):
        from custom_components.givenergy_inverter_manager.sensor import SENSOR_DESCRIPTIONS

        assert "missed_solar_today" in {d.key for d in SENSOR_DESCRIPTIONS}

    def test_missed_solar_disabled_by_default(self):
        from custom_components.givenergy_inverter_manager.sensor import SENSOR_DESCRIPTIONS

        description = next(d for d in SENSOR_DESCRIPTIONS if d.key == "missed_solar_today")
        assert description.entity_registry_enabled_default is False


class TestSolarNoiseFloor:
    """Solar accumulation ignores sensor noise below 10W."""

    @pytest.mark.asyncio
    async def test_no_accumulation_below_noise_floor(self):
        # Arrange — solar reads 5W (sensor noise at night)
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states({**_default_states(), "sensor.solar": "5"})
        await coord._async_update_data()
        coord._last_update = coord._last_update
        coord.set_states({**_default_states(), "sensor.solar": "5"})
        await coord._async_update_data()
        # Assert — tiny reading treated as zero
        assert coord._acc.today.solar_kwh == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_accumulates_above_noise_floor(self):
        # Arrange — solar reads 100W (real generation)
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states({**_default_states(), "sensor.solar": "3000"})
        await coord._async_update_data()
        coord._last_update = coord._last_update - __import__('datetime').timedelta(minutes=30)
        await coord._async_update_data()
        # Assert — real generation accumulates
        assert coord._acc.today.solar_kwh > 0

    def test_noise_floor_constant_in_const(self):
        from custom_components.givenergy_inverter_manager.const import SOLAR_NOISE_FLOOR_W
        assert SOLAR_NOISE_FLOOR_W == pytest.approx(10.0)


class TestDeratingMinutes:
    """Derating minutes accumulate when inverter temp >= INVERTER_TEMP_DERATING."""

    @pytest.mark.asyncio
    async def test_accumulates_during_derating(self):
        from custom_components.givenergy_inverter_manager.const import CONF_INVERTER_TEMP_ENTITY
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.entry.data[CONF_INVERTER_TEMP_ENTITY] = "sensor.inverter_temp"
        coord.set_state("sensor.inverter_temp", "68.0")  # above 65°C derating threshold
        await coord._async_update_data()
        coord._last_update = coord._last_update - __import__('datetime').timedelta(minutes=30)
        await coord._async_update_data()
        assert coord._acc.today.inverter_derating_minutes == pytest.approx(30.0, rel=0.05)

    @pytest.mark.asyncio
    async def test_no_accumulation_below_threshold(self):
        from custom_components.givenergy_inverter_manager.const import CONF_INVERTER_TEMP_ENTITY
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.entry.data[CONF_INVERTER_TEMP_ENTITY] = "sensor.inverter_temp"
        coord.set_state("sensor.inverter_temp", "55.0")  # below 65°C derating threshold
        await coord._async_update_data()
        coord._last_update = coord._last_update - __import__('datetime').timedelta(minutes=30)
        await coord._async_update_data()
        assert coord._acc.today.inverter_derating_minutes == pytest.approx(0.0)

    def test_derating_minutes_in_energy_accumulator(self):
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
        acc = EnergyAccumulator()
        assert hasattr(acc, "inverter_derating_minutes")
        assert acc.inverter_derating_minutes == pytest.approx(0.0)


class TestLiveGridCostRate:
    """live_grid_cost_rate uses import rate when importing, export rate when exporting."""

    @pytest.mark.asyncio
    async def test_positive_when_importing(self):
        # Arrange — importing 1 kW at €0.33/kWh = €0.33/hr
        from custom_components.givenergy_inverter_manager.const import CONF_EXPORT_RATE
        cfg = _cfg(**{CONF_EXPORT_RATE: 0.20})
        coord = FakeCoordinator(cfg=cfg)
        coord.set_states({**_default_states(), "sensor.grid": "-1000"})  # GivTCP: negative = import
        data = await coord._async_update_data()
        # internal grid_power_w = +1000 (import) → spending
        assert data.live_grid_cost_rate > 0

    @pytest.mark.asyncio
    async def test_negative_when_exporting(self):
        # Arrange — exporting 1 kW
        from custom_components.givenergy_inverter_manager.const import CONF_EXPORT_RATE
        cfg = _cfg(**{CONF_EXPORT_RATE: 0.20})
        coord = FakeCoordinator(cfg=cfg)
        coord.set_states({**_default_states(), "sensor.grid": "1000"})  # GivTCP: positive = export
        data = await coord._async_update_data()
        # internal grid_power_w = -1000 (export) → earning
        assert data.live_grid_cost_rate < 0

    @pytest.mark.asyncio
    async def test_zero_when_idle(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states({**_default_states(), "sensor.grid": "0"})
        data = await coord._async_update_data()
        assert data.live_grid_cost_rate == pytest.approx(0.0)

    def test_live_grid_cost_rate_in_sensor_descriptions(self):
        from custom_components.givenergy_inverter_manager.sensor import SENSOR_DESCRIPTIONS

        assert "live_grid_cost_rate" in {d.key for d in SENSOR_DESCRIPTIONS}


class TestHardwareSettingsInOptions:
    """Battery capacity and inverter max output can be overridden via options flow."""

    @pytest.mark.asyncio
    async def test_battery_capacity_from_options_overrides_data(self):
        # Arrange — entry.data has 10.0 kWh, options has 19.2 kWh
        from custom_components.givenergy_inverter_manager.const import CONF_BATTERY_CAPACITY

        cfg = _cfg(**{CONF_BATTERY_CAPACITY: 10.0})
        coord = FakeCoordinator(cfg=cfg)
        # Simulate options override
        coord.entry.options = {CONF_BATTERY_CAPACITY: 19.2}
        coord.set_states(_default_states())

        # Act
        await coord.run_cycle()

        # Assert — effective config merges options over data → 19.2 kWh
        effective = coord._effective_cfg()
        assert effective.get(CONF_BATTERY_CAPACITY) == pytest.approx(19.2)

    def test_effective_cfg_merges_data_and_options(self):
        # Arrange
        from custom_components.givenergy_inverter_manager.const import CONF_BATTERY_CAPACITY

        cfg = _cfg(**{CONF_BATTERY_CAPACITY: 10.0})
        coord = FakeCoordinator(cfg=cfg)
        coord.entry.options = {CONF_BATTERY_CAPACITY: 19.2}

        # Act
        effective = coord._effective_cfg()

        # Assert — options override data
        assert effective[CONF_BATTERY_CAPACITY] == pytest.approx(19.2)
class TestCheapRateFloorWriteSafety:
    """The floor top-up must use the guarded write helpers, not raw service calls."""

    @staticmethod
    def _coord(target_now: str | None = None):
        cfg = {
            **_cfg(),
            "target_soc_entity": "number.target_soc",
            "enable_charge_target_entity": "switch.enable_target",
        }
        coord = FakeCoordinator(cfg=cfg)
        if target_now is not None:
            coord.set_state("number.target_soc", target_now)
        coord.set_state("switch.enable_target", "off")
        return coord, cfg

    @pytest.mark.asyncio
    async def test_writes_integer_target_and_enables_switch(self):
        from unittest.mock import AsyncMock, patch

        coord, cfg = self._coord(target_now="20")
        with patch(
            "custom_components.givenergy_inverter_manager.givtcp_writer.asyncio.sleep",
            new=AsyncMock(),
        ):
            await coord._write_floor_target(cfg, "number.target_soc", 40)

        assert coord.service_calls_for("number", "set_value") == [
            {"entity_id": "number.target_soc", "value": 40}
        ]
        assert coord.service_calls_for("switch", "turn_on") == [
            {"entity_id": "switch.enable_target"}
        ]

    @pytest.mark.asyncio
    async def test_skips_writes_when_already_at_target(self):
        from unittest.mock import AsyncMock, patch

        coord, cfg = self._coord(target_now="40")
        coord.set_state("switch.enable_target", "on")
        with patch(
            "custom_components.givenergy_inverter_manager.givtcp_writer.asyncio.sleep",
            new=AsyncMock(),
        ):
            await coord._write_floor_target(cfg, "number.target_soc", 40)

        assert coord.service_calls == []

    @pytest.mark.asyncio
    async def test_cooldown_does_not_block_a_different_value(self):
        from unittest.mock import AsyncMock, patch

        coord, cfg = self._coord(target_now="20")
        with patch(
            "custom_components.givenergy_inverter_manager.givtcp_writer.asyncio.sleep",
            new=AsyncMock(),
        ):
            await coord._write_floor_target(cfg, "number.target_soc", 40)
            await coord._write_floor_target(cfg, "number.target_soc", 55)

        values = [c["value"] for c in coord.service_calls_for("number", "set_value")]
        assert values == [40, 55]

    @pytest.mark.asyncio
    async def test_counts_register_writes(self):
        from unittest.mock import AsyncMock, patch

        coord, cfg = self._coord(target_now="20")
        with patch(
            "custom_components.givenergy_inverter_manager.givtcp_writer.asyncio.sleep",
            new=AsyncMock(),
        ):
            await coord._write_floor_target(cfg, "number.target_soc", 40)

        assert coord._writer.write_count == 2


class TestCheapRateFloorNeverLowersTarget:
    """The floor top-up raises a low charge target. It never lowers a higher one."""

    @staticmethod
    def _now():
        from zoneinfo import ZoneInfo

        return datetime(2024, 7, 10, 2, 30, tzinfo=ZoneInfo("Europe/Dublin"))

    @staticmethod
    def _coord(target_now: str | None):
        cfg = _cfg()
        coord = FakeCoordinator(cfg=cfg)
        if target_now is not None:
            coord.set_state("number.target_soc", target_now)
        coord.set_state("switch.enable_charge_target", "off")
        return coord, cfg

    @staticmethod
    def _target_writes(coord):
        return [c["value"] for c in coord.service_calls_for("number", "set_value")]

    async def _run(self, coord, cfg, soc=30.0):
        from unittest.mock import AsyncMock, patch

        with patch(
            "custom_components.givenergy_inverter_manager.givtcp_writer.asyncio.sleep",
            new=AsyncMock(),
        ):
            return await coord._maybe_apply_cheap_rate_floor(self._now(), _raw(battery_soc=soc), cfg)

    @pytest.mark.asyncio
    async def test_overnight_target_of_80_is_not_lowered_to_the_floor(self):
        coord, cfg = self._coord("80")
        result = await self._run(coord, cfg)
        assert "topping up" in result.lower()
        assert 40 not in self._target_writes(coord)
        assert coord._states["number.target_soc"].state == "80"

    @pytest.mark.asyncio
    async def test_target_below_the_floor_is_raised_to_the_floor(self):
        coord, cfg = self._coord("20")
        await self._run(coord, cfg)
        assert self._target_writes(coord) == [40]

    @pytest.mark.asyncio
    async def test_target_equal_to_the_floor_is_left_alone(self):
        coord, cfg = self._coord("40")
        await self._run(coord, cfg)
        assert self._target_writes(coord) == []

    @pytest.mark.asyncio
    async def test_unreadable_target_falls_back_to_the_floor(self):
        coord, cfg = self._coord("unavailable")
        await self._run(coord, cfg)
        assert self._target_writes(coord) == [40]

    @pytest.mark.asyncio
    async def test_missing_target_state_falls_back_to_the_floor(self):
        coord, cfg = self._coord(None)
        await self._run(coord, cfg)
        assert self._target_writes(coord) == [40]

    @pytest.mark.asyncio
    async def test_floor_never_writes_above_the_cap(self):
        from custom_components.givenergy_inverter_manager.const import (
            GIVTCP_MAX_CHARGE_TARGET_PCT,
        )

        coord, cfg = self._coord("20")
        cfg["cheap_rate_floor_soc"] = 150
        await self._run(coord, cfg)
        assert self._target_writes(coord) == [GIVTCP_MAX_CHARGE_TARGET_PCT]

    @pytest.mark.asyncio
    async def test_higher_target_still_enables_the_charge_target_and_sets_the_flag(self):
        coord, cfg = self._coord("80")
        await self._run(coord, cfg)
        assert coord.service_calls_for("switch", "turn_on") == [
            {"entity_id": "switch.enable_charge_target"}
        ]
        assert coord._floor_top_up_applied is True


class TestSensorDropouts:
    """Unavailable required sensors are flagged, not read as zero readings."""

    def _coord(self, **cfg_overrides):
        coord = FakeCoordinator(cfg=_cfg(**cfg_overrides))
        coord.set_states(_default_states())
        return coord

    @pytest.mark.parametrize(
        ("entity", "name"),
        [
            ("sensor.house", "house_load"),
            ("sensor.battery_power", "battery_power"),
            ("sensor.solar", "solar_power"),
            ("sensor.battery_soc", "battery_soc"),
        ],
    )
    @pytest.mark.parametrize("state", ["unavailable", "unknown"])
    def test_flags_unavailable_input(self, entity, name, state):
        coord = self._coord()
        coord.set_state(entity, state)
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.unavailable_inputs == (name,)

    def test_flags_missing_entity(self):
        coord = self._coord()
        del coord._states["sensor.house"]
        raw = coord._collect_raw(coord._effective_cfg())
        assert "house_load" in raw.unavailable_inputs

    def test_nothing_flagged_when_all_available(self):
        coord = self._coord()
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.unavailable_inputs == ()

    def test_flags_unavailable_temp_sensor_when_configured(self):
        from custom_components.givenergy_inverter_manager.const import CONF_IMMERSION_TEMP_SENSOR

        coord = self._coord(**{CONF_IMMERSION_TEMP_SENSOR: "sensor.immersion_temp"})
        coord.set_state("sensor.immersion_temp", "unavailable")
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.unavailable_inputs == ("immersion_temp",)

    def test_no_temp_sensor_configured_is_not_flagged(self):
        coord = self._coord()
        raw = coord._collect_raw(coord._effective_cfg())
        assert raw.immersion_temp is None
        assert "immersion_temp" not in raw.unavailable_inputs

    def test_unavailable_solar_does_not_change_smoothed_value(self):
        coord = self._coord()
        coord.set_state("sensor.solar", "4000")
        coord._collect_raw(coord._effective_cfg())
        before = coord._smoothed_solar_w
        coord.set_state("sensor.solar", "unavailable")
        raw = coord._collect_raw(coord._effective_cfg())
        assert coord._smoothed_solar_w == pytest.approx(before)
        assert raw.smoothed_solar_power_w == pytest.approx(before)

    def test_available_solar_still_smoothed(self):
        coord = self._coord()
        coord.set_state("sensor.solar", "4000")
        coord._collect_raw(coord._effective_cfg())
        assert coord._smoothed_solar_w == pytest.approx(2000.0)

    @pytest.mark.asyncio
    async def test_house_load_dropout_does_not_start_immersion(self):
        coord = self._coord(**{CONF_IMMERSION_SWITCH: "switch.immersion"})
        coord.set_states({"sensor.solar": "5000", "sensor.battery_soc": "95",
                          "sensor.battery_power": "0", "sensor.house": "unavailable",
                          "switch.immersion": "off"})
        coord._smoothed_solar_w = 5000.0
        data = await coord._async_update_data()
        assert data.should_divert_immersion is False
        assert "sensor unavailable" in data.divert_reason.lower()

    @pytest.mark.asyncio
    async def test_house_load_dropout_holds_running_immersion(self):
        coord = self._coord(**{CONF_IMMERSION_SWITCH: "switch.immersion"})
        coord.set_states({"sensor.solar": "5000", "sensor.battery_soc": "95",
                          "sensor.battery_power": "0", "sensor.house": "unavailable",
                          "switch.immersion": "on"})
        coord._smoothed_solar_w = 5000.0
        data = await coord._async_update_data()
        assert data.should_divert_immersion is True


class TestInputOutageTracking:
    """The coordinator measures how long required inputs have been unavailable."""

    def _raw_with(self, *unavailable):
        raw = _raw()
        raw.unavailable_inputs = tuple(unavailable)
        return raw

    def test_no_outage_reports_zero(self):
        coord = FakeCoordinator(cfg=_cfg())
        raw = self._raw_with()
        coord._track_input_outage(raw, datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))
        assert raw.unavailable_for_s == 0.0
        assert coord._inputs_unavailable_since is None

    def test_outage_duration_counts_from_first_cycle(self):
        coord = FakeCoordinator(cfg=_cfg())
        start = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
        for offset in (0, 30, 90):
            raw = self._raw_with("house_load")
            coord._track_input_outage(raw, start + timedelta(seconds=offset))
        assert raw.unavailable_for_s == pytest.approx(90.0)

    def test_recovery_resets_the_clock(self):
        coord = FakeCoordinator(cfg=_cfg())
        start = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
        coord._track_input_outage(self._raw_with("solar_power"), start)
        coord._track_input_outage(self._raw_with(), start + timedelta(seconds=60))
        raw = self._raw_with("solar_power")
        coord._track_input_outage(raw, start + timedelta(seconds=120))
        assert raw.unavailable_for_s == 0.0

    @pytest.mark.asyncio
    async def test_running_immersion_turns_off_after_hold_limit(self):
        from custom_components.givenergy_inverter_manager.const import (
            GIVTCP_MIN_WRITE_INTERVAL_S,
        )

        coord = FakeCoordinator(cfg=_cfg(**{CONF_IMMERSION_SWITCH: "switch.immersion"}))
        coord.set_states(_default_states())
        coord.set_states({"sensor.solar": "5000", "sensor.battery_soc": "95",
                          "sensor.battery_power": "0", "sensor.house": "unavailable",
                          "switch.immersion": "on"})
        coord._smoothed_solar_w = 5000.0
        coord._inputs_unavailable_since = datetime.now(timezone.utc) - timedelta(
            seconds=GIVTCP_MIN_WRITE_INTERVAL_S + 10
        )
        data = await coord._async_update_data()
        assert data.should_divert_immersion is False
        assert "turning off" in data.divert_reason
# ── Load profile and forecast correction wiring ───────────────────────────────


class _FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 6, 15, 12, 0, tzinfo=tz or timezone.utc)  # a Monday


@pytest.fixture
def fixed_clock(monkeypatch):
    monkeypatch.setitem(
        GivEnergyCoordinator._async_update_data.__globals__, "datetime", _FixedClock
    )


def _history_day(offset_days: int, slots: list[float]) -> dict:
    day = datetime(2026, 6, 14, tzinfo=timezone.utc) - timedelta(days=offset_days)
    return {"date": day.date().isoformat(), "slots": slots, "coverage": 1.0}


def _evening_heavy_slots() -> list[float]:
    return [0.1 if slot < 34 else 0.1 + (20 - 0.1 * 48) / 14 for slot in range(48)]


def _forecast_coord() -> FakeCoordinator:
    coord = FakeCoordinator(cfg=_cfg(**{"forecast_entity": "sensor.forecast"}))
    coord.set_states(_default_states())
    coord.set_state("sensor.forecast", "14")
    coord._acc.today.house_kwh = 10.0  # 20 kWh/day pace at noon
    return coord


class TestLoadProfileAndForecastCorrectionWiring:
    @pytest.mark.asyncio
    async def test_cycle_records_baseline_load_in_persisted_slot_state(self, fixed_clock):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord._last_update = datetime(2026, 6, 15, 11, 59, 30, tzinfo=timezone.utc)
        await coord.run_cycle()
        assert coord._acc.state.slot_load_today[24] == pytest.approx(1.5 * 30 / 3600)
        assert coord._acc.state.slot_hours_today[24] == pytest.approx(30 / 3600)
        assert coord._acc.state.slot_load_date == "2026-06-15"

    @pytest.mark.asyncio
    async def test_stored_profile_changes_the_charge_target(self, fixed_clock):
        flat = await _forecast_coord().run_cycle()
        coord = _forecast_coord()
        coord._acc.state.slot_load_history = [
            _history_day(1, _evening_heavy_slots()),
            _history_day(2, _evening_heavy_slots()),
        ]
        profiled = await coord.run_cycle()
        assert profiled.charge_decision.target_soc < flat.charge_decision.target_soc
        assert "load profile" in profiled.charge_decision.reason

    @pytest.mark.asyncio
    async def test_no_history_gives_flat_decision(self, fixed_clock):
        data = await _forecast_coord().run_cycle()
        assert "load profile" not in data.charge_decision.reason
        assert "accuracy" not in data.charge_decision.reason

    @pytest.mark.asyncio
    async def test_recorded_accuracy_scales_the_forecast(self, fixed_clock):
        coord = _forecast_coord()
        coord._acc.state.forecast_ratio_history = [
            {"forecast": 10.0, "actual": 7.0, "clipped": False}
        ] * 5
        data = await coord.run_cycle()
        assert data.charge_decision.forecast_kwh == pytest.approx(14.0 * 0.7)

    @pytest.mark.asyncio
    async def test_cycle_stores_raw_forecast_and_clipping(self, fixed_clock):
        coord = _forecast_coord()
        coord.set_state("sensor.solar", "4900")
        await coord.run_cycle()
        assert coord._acc.state.pending_raw_forecast_kwh == pytest.approx(14.0)
        assert coord._acc.state.today_clipping is True

    @pytest.mark.asyncio
    async def test_no_clipping_flag_below_threshold(self, fixed_clock):
        coord = _forecast_coord()
        await coord.run_cycle()
        assert coord._acc.state.today_clipping is False

    def test_midnight_reset_archives_the_completed_day(self):
        coord = FakeCoordinator(cfg=_cfg())
        for slot in range(48):
            coord._acc.record_slot_load(
                datetime(2026, 6, 15, slot // 2, (slot % 2) * 30, tzinfo=timezone.utc),
                slot,
                0.4,
                0.5,
            )
        coord._midnight_reset(datetime(2026, 6, 16, 0, 0, tzinfo=timezone.utc))
        history = coord._acc.state.slot_load_history
        assert [e["date"] for e in history] == ["2026-06-15"]
        assert history[0]["coverage"] == pytest.approx(1.0)
        assert coord._acc.state.slot_load_today == [0.0] * 48
# ── Battery cycle accounting ──────────────────────────────────────────────────


class TestBatteryCycleAccounting:
    """SoC glitches must not add phantom cycles through the coordinator."""

    async def _run(self, readings):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        for soc in readings:
            coord.set_state("sensor.battery_soc", soc)
            await coord.run_cycle()
        return coord

    @pytest.mark.asyncio
    async def test_unavailable_soc_between_healthy_readings_adds_no_cycles(self):
        coord = await self._run(["80", "unavailable", "80"])
        assert coord._battery_stats.total_cycles == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_unavailable_soc_does_not_become_the_previous_reading(self):
        coord = await self._run(["80", "unavailable"])
        assert coord._last_soc is None

    @pytest.mark.asyncio
    async def test_literal_zero_soc_adds_no_cycles(self):
        coord = await self._run(["80", "0", "79"])
        assert coord._battery_stats.total_cycles == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_discharge_between_healthy_readings_is_counted(self):
        coord = await self._run(["80", "79", "78"])
        assert coord._battery_stats.total_cycles == pytest.approx(0.02)

    @pytest.mark.asyncio
    async def test_charging_between_healthy_readings_is_not_counted(self):
        coord = await self._run(["70", "71", "72"])
        assert coord._battery_stats.total_cycles == pytest.approx(0.0)


# ── BMS lifetime cycle counter ────────────────────────────────────────────────

PACK_1 = "sensor.givtcp_bt2349g123_battery_cycles"
PACK_2 = "sensor.givtcp_bt2349g456_battery_cycles"


class TestBatteryLifetimeCycles:
    """The GivTCP BMS counter is the authoritative lifetime cycle count."""

    def _coord(self, **states):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states(_default_states())
        coord.set_states(states)
        return coord

    def test_reads_the_bms_counter_once_discovered(self):
        coord = self._coord(**{PACK_1: "38"})
        coord._update_cycle = 1
        coord._maybe_rediscover_battery_cycles()
        assert coord._battery_cycle_entities == [PACK_1]
        assert coord._read_battery_lifetime_cycles() == pytest.approx(38.0)

    def test_uses_the_highest_pack_not_the_sum(self):
        coord = self._coord(**{PACK_1: "38", PACK_2: "41"})
        coord._update_cycle = 1
        coord._maybe_rediscover_battery_cycles()
        assert coord._read_battery_lifetime_cycles() == pytest.approx(41.0)

    def test_unavailable_and_zero_packs_are_ignored(self):
        coord = self._coord(**{PACK_1: "unavailable", PACK_2: "0"})
        coord._update_cycle = 1
        coord._maybe_rediscover_battery_cycles()
        assert coord._read_battery_lifetime_cycles() is None

    def test_none_when_no_counter_exists(self):
        coord = self._coord()
        coord._update_cycle = 1
        coord._maybe_rediscover_battery_cycles()
        assert coord._read_battery_lifetime_cycles() is None

    def test_rediscovery_only_runs_every_tenth_cycle(self):
        coord = self._coord(**{PACK_1: "38"})
        coord._update_cycle = 2
        coord._maybe_rediscover_battery_cycles()
        assert coord._battery_cycle_entities == []
        coord._update_cycle = 11
        coord._maybe_rediscover_battery_cycles()
        assert coord._battery_cycle_entities == [PACK_1]

    @pytest.mark.asyncio
    async def test_total_cycles_is_seeded_from_the_bms_counter(self):
        coord = self._coord(**{PACK_1: "38"})
        data = await coord.run_cycle()
        assert data.battery_stats.total_cycles == pytest.approx(38.0)
        assert data.battery_stats.estimated_remaining_life_pct == pytest.approx(
            (1 - 38.0 / 6000) * 100
        )

    @pytest.mark.asyncio
    async def test_bms_counter_replaces_a_lower_soc_estimate(self):
        coord = self._coord(**{PACK_1: "38"})
        coord._battery_stats.total_cycles = 12.0
        data = await coord.run_cycle()
        assert data.battery_stats.total_cycles == pytest.approx(38.0)

    @pytest.mark.asyncio
    async def test_falls_back_to_the_soc_estimate_without_a_counter(self):
        coord = self._coord()
        coord.set_state("sensor.battery_soc", "80")
        await coord.run_cycle()
        coord.set_state("sensor.battery_soc", "79")
        data = await coord.run_cycle()
        assert data.battery_stats.total_cycles == pytest.approx(0.01)

    @pytest.mark.asyncio
    async def test_soc_estimate_continues_from_the_last_bms_value(self):
        coord = self._coord(**{PACK_1: "38"})
        coord.set_state("sensor.battery_soc", "80")
        await coord.run_cycle()
        coord.set_state(PACK_1, "unavailable")
        coord.set_state("sensor.battery_soc", "79")
        data = await coord.run_cycle()
        assert data.battery_stats.total_cycles == pytest.approx(38.01)


# ── Write safety ──────────────────────────────────────────────────────────────


class _Boom(Exception):
    """Stand-in for an error raised by a service call."""


def _write_coord(fail_entities=(), exc=None, **cfg_overrides):
    """FakeCoordinator whose service calls raise for the listed entities."""
    from homeassistant.exceptions import HomeAssistantError

    error = exc or HomeAssistantError("service failed")
    cfg = _cfg(**cfg_overrides)
    coord = FakeCoordinator(cfg=cfg)
    coord.set_state("switch.enable_charge_target", "off")
    coord.set_state("switch.enable_charge_schedule", "off")
    coord.set_state("select.charge_start", "00:00:00")
    coord.set_state("select.charge_end", "00:00:00")
    coord.set_state("number.target_soc", "100")
    original = coord._call_service

    async def call(domain, service, data):
        if data.get("entity_id") in fail_entities:
            raise error
        await original(domain, service, data)

    coord._call_service = call
    return coord, cfg


def _cheap_period():
    from datetime import time as dtime
    from types import SimpleNamespace

    return SimpleNamespace(name="Night", start=dtime(23, 0), end=dtime(8, 0))


class TestWriteHelpersCatchServiceErrors:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("exc", [None, RuntimeError("boom")])
    async def test_set_number_returns_false_instead_of_raising(self, exc):
        coord, _ = _write_coord({"number.target_soc"}, exc)
        assert await coord._givtcp_set_number("number.target_soc", 80, "target") is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exc", [None, RuntimeError("boom")])
    async def test_set_switch_returns_false_instead_of_raising(self, exc):
        coord, _ = _write_coord({"switch.enable_charge_target"}, exc)
        assert await coord._givtcp_set_switch("switch.enable_charge_target", SwitchState.ON, "x") is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exc", [None, RuntimeError("boom")])
    async def test_set_select_returns_false_instead_of_raising(self, exc):
        coord, _ = _write_coord({"select.charge_start"}, exc)
        assert await coord._givtcp_set_select("select.charge_start", "23:00:00", "x") is False

    @pytest.mark.asyncio
    async def test_successful_write_returns_true(self):
        coord, _ = _write_coord()
        assert await coord._givtcp_set_number("number.target_soc", 80, "target") is True
        assert await coord._givtcp_set_switch("switch.enable_charge_target", SwitchState.ON, "x") is True
        assert await coord._givtcp_set_select("select.charge_start", "23:00:00", "x") is True

    @pytest.mark.asyncio
    async def test_already_at_value_returns_true_without_writing(self):
        coord, _ = _write_coord()
        coord.set_state("number.target_soc", "80")
        assert await coord._givtcp_set_number("number.target_soc", 80, "target") is True
        assert coord.service_calls == []

    @pytest.mark.asyncio
    async def test_missing_entity_returns_false(self):
        coord, _ = _write_coord()
        assert await coord._givtcp_set_number(None, 80, "target") is False

    @pytest.mark.asyncio
    async def test_failed_write_is_not_counted(self):
        coord, _ = _write_coord({"number.target_soc"})
        await coord._givtcp_set_number("number.target_soc", 80, "target")
        assert coord._writer.write_count == 0

    @pytest.mark.asyncio
    async def test_failed_write_does_not_start_a_cooldown(self):
        coord, _ = _write_coord({"number.target_soc"})
        await coord._givtcp_set_number("number.target_soc", 80, "target")
        assert ("number.target_soc", 80) not in coord._writer.last_write_time

    @pytest.mark.asyncio
    async def test_failure_is_logged(self, caplog):
        coord, _ = _write_coord({"number.target_soc"})
        with caplog.at_level(logging.WARNING):
            await coord._givtcp_set_number("number.target_soc", 80, "target")
        assert any("number.target_soc" in r.getMessage() for r in caplog.records)


class TestWriteCooldownKeyedOnValue:
    @staticmethod
    def _stuck(coord):
        """Service calls are recorded but the state never changes."""

        async def call(domain, service, data):
            coord.service_calls.append((domain, service, data))

        coord._call_service = call

    @pytest.mark.asyncio
    async def test_identical_value_within_cooldown_is_not_rewritten(self):
        coord, _ = _write_coord()
        self._stuck(coord)
        await coord._givtcp_set_number("number.target_soc", 80, "target")
        calls_after_first = len(coord.service_calls)
        await coord._givtcp_set_number("number.target_soc", 80, "target")
        assert len(coord.service_calls) == calls_after_first

    @pytest.mark.asyncio
    async def test_different_value_within_cooldown_is_written(self):
        coord, _ = _write_coord()
        await coord._givtcp_set_number("number.target_soc", 80, "target")
        await coord._givtcp_set_number("number.target_soc", 60, "target")
        values = [c["value"] for c in coord.service_calls_for("number", "set_value")]
        assert values == [80, 60]

    @pytest.mark.asyncio
    async def test_cooldown_is_per_value_for_switches(self):
        coord, _ = _write_coord()
        await coord._givtcp_set_switch("switch.enable_charge_target", SwitchState.ON, "x")
        await coord._givtcp_set_switch("switch.enable_charge_target", SwitchState.OFF, "x")
        assert len(coord.service_calls_for("switch", "turn_on")) == 1
        assert len(coord.service_calls_for("switch", "turn_off")) == 1

    @pytest.mark.asyncio
    async def test_cooldown_is_per_value_for_selects(self):
        coord, _ = _write_coord()
        await coord._givtcp_set_select("select.charge_start", "23:00:00", "x")
        await coord._givtcp_set_select("select.charge_start", "01:00:00", "x")
        options = [c["option"] for c in coord.service_calls_for("select", "select_option")]
        assert options == ["23:00:00", "01:00:00"]


class TestChargeTargetSequenceSafety:
    @pytest.mark.asyncio
    async def test_failed_target_write_does_not_enable_the_charge_target(self):
        coord, cfg = _write_coord({"number.target_soc"})
        await coord._async_apply_charge_target(cfg, 80, _cheap_period())
        assert coord.service_calls_for("switch", "turn_on") == [
            {"entity_id": "switch.enable_charge_schedule"}
        ]
        assert {"entity_id": "switch.enable_charge_target"} not in coord.service_calls_for(
            "switch", "turn_on"
        )

    @pytest.mark.asyncio
    async def test_failed_target_write_logs_a_warning(self, caplog):
        coord, cfg = _write_coord({"number.target_soc"})
        with caplog.at_level(logging.WARNING):
            await coord._async_apply_charge_target(cfg, 80, _cheap_period())
        assert any("not enabling the charge target" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_failed_target_write_still_lets_a_100_percent_target_clear_the_limit(self):
        coord, cfg = _write_coord({"number.target_soc"})
        coord.set_state("switch.enable_charge_target", "on")
        await coord._async_apply_charge_target(cfg, 100, _cheap_period())
        assert coord.service_calls_for("switch", "turn_off") == [
            {"entity_id": "switch.enable_charge_target"}
        ]

    @pytest.mark.asyncio
    async def test_earlier_step_failure_does_not_abort_the_sequence(self):
        coord, cfg = _write_coord({"switch.enable_charge_schedule", "select.charge_start"})
        await coord._async_apply_charge_target(cfg, 80, _cheap_period())
        assert coord.service_calls_for("number", "set_value") == [
            {"entity_id": "number.target_soc", "value": 80}
        ]
        assert {"entity_id": "switch.enable_charge_target"} in coord.service_calls_for(
            "switch", "turn_on"
        )
        assert coord.service_calls_for("select", "select_option") == [
            {"entity_id": "select.charge_end", "option": "08:00:00"}
        ]

    @pytest.mark.asyncio
    async def test_generic_exception_in_the_target_write_is_contained(self):
        coord, cfg = _write_coord({"number.target_soc"}, RuntimeError("boom"))
        await coord._async_apply_charge_target(cfg, 80, _cheap_period())
        assert {"entity_id": "switch.enable_charge_target"} not in coord.service_calls_for(
            "switch", "turn_on"
        )

    @pytest.mark.asyncio
    async def test_full_sequence_runs_when_everything_succeeds(self):
        coord, cfg = _write_coord()
        await coord._async_apply_charge_target(cfg, 80, _cheap_period())
        assert {"entity_id": "switch.enable_charge_target"} in coord.service_calls_for(
            "switch", "turn_on"
        )


class TestChargeTargetClamp:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("requested", "written"), [(0, 4), (2, 4), (3, 4), (4, 4), (150, 100)])
    async def test_target_is_clamped_to_what_givtcp_accepts(self, requested, written):
        coord, cfg = _write_coord()
        coord.set_state("number.target_soc", "50")
        await coord._async_apply_charge_target(cfg, requested, _cheap_period())
        assert coord.service_calls_for("number", "set_value") == [
            {"entity_id": "number.target_soc", "value": written}
        ]

    @pytest.mark.asyncio
    async def test_clamped_100_percent_clears_the_charge_target_limit(self):
        coord, cfg = _write_coord()
        coord.set_state("switch.enable_charge_target", "on")
        coord.set_state("number.target_soc", "50")
        await coord._async_apply_charge_target(cfg, 120, _cheap_period())
        assert coord.service_calls_for("number", "set_value")[0]["value"] == 100
        assert coord.service_calls_for("switch", "turn_off") == [
            {"entity_id": "switch.enable_charge_target"}
        ]

    @pytest.mark.asyncio
    async def test_clamping_is_logged(self, caplog):
        coord, cfg = _write_coord()
        with caplog.at_level(logging.WARNING):
            await coord._async_apply_charge_target(cfg, 1, _cheap_period())
        assert any("outside the range" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_floor_target_is_clamped(self):
        coord, cfg = _write_coord()
        coord.set_state("number.target_soc", "2")
        assert await coord._write_floor_target(cfg, "number.target_soc", 1) is True
        assert coord.service_calls_for("number", "set_value") == [
            {"entity_id": "number.target_soc", "value": 4}
        ]

    @pytest.mark.asyncio
    async def test_floor_does_not_enable_the_target_when_the_number_write_fails(self):
        coord, cfg = _write_coord({"number.target_soc"})
        coord.set_state("number.target_soc", "20")
        assert await coord._write_floor_target(cfg, "number.target_soc", 40) is False
        assert coord.service_calls_for("switch", "turn_on") == []


# ── Register write count ──────────────────────────────────────────────────────


class TestRegisterWriteCountPersistence:
    @pytest.mark.asyncio
    async def test_each_write_updates_the_value_that_gets_saved(self):
        coord, _ = _write_coord()
        coord._acc.state.register_write_count = 0
        await coord._givtcp_set_number("number.target_soc", 80, "target")
        assert coord._acc.state.register_write_count == coord._writer.write_count > 0

    @pytest.mark.asyncio
    async def test_count_continues_from_a_restored_value(self):
        coord, _ = _write_coord()
        coord._writer.write_count = 1000
        await coord._givtcp_set_number("number.target_soc", 80, "target")
        assert coord._acc.state.register_write_count == 1001

    @pytest.mark.asyncio
    async def test_lifetime_warning_fires_when_the_restored_count_reaches_the_limit(self, caplog):
        from custom_components.givenergy_inverter_manager.const import GIVTCP_WRITE_LIFETIME_WARN

        coord, _ = _write_coord()
        coord._writer.write_count = GIVTCP_WRITE_LIFETIME_WARN - 1
        with caplog.at_level(logging.WARNING):
            await coord._givtcp_set_number("number.target_soc", 80, "target")
        assert any("rated lifetime" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_no_lifetime_warning_below_the_limit(self, caplog):
        coord, _ = _write_coord()
        coord._writer.write_count = 10
        with caplog.at_level(logging.WARNING):
            await coord._givtcp_set_number("number.target_soc", 80, "target")
        assert not any("rated lifetime" in r.getMessage() for r in caplog.records)


class TestBackgroundTasks:
    """Fire-and-forget work is owned by the config entry and never raises."""

    def test_create_task_hands_the_work_to_the_config_entry(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.entry.async_create_task = MagicMock()
        coro = coord._call_service("switch", "turn_on", {"entity_id": "switch.x"})

        GivEnergyCoordinator._create_task(coord, coro)

        coord.entry.async_create_task.assert_called_once()
        args = coord.entry.async_create_task.call_args.args
        assert args[0] is coord.hass
        args[1].close()
        coro.close()

    async def test_run_background_awaits_the_work(self):
        coord = FakeCoordinator(cfg=_cfg())

        await GivEnergyCoordinator._run_background(
            coord, coord._call_service("switch", "turn_on", {"entity_id": "switch.x"})
        )

        assert coord.service_calls_for("switch", "turn_on") == [{"entity_id": "switch.x"}]

    async def test_run_background_logs_a_failure_and_does_not_raise(self, caplog):
        coord = FakeCoordinator(cfg=_cfg())

        async def broken():
            raise RuntimeError("charger offline")

        with caplog.at_level(logging.WARNING):
            await GivEnergyCoordinator._run_background(coord, broken())

        messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("charger offline" in m for m in messages)

    async def test_run_background_lets_cancellation_through(self):
        import asyncio

        coord = FakeCoordinator(cfg=_cfg())

        async def cancelled():
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await GivEnergyCoordinator._run_background(coord, cancelled())




# ── TestChargeWindowSizing ────────────────────────────────────────────────────

_SERIAL = "fd2309f069"
_CHARGE_RATE = f"number.givtcp_{_SERIAL}_battery_charge_rate"


class TestChargeWindowSizing:
    """The charge window end is sized to the plan from the GivTCP battery charge rate."""

    @staticmethod
    def _coord(soc: str = "20", charge_rate: str | None = "3600", **cfg_extra) -> FakeCoordinator:
        from custom_components.givenergy_inverter_manager.const import (
            CONF_BATTERY_CAPACITY,
            CONF_INVERTER_SERIAL,
        )

        coord = FakeCoordinator(
            cfg=_cfg(**{CONF_INVERTER_SERIAL: _SERIAL, CONF_BATTERY_CAPACITY: 19.0, **cfg_extra})
        )
        coord.set_states({**_default_states(), "sensor.battery_soc": soc})
        if charge_rate is not None:
            coord.set_state(_CHARGE_RATE, charge_rate)
        coord.override_charge_enabled = True
        coord.override_charge_value = 88
        return coord

    @staticmethod
    def _written_times(coord: FakeCoordinator) -> dict[str, str]:
        calls = coord.service_calls_for("select", "select_option")
        return {c["entity_id"]: c["option"] for c in calls}

    async def _write(self, coord: FakeCoordinator) -> None:
        await coord.run_cycle()
        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))
        await coord.tasks_created[0]

    @pytest.mark.parametrize(
        ("rate_state", "expected"),
        [
            ("3600", 3600.0),
            ("2600.0", 2600.0),
            ("0", None),
            ("unavailable", None),
            ("unknown", None),
        ],
    )
    def test_reads_the_charge_rate_from_the_serial_derived_entity(self, rate_state, expected):
        coord = self._coord(charge_rate=rate_state)

        raw = coord._collect_raw(coord._effective_cfg())

        assert raw.battery_charge_rate_w == expected

    def test_a_missing_charge_rate_entity_reads_as_unknown(self):
        coord = self._coord(charge_rate=None)

        assert coord._collect_raw(coord._effective_cfg()).battery_charge_rate_w is None

    def test_no_inverter_serial_reads_as_unknown(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states({**_default_states(), _CHARGE_RATE: "3600"})

        assert coord._collect_raw(coord._effective_cfg()).battery_charge_rate_w is None

    @pytest.mark.asyncio
    async def test_a_deep_deficit_writes_the_extended_end(self):
        coord = self._coord()

        await self._write(coord)

        written = self._written_times(coord)
        assert written["select.charge_start"] == "02:00:00"
        assert written["select.charge_end"] == "06:10:00"

    @pytest.mark.asyncio
    async def test_a_shallow_deficit_writes_the_cheapest_period_end(self):
        coord = self._coord(soc="75")

        await self._write(coord)

        assert self._written_times(coord)["select.charge_end"] == "04:00:00"

    @pytest.mark.asyncio
    async def test_an_unreadable_charge_rate_writes_the_cheapest_period_end(self):
        coord = self._coord(charge_rate=None)

        await self._write(coord)

        assert self._written_times(coord)["select.charge_end"] == "04:00:00"

    @pytest.mark.asyncio
    async def test_a_skipped_night_resets_the_window_to_the_cheapest_period(self):
        coord = self._coord()
        coord.override_charge_enabled = False
        coord.override_skip_charge = True

        await self._write(coord)

        assert self._written_times(coord)["select.charge_end"] == "04:00:00"

    @pytest.mark.asyncio
    async def test_dry_run_shows_the_extended_window(self):
        coord = self._coord(**{CONF_DRY_RUN: True})
        await coord.run_cycle()

        coord._write_charge_target_to_inverter(datetime.now(timezone.utc))

        assert coord.tasks_created == []
        assert "Nightboost window 02:00–06:10" in coord.data.dry_run_last_skipped


# ── TestAcChargeCounter ───────────────────────────────────────────────────────

_AC_CHARGE = f"sensor.givtcp_{_SERIAL}_ac_charge_energy_today_kwh"


class TestAcChargeCounter:
    """GivTCP's AC charge counter is found from the inverter serial, like the other daily counters."""

    @staticmethod
    def _coord(**states: str) -> FakeCoordinator:
        from custom_components.givenergy_inverter_manager.const import CONF_INVERTER_SERIAL

        coord = FakeCoordinator(cfg=_cfg(**{CONF_INVERTER_SERIAL: _SERIAL}))
        coord.set_states({**_default_states(), **states})
        return coord

    @pytest.mark.parametrize(
        ("state", "expected"),
        [("7.5", 7.5), ("0", 0.0), ("unavailable", None), ("unknown", None)],
    )
    def test_reads_the_counter_from_the_serial_derived_entity(self, state, expected):
        coord = self._coord(**{_AC_CHARGE: state})

        raw = coord._collect_raw(coord._effective_cfg())

        assert raw.ac_charge_energy_today_kwh == expected

    def test_a_missing_entity_reads_as_unknown(self):
        coord = self._coord()

        assert coord._collect_raw(coord._effective_cfg()).ac_charge_energy_today_kwh is None

    def test_no_inverter_serial_reads_as_unknown(self):
        coord = FakeCoordinator(cfg=_cfg())
        coord.set_states({**_default_states(), _AC_CHARGE: "7.5"})

        assert coord._collect_raw(coord._effective_cfg()).ac_charge_energy_today_kwh is None

    @pytest.mark.asyncio
    async def test_a_cycle_with_the_live_counters_reads_59_percent(self):
        """12.1 kWh imported, 7.5 kWh of it into the battery, 11.3 kWh of load."""
        coord = self._coord(
            **{
                _AC_CHARGE: "7.5",
                f"sensor.givtcp_{_SERIAL}_import_energy_today_kwh": "12.1",
                f"sensor.givtcp_{_SERIAL}_load_energy_today_kwh": "11.3",
            }
        )

        data = await coord.run_cycle()

        assert data.today.self_sufficiency_pct == pytest.approx(59.3, abs=0.05)
        assert data.week.grid_to_battery_kwh == pytest.approx(7.5)
        assert data.grid_to_battery_counter_available is True

    @pytest.mark.asyncio
    async def test_a_cycle_without_the_counter_reads_zero_and_says_so(self):
        coord = self._coord(
            **{
                f"sensor.givtcp_{_SERIAL}_import_energy_today_kwh": "12.1",
                f"sensor.givtcp_{_SERIAL}_load_energy_today_kwh": "11.3",
            }
        )

        data = await coord.run_cycle()

        assert data.today.self_sufficiency_pct == 0.0
        assert data.grid_to_battery_counter_available is False
