"""
test_verbose.py — Tests for logging.py (custom logger with verbose mode).

Verifies:
  - GivLogger exposes standard log levels (.debug, .info, .warning, .error)
  - .verbose() only emits when CONF_VERBOSE_LOGGING is True in the config
  - log_cycle, log_givtcp_write, log_startup produce correct output when verbose on
  - All verbose functions are true no-ops when verbose is off
"""

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock

_ROOT = "custom_components.givenergy_inverter_manager"


# ── helpers ───────────────────────────────────────────────────────────────────


def _enable_verbose():
    from custom_components.givenergy_inverter_manager.logging import GivLogger

    GivLogger.register(lambda: {"verbose_logging": True})


def _disable_verbose():
    from custom_components.givenergy_inverter_manager.logging import GivLogger

    GivLogger.register(lambda: {"verbose_logging": False})


def _make_log():
    from custom_components.givenergy_inverter_manager.logging import get_logger

    return get_logger(f"{_ROOT}.test_verbose_helper")


def _make_data(**overrides):
    from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
    from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
    from custom_components.givenergy_inverter_manager.discovery.ev_charger import EVChargerState

    cd = MagicMock()
    cd.target_soc = 80
    cd.skip_charge = False
    cd.reason = "Test reason"
    cd.cost_to_charge = 1.23

    acc = EnergyAccumulator(
        solar_kwh=5.0,
        import_kwh=2.0,
        export_kwh=1.0,
        zappi_kwh=3.0,
        immersion_kwh=0.5,
        house_kwh=8.0,
        import_cost_by_period={"Day": 0.80},
        export_earnings=0.195,
        zappi_cost=0.30,
        immersion_cost=0.05,
        house_cost=0.45,
        battery_discharge_kwh=1.5,
    )

    data = MagicMock()
    data.solar_power_w = 3000.0
    data.battery_soc = 75.0
    data.battery_power_w = -500.0
    data.grid_power_w = 200.0
    data.house_load_w = 1200.0
    data.immersion_load_w = 0.0
    data.rest_of_house_w = 1000.0
    data.current_rate_name = "Night"
    data.current_rate = 0.1644
    data.currency_symbol = "€"
    data.is_clipping = False
    data.charge_decision = cd
    data.should_divert_immersion = False
    data.divert_reason = "Battery not full"
    data.ev_available = False
    data.ev_charger_name = ""
    data.ev_charger_state = EVChargerState.UNKNOWN
    data.ev_power_w = 0.0
    data.ev_draining_battery = False
    data.ev_protection_reason = ""
    data.today = acc
    data.battery_stats = BatteryStats()
    data.accrued_bill = 12.50
    data.projected_bill = 45.00
    data.days_remaining = 12
    data.will_survive_night = True
    data.estimated_soc_at_sunrise = 35.0
    data.survival_reason = "Fine"
    data.dry_run = False
    data.dry_run_last_skipped = ""
    for k, v in overrides.items():
        setattr(data, k, v)
    return data


def _make_raw(**overrides):
    from custom_components.givenergy_inverter_manager.core.engine import RawSensorValues

    raw = RawSensorValues(
        solar_power_w=3000.0,
        battery_soc=75.0,
        battery_power_w=-500.0,
        grid_power_w=200.0,
        house_load_w=1200.0,
        immersion_on=False,
        immersion_wattage_w=3000.0,
        immersion_temp=None,
        forecast_kwh_tomorrow=None,
        ev_power_w=0.0,
        ev_plugged_in=False,
    )
    for k, v in overrides.items():
        setattr(raw, k, v)
    return raw


# ── TestGivLogger ─────────────────────────────────────────────────────────────


class TestGivLogger:
    def test_get_logger_returns_givlogger(self):
        from custom_components.givenergy_inverter_manager.logging import GivLogger, get_logger

        log = get_logger(__name__)
        assert isinstance(log, GivLogger)

    def test_name_matches_module(self):
        from custom_components.givenergy_inverter_manager.logging import get_logger

        log = get_logger(f"{_ROOT}.mymodule")
        assert "mymodule" in log.name

    def test_debug_delegates_to_stdlib(self, caplog):
        log = _make_log()
        with caplog.at_level(logging.DEBUG, logger=log.name):
            log.debug("test debug %s", "message")
        assert any("test debug message" in r.message for r in caplog.records)

    def test_info_delegates_to_stdlib(self, caplog):
        log = _make_log()
        with caplog.at_level(logging.INFO, logger=log.name):
            log.info("test info")
        assert any("test info" in r.message for r in caplog.records)

    def test_warning_delegates_to_stdlib(self, caplog):
        log = _make_log()
        with caplog.at_level(logging.WARNING, logger=log.name):
            log.warning("test warn")
        assert any("test warn" in r.message for r in caplog.records)


# ── TestVerboseGuard ──────────────────────────────────────────────────────────


class TestVerboseGuard:
    def test_verbose_emits_when_enabled(self, caplog):
        _enable_verbose()
        log = _make_log()
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log.verbose("verbose output %s", "here")
        assert any("verbose output here" in r.message for r in caplog.records)

    def test_verbose_silent_when_disabled(self, caplog):
        _disable_verbose()
        log = _make_log()
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log.verbose("should not appear")
        assert not any("should not appear" in r.message for r in caplog.records)

    def test_verbose_silent_with_no_config(self, caplog):
        from custom_components.givenergy_inverter_manager.logging import GivLogger

        GivLogger._cfg_fn = None
        log = _make_log()
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log.verbose("should not appear")
        assert not any("should not appear" in r.message for r in caplog.records)

    def test_verbose_block_emits_all_lines_when_enabled(self, caplog):
        _enable_verbose()
        log = _make_log()
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log.verbose_block(["line one", "line two", "line three"])
        messages = [r.message for r in caplog.records]
        assert "line one" in messages
        assert "line two" in messages
        assert "line three" in messages

    def test_verbose_block_silent_when_disabled(self, caplog):
        _disable_verbose()
        log = _make_log()
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log.verbose_block(["should not", "appear at all"])
        assert not any("should not" in r.message for r in caplog.records)

    def test_verbose_reads_live_config(self, caplog):
        """Toggling the config flag mid-test affects the next call immediately."""
        from custom_components.givenergy_inverter_manager.logging import GivLogger

        flag = {"verbose_logging": False}
        GivLogger.register(lambda: flag)
        log = _make_log()

        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log.verbose("before toggle")

        flag["verbose_logging"] = True

        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log.verbose("after toggle")

        messages = [r.message for r in caplog.records]
        assert "before toggle" not in messages
        assert "after toggle" in messages


# ── TestLogCycle ──────────────────────────────────────────────────────────────


class TestLogCycle:
    def _run(self, raw=None, data=None, cycle=1, caplog=None):
        from custom_components.givenergy_inverter_manager.logging import log_cycle

        _enable_verbose()
        log = _make_log()
        raw = raw or _make_raw()
        data = data or _make_data()
        now = datetime(2024, 6, 15, 14, 0)
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log_cycle(log, cycle, raw, data, now)
        return "\n".join(r.message for r in caplog.records)

    def test_no_output_when_verbose_off(self, caplog):
        from custom_components.givenergy_inverter_manager.logging import log_cycle

        _disable_verbose()
        log = _make_log()
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log_cycle(log, 1, _make_raw(), _make_data(), datetime.now(timezone.utc))
        assert not caplog.records

    def test_cycle_number_in_output(self, caplog):
        assert "42" in self._run(cycle=42, caplog=caplog)

    def test_solar_power_in_output(self, caplog):
        assert "4567" in self._run(raw=_make_raw(solar_power_w=4567.0), caplog=caplog)

    def test_battery_soc_in_output(self, caplog):
        assert "82.5" in self._run(raw=_make_raw(battery_soc=82.5), caplog=caplog)

    def test_rate_period_in_output(self, caplog):
        data = _make_data()
        data.current_rate_name = "Nightboost"
        data.current_rate = 0.0965
        output = self._run(data=data, caplog=caplog)
        assert "Nightboost" in output
        assert "0.0965" in output

    def test_charge_target_and_reason_in_output(self, caplog):
        output = self._run(caplog=caplog)
        assert "80" in output
        assert "Test reason" in output

    def test_bill_in_output(self, caplog):
        output = self._run(caplog=caplog)
        assert "12.50" in output
        assert "45.00" in output

    def test_ev_section_when_available(self, caplog):
        from custom_components.givenergy_inverter_manager.discovery.ev_charger import EVChargerState

        data = _make_data()
        data.ev_available = True
        data.ev_charger_name = "Zappi"
        data.ev_charger_state = EVChargerState.CHARGING
        data.ev_power_w = 1400.0
        output = self._run(data=data, caplog=caplog)
        assert "Zappi" in output
        assert "1400" in output

    def test_ev_not_discovered_when_unavailable(self, caplog):
        assert "not discovered" in self._run(caplog=caplog)

    def test_forecast_line_when_present(self, caplog):
        assert "12.5" in self._run(raw=_make_raw(forecast_kwh_tomorrow=12.5), caplog=caplog)

    def test_dry_run_shown_when_active(self, caplog):
        data = _make_data()
        data.dry_run = True
        data.dry_run_last_skipped = "Would set Zappi -> Stopped"
        output = self._run(data=data, caplog=caplog)
        assert "DRY RUN" in output
        assert "Zappi" in output

    def test_dry_run_absent_when_inactive(self, caplog):
        assert "DRY RUN" not in self._run(caplog=caplog)

    def test_immersion_section_when_on(self, caplog):
        assert "IMMERSION RAW" in self._run(raw=_make_raw(immersion_on=True), caplog=caplog)


# ── TestLogGivtcpWrite ────────────────────────────────────────────────────────


class TestLogGivtcpWrite:
    def test_accepted_write_logged(self, caplog):
        from custom_components.givenergy_inverter_manager.logging import log_givtcp_write

        _enable_verbose()
        log = _make_log()
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log_givtcp_write(log, 4, "number.givtcp_SA123_target_soc", 85, "85", True)
        output = "\n".join(r.message for r in caplog.records)
        assert "step=4" in output
        assert "target_soc" in output
        assert "accepted" in output

    def test_mismatch_logged(self, caplog):
        from custom_components.givenergy_inverter_manager.logging import log_givtcp_write

        _enable_verbose()
        log = _make_log()
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log_givtcp_write(log, 4, "number.givtcp_SA123_target_soc", 85, "100", False)
        assert "MISMATCH" in "\n".join(r.message for r in caplog.records)

    def test_silent_when_verbose_off(self, caplog):
        from custom_components.givenergy_inverter_manager.logging import log_givtcp_write

        _disable_verbose()
        log = _make_log()
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log_givtcp_write(log, 4, "number.target_soc", 85, "85", True)
        assert not caplog.records


# ── TestLogStartup ────────────────────────────────────────────────────────────


class TestLogStartup:
    def test_entity_ids_logged(self, caplog):
        from custom_components.givenergy_inverter_manager.logging import log_startup

        _enable_verbose()
        log = _make_log()
        cfg = {"solar_power_entity": "sensor.givtcp_SA123_pv_power"}
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log_startup(log, cfg)
        assert any("SA123" in r.message for r in caplog.records)

    def test_missing_entity_noted(self, caplog):
        from custom_components.givenergy_inverter_manager.logging import log_startup

        _enable_verbose()
        log = _make_log()
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log_startup(log, {})
        assert any("not configured" in r.message for r in caplog.records)

    def test_base_rate_logged(self, caplog):
        from custom_components.givenergy_inverter_manager.logging import log_startup

        _enable_verbose()
        log = _make_log()
        cfg = {"base_rate": 0.3334, "base_rate_name": "Day", "rate_periods": []}
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log_startup(log, cfg)
        output = "\n".join(r.message for r in caplog.records)
        assert "0.3334" in output
        assert "Day" in output

    def test_timed_periods_logged(self, caplog):
        from custom_components.givenergy_inverter_manager.logging import log_startup

        _enable_verbose()
        log = _make_log()
        cfg = {
            "rate_periods": [
                {"name": "Night", "rate": 0.1644, "start": "23:00", "end": "08:00"},
            ]
        }
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log_startup(log, cfg)
        output = "\n".join(r.message for r in caplog.records)
        assert "Night" in output
        assert "23:00" in output

    def test_silent_when_verbose_off(self, caplog):
        from custom_components.givenergy_inverter_manager.logging import log_startup

        _disable_verbose()
        log = _make_log()
        with caplog.at_level(logging.DEBUG, logger=_ROOT):
            log_startup(log, {"base_rate": 0.30})
        assert not caplog.records


class TestManifest:
    """manifest.json must satisfy HA 2026.7+ requirements to load correctly."""

    def _manifest(self):
        import json
        from pathlib import Path

        return json.loads(
            Path("custom_components/givenergy_inverter_manager/manifest.json").read_text()
        )

    def test_import_executor_is_true(self):
        """import_executor: true is required on HA 2026.7+.

        Without it, HA raises:
          Detected blocking call to import_module inside the event loop
        and the integration fails to load. The field must be a boolean
        true — not the string "true" or absent entirely.
        """
        manifest = self._manifest()
        assert manifest.get("import_executor") is True, (
            'manifest.json must have "import_executor": true — '
            "HA 2026.7+ enforces that platform module imports happen "
            "in a thread executor, not the event loop."
        )

    def test_version_is_string(self):
        """version must be a semver string."""
        manifest = self._manifest()
        version = manifest.get("version", "")
        parts = version.split(".")
        assert len(parts) == 3 and all(p.isdigit() for p in parts), (
            f"manifest version must be 'MAJOR.MINOR.PATCH', got: {version!r}"
        )

    def test_required_fields_present(self):
        """All mandatory manifest fields must be present."""
        manifest = self._manifest()
        required = {
            "domain",
            "name",
            "codeowners",
            "config_flow",
            "documentation",
            "iot_class",
            "version",
            "import_executor",
        }
        missing = required - set(manifest.keys())
        assert not missing, f"manifest.json missing required fields: {missing}"
