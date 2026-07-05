"""
test_config_flow.py — Unit tests for config flow rate period parsing and GivTCP discovery.

Tests the pure Python logic in config_flow.py (_parse_rate_periods,
_rate_periods_to_text) and discovery/givtcp.py (entity derivation logic)
without requiring a running Home Assistant instance.
"""

import pytest

from custom_components.givenergy_inverter_manager.config_flow import (
    _parse_rate_periods,
    _rate_periods_to_text,
)
from custom_components.givenergy_inverter_manager.discovery import (
    GivTCPInverter,
    discover_givtcp_inverters,
    get_suggested_entities,
)
from custom_components.givenergy_inverter_manager.discovery.givtcp import SERIAL_SENSOR_SUFFIX

# ── Rate period parsing ───────────────────────────────────────────────────────

class TestParseRatePeriods:

    def test_single_period(self):
        result = _parse_rate_periods("Day, 0.3334, 08:00, 23:00")
        assert len(result) == 1
        assert result[0]["name"] == "Day"
        assert result[0]["rate"] == pytest.approx(0.3334)
        assert result[0]["start"] == "08:00"
        assert result[0]["end"] == "23:00"

    def test_three_periods_electric_ireland(self):
        text = (
            "Day, 0.3334, 08:00, 23:00\n"
            "Night, 0.1644, 23:00, 08:00\n"
            "Nightboost, 0.0965, 02:00, 04:00"
        )
        result = _parse_rate_periods(text)
        assert len(result) == 3
        names = [p["name"] for p in result]
        assert "Day" in names
        assert "Night" in names
        assert "Nightboost" in names

    def test_blank_lines_ignored(self):
        text = "\nDay, 0.3334, 08:00, 23:00\n\nNight, 0.1644, 23:00, 08:00\n"
        result = _parse_rate_periods(text)
        assert len(result) == 2

    def test_comment_lines_ignored(self):
        text = "# Electric Ireland rates\nDay, 0.3334, 08:00, 23:00"
        result = _parse_rate_periods(text)
        assert len(result) == 1

    def test_whitespace_around_values(self):
        result = _parse_rate_periods("  Day  ,  0.3334  ,  08:00  ,  23:00  ")
        assert result[0]["name"] == "Day"
        assert result[0]["rate"] == pytest.approx(0.3334)

    def test_error_wrong_field_count(self):
        with pytest.raises(ValueError, match="Line 1"):
            _parse_rate_periods("Day, 0.3334, 08:00")

    def test_error_invalid_rate(self):
        with pytest.raises(ValueError, match="invalid rate"):
            _parse_rate_periods("Day, notanumber, 08:00, 23:00")

    def test_error_invalid_start_time(self):
        with pytest.raises(ValueError, match="invalid start"):
            _parse_rate_periods("Day, 0.3334, 25:00, 23:00")

    def test_error_invalid_end_time(self):
        with pytest.raises(ValueError, match="invalid end"):
            _parse_rate_periods("Day, 0.3334, 08:00, 99:99")

    def test_error_malformed_time_no_colon(self):
        with pytest.raises(ValueError, match="invalid start"):
            _parse_rate_periods("Day, 0.3334, 0800, 23:00")

    def test_empty_input_is_valid(self):
        """Empty override list is valid — base-rate-only tariff needs no timed periods."""
        result = _parse_rate_periods("")
        assert result == []

    def test_only_comments_is_valid(self):
        result = _parse_rate_periods("# just a comment\n# another comment")
        assert result == []

    def test_many_periods(self):
        """Supports any number of rate periods, not just 3."""
        lines = "\n".join(
            f"Rate{i}, 0.{i:04d}, 0{i}:00, 0{i+1}:00"
            for i in range(5)
        )
        result = _parse_rate_periods(lines)
        assert len(result) == 5

    def test_overnight_period_preserved(self):
        """Overnight periods (end < start) are stored as-is."""
        result = _parse_rate_periods("Night, 0.1644, 23:00, 08:00")
        assert result[0]["start"] == "23:00"
        assert result[0]["end"] == "08:00"


class TestRatePeriodsToText:

    def test_roundtrip(self):
        """parse → text → parse should give the same result."""
        original = [
            {"name": "Day", "rate": 0.3334, "start": "08:00", "end": "23:00"},
            {"name": "Night", "rate": 0.1644, "start": "23:00", "end": "08:00"},
            {"name": "Nightboost", "rate": 0.0965, "start": "02:00", "end": "04:00"},
        ]
        text = _rate_periods_to_text(original)
        result = _parse_rate_periods(text)
        assert len(result) == len(original)
        for orig, parsed in zip(original, result, strict=True):
            assert parsed["name"] == orig["name"]
            assert parsed["rate"] == pytest.approx(orig["rate"])
            assert parsed["start"] == orig["start"]
            assert parsed["end"] == orig["end"]

    def test_produces_one_line_per_period(self):
        periods = [
            {"name": "A", "rate": 0.1, "start": "00:00", "end": "12:00"},
            {"name": "B", "rate": 0.2, "start": "12:00", "end": "00:00"},
        ]
        text = _rate_periods_to_text(periods)
        lines = [ln for ln in text.strip().splitlines() if ln.strip()]
        assert len(lines) == 2

    def test_empty_list_produces_empty_string(self):
        assert _rate_periods_to_text([]) == ""


# ── GivTCP discovery ──────────────────────────────────────────────────────────

class TestGivTCPInverter:

    def _make_inverter(self, serial="SA2221G123", entities=None):
        inv = GivTCPInverter(
            serial=serial,
            prefix=f"givtcp_{serial}",
            display_name=f"GivTCP {serial}",
        )
        if entities:
            inv.entities = entities
        return inv

    def test_fully_configured_all_present(self):
        inv = self._make_inverter(entities={
            "solar_power": "sensor.givtcp_SA2221G123_pv_power",
            "battery_soc": "sensor.givtcp_SA2221G123_battery_soc",
            "battery_power": "sensor.givtcp_SA2221G123_battery_power",
            "grid_power": "sensor.givtcp_SA2221G123_grid_power",
            "house_load": "sensor.givtcp_SA2221G123_load_power",
        })
        assert inv.is_fully_configured is True

    def test_not_fully_configured_missing_one(self):
        inv = self._make_inverter(entities={
            "solar_power": "sensor.givtcp_SA2221G123_pv_power",
            "battery_soc": "sensor.givtcp_SA2221G123_battery_soc",
            "battery_power": "sensor.givtcp_SA2221G123_battery_power",
            "grid_power": "sensor.givtcp_SA2221G123_grid_power",
            # house_load missing
        })
        assert inv.is_fully_configured is False

    def test_get_suggested_includes_all_entities(self):
        inv = self._make_inverter(entities={
            "solar_power": "sensor.givtcp_X_pv_power",
            "battery_soc": "sensor.givtcp_X_battery_soc",
            "battery_power": "sensor.givtcp_X_battery_power",
            "grid_power": "sensor.givtcp_X_grid_power",
            "house_load": "sensor.givtcp_X_load_power",
            "target_soc": "number.givtcp_X_target_soc",
            "enable_charge_target": "switch.givtcp_X_enable_charge_target",
        })
        suggested = get_suggested_entities(inv)
        # Control entities are now included so they pre-fill the config form
        assert "target_soc" in suggested
        assert "enable_charge_target" in suggested
        assert "solar_power" in suggested

    def test_display_name_includes_serial(self):
        inv = self._make_inverter(serial="SA2221G999")
        assert "SA2221G999" in inv.display_name


class TestDiscoverGivTCPInverters:

    class _FakeState:
        def __init__(self, entity_id: str, state: str):
            self.entity_id = entity_id
            self.state = state

    def _all_states(self, entity_ids: list[str]) -> dict:
        """Build a {entity_id: state} dict for discover_givtcp_inverters."""
        result = {}
        for eid in entity_ids:
            if eid.endswith(SERIAL_SENSOR_SUFFIX):
                serial = eid.split(".", 1)[1].replace(SERIAL_SENSOR_SUFFIX, "").replace("givtcp_", "")
                state = serial.upper()
            else:
                state = "100"
            result[eid] = self._FakeState(eid, state)
        return result

    def test_discovers_single_inverter(self):
        serial = "SA2221G123"
        prefix = f"givtcp_{serial.lower()}"
        all_states = self._all_states([
            f"sensor.{prefix}_invertor_serial_number",
            f"sensor.{prefix}_pv_power",
            f"sensor.{prefix}_battery_soc",
            f"sensor.{prefix}_battery_power",
            f"sensor.{prefix}_grid_power",
            f"sensor.{prefix}_load_power",
            f"number.{prefix}_target_soc",
        ])
        result = discover_givtcp_inverters(all_states)
        assert len(result) == 1
        assert result[0].is_fully_configured

    def test_discovers_no_inverters_when_none(self):
        all_states = self._all_states(["sensor.some_other_sensor"])
        result = discover_givtcp_inverters(all_states)
        assert result == []

    def test_notes_missing_entities(self):
        prefix = "givtcp_sa2221g123"
        all_states = self._all_states([
            f"sensor.{prefix}_invertor_serial_number",
            f"sensor.{prefix}_pv_power",
            # battery_soc, battery_power, grid_power, load_power missing
        ])
        result = discover_givtcp_inverters(all_states)
        assert len(result) == 1
        assert not result[0].is_fully_configured
        assert len(result[0].missing_entities) > 0

    def test_discovers_multiple_inverters(self):
        all_states = self._all_states([
            "sensor.givtcp_inv1_invertor_serial_number",
            "sensor.givtcp_inv2_invertor_serial_number",
        ])
        result = discover_givtcp_inverters(all_states)
        assert len(result) == 2

    def test_sorted_by_serial(self):
        all_states = self._all_states([
            "sensor.givtcp_zzz_invertor_serial_number",
            "sensor.givtcp_aaa_invertor_serial_number",
        ])
        result = discover_givtcp_inverters(all_states)
        assert result[0].serial < result[1].serial
