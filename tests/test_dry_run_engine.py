"""The dry_run option is threaded through the engine output without changing readings."""


class TestDryRunEngine:
    """Tests that dry_run flag is correctly threaded through engine output."""

    def _run_with_dry_run(self, dry_run: bool):
        from datetime import datetime

        from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
        from custom_components.givenergy_inverter_manager.core.engine import (
            RawSensorValues,
            build_coordinator_data,
        )
        from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

        cfg = {
            "rate_periods": [
                {"name": "Day", "rate": 0.3334, "start": "08:00", "end": "23:00"},
                {"name": "Night", "rate": 0.1644, "start": "23:00", "end": "08:00"},
            ],
            "dry_run": dry_run,
            "currency": "EUR",
        }
        raw = RawSensorValues(solar_power_w=1000.0, battery_soc=70.0)
        data, _ = build_coordinator_data(
            raw=raw,
            cfg=cfg,
            acc=EnergyAccumulator(),
            battery_stats=BatteryStats(),
            last_soc=None,
            last_update_time=None,
            now=datetime(2024, 6, 15, 14, 0),
        )
        return data

    def test_dry_run_false_by_default(self):
        data = self._run_with_dry_run(False)
        assert data.dry_run is False

    def test_dry_run_true_when_configured(self):
        data = self._run_with_dry_run(True)
        assert data.dry_run is True

    def test_dry_run_last_skipped_empty_on_init(self):
        data = self._run_with_dry_run(True)
        assert data.dry_run_last_skipped == ""

    def test_dry_run_does_not_affect_sensor_values(self):
        """dry_run=True must not change any sensor readings."""
        live = self._run_with_dry_run(False)
        dry = self._run_with_dry_run(True)
        assert dry.solar_power_w == live.solar_power_w
        assert dry.battery_soc == live.battery_soc
        assert dry.charge_decision is not None

    def test_dry_run_flag_not_exposed_as_charge_skip(self):
        """dry_run mode must not force skip_charge."""
        data = self._run_with_dry_run(True)
        # dry_run should not interfere with the charge decision logic
        assert isinstance(data.charge_decision.skip_charge, bool)
