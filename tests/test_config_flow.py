"""
test_config_flow.py - Sensor-default and translation tests that sit next to the flows.

The wizards themselves are tested in tests/core/test_wizard_*.py (page logic, no Home
Assistant), tests/test_config_flow_schemas.py (the page schemas under the real selectors) and
tests/ha_e2e/ (the real flow managers). The selector-level contract tests (step >= 1e-3) are in
test_config_flow_schemas.py.
"""

from tests.helpers import PKG

# ── Sensor default-enabled tests ──────────────────────────────────────────────


def _parse_sensor_enabled_state():
    """Return {name: enabled_default} from the sensor description table."""
    import json

    from custom_components.givenergy_inverter_manager.sensor import SENSOR_DESCRIPTIONS

    translated = json.loads((PKG / "strings.json").read_text())["entity"]["sensor"]
    return {
        translated[d.translation_key]["name"]: d.entity_registry_enabled_default
        for d in SENSOR_DESCRIPTIONS
        if d.translation_key in translated and "name" in translated[d.translation_key]
    }


class TestSensorDefaultEnabled:
    """Document exactly which sensors are disabled by default."""

    EXPECTED_DISABLED = {
        "Today's energy summary",
        "This week's energy summary",
        "Forecast accuracy yesterday",
        "Forecast accuracy 7-day average",
        "Export — trailing 12 months",
        "Battery Cycle Cost per kWh",
        "Self-consumed Solar Today",
        "Net Financial Position Today",
        "Battery Life Consumed Today",
        "Grid Carbon Intensity",
        "Grid Carbon Intensity Status",
        "Solar — trailing 12 months",
        "Import — trailing 12 months",
        "Import Cost — trailing 12 months",
        "Export Earnings — trailing 12 months",
        "Battery Throughput Budget Used",
        "Battery Throughput Budget Status",
        "Battery Years Remaining (est.)",
        "Average Import Rate Today",
        "Average Import Rate This Week",
        "Average Import Rate This Month",
        "Cheap rate import fraction this week",
        "Cheap rate import fraction this month",
        "Battery Round-trip Efficiency Today",
        "Hours to Cheap Rate",
        "Battery Charged Today",
        "Battery Power Direction",
        "Integration Version",
        "Days Elapsed in Bill Period",
        "km Charged Today",
        "Cost per km Today",
        "Battery Estimated Usable Capacity",
        "Solar Capture Efficiency Today",
        "Net Financial Position This Month",
        "Cheapest Tariff Rate",
        "Cheapest Rate Period Name",
        "On Cheapest Rate",
        "On Base (Daytime) Rate",
        "Minutes Remaining in Rate Period",
        "Rate Saving vs Daytime",
        "Grid Power Direction",
        "Solar Output % of Max",
        "Battery State",
        "Battery Overnight Confidence",
        "Net Solar Surplus",
        "Battery Energy Available",
        "Solar generated this year",
        "Export this year",
        "Export earnings this year",
        "Missed solar today",
        "Inverter Derating Today",
    }

    def test_exactly_five_sensors_disabled(self):
        """Exactly 51 sensors should be disabled by default."""
        state = _parse_sensor_enabled_state()
        disabled = [n for n, enabled in state.items() if not enabled]
        assert len(disabled) == 51, f"Expected 51 disabled sensors, got {len(disabled)}: {disabled}"

    def test_disabled_sensors_are_the_expected_ones(self):
        """The disabled sensors must be the HTML reports and forecast accuracy."""
        state = _parse_sensor_enabled_state()
        disabled_names = {n for n, enabled in state.items() if not enabled}
        assert disabled_names == self.EXPECTED_DISABLED, (
            f"Unexpected disabled set.\n"
            f"  Extra disabled: {disabled_names - self.EXPECTED_DISABLED}\n"
            f"  Missing disabled: {self.EXPECTED_DISABLED - disabled_names}"
        )

    def test_accumulation_sensors_enabled_by_default(self):
        """Yesterday/week/month sensors must be enabled - they are core value.

        Excludes forecast accuracy sensors which are deliberately kept disabled.
        """
        state = _parse_sensor_enabled_state()
        keywords = ("yesterday", "this week", "this month")
        accumulation = {
            n: e
            for n, e in state.items()
            if any(k in n.lower() for k in keywords)
            and n not in TestSensorDefaultEnabled.EXPECTED_DISABLED
        }
        assert len(accumulation) > 0, "No accumulation sensors found"
        for name, enabled in accumulation.items():
            assert enabled, f"Accumulation sensor '{name}' should be enabled by default"


class TestReconfigureStep:
    """Config flow must expose async_step_reconfigure for the HA quality scale."""

    def test_abort_reason_in_strings(self):
        import json

        s = json.loads(
            (PKG / "strings.json").read_text()
        )
        assert "reconfigure_successful" in s.get("config", {}).get("abort", {}), (
            "strings.json must define the reconfigure_successful abort reason."
        )

    def test_reconfigure_step_in_strings(self):
        import json

        s = json.loads(
            (PKG / "strings.json").read_text()
        )
        assert "reconfigure" in s.get("config", {}).get("step", {}), (
            "strings.json must define the reconfigure step."
        )

    def test_quality_scale_reconfiguration_done(self):

        qs = (PKG / "quality_scale.yaml").read_text()
        idx = qs.find("reconfiguration-flow")
        assert idx != -1
        assert "done" in qs[idx : idx + 60]


class TestExceptionTranslations:
    """Exceptions must use translation_key for the HA quality scale."""

    def test_exception_keys_in_strings(self):
        import json

        s = json.loads(
            (PKG / "strings.json").read_text()
        )
        exc = s.get("exceptions", {})
        assert "config_entry_not_ready" in exc
        assert "givtcp_unavailable" in exc

    def test_exceptions_mirrored_in_translations(self):
        import json

        s = json.loads(
            (PKG / "strings.json").read_text()
        )
        e = json.loads(
            (PKG / "translations/en.json").read_text()
        )
        assert e.get("exceptions") == s.get("exceptions"), (
            "translations/en.json exceptions must mirror strings.json."
        )

    def test_quality_scale_exception_translations_done(self):

        qs = (PKG / "quality_scale.yaml").read_text()
        idx = qs.find("exception-translations")
        assert idx != -1
        assert "done" in qs[idx : idx + 60]
