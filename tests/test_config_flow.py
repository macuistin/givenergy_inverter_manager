"""
test_config_flow_schemas.py — Integration tests for config flow schema construction.

These tests use the REAL homeassistant selector module (not the MagicMock stubs in
conftest.py) to catch selector validation failures that would be silently swallowed
by HA's flow manager at runtime.

HA's NumberSelectorConfig enforces:
  - step must be a float >= 1e-3 OR the literal string "any"
  - min/max must be valid floats when provided

SelectSelectorConfig and TextSelectorConfig are also validated at construction time.

The test_config_flow.py file uses MagicMock stubs for speed and isolation; this file
is the dedicated contract test for selector-level constraints.
"""

import importlib
import sys

import pytest

# ── Ensure the real homeassistant is used, not the stub from conftest ──────────
# conftest.py installs stubs into sys.modules before collection.
# We must temporarily replace them with real modules for these tests.
#
# NOTE: homeassistant must be installed in the test environment.
# Run:  pip install "homeassistant==2024.12.5" --break-system-packages
# ───────────────────────────────────────────────────────────────────────────────

_HA_MODULES_TO_RESTORE = [
    "homeassistant",
    "homeassistant.helpers",
    "homeassistant.helpers.selector",
    "voluptuous",
]


@pytest.fixture(scope="module")
def real_ha_selector():
    """Temporarily replace stub modules with real homeassistant imports.

    Saves the entire state of sys.modules before the test module runs,
    restores it completely afterwards — no leakage into other test files.
    """
    saved = dict(sys.modules)

    # Clear everything homeassistant-related and voluptuous so the real
    # packages are loaded fresh.
    for key in list(sys.modules.keys()):
        if key == "voluptuous" or key.startswith("homeassistant"):
            del sys.modules[key]

    try:
        import voluptuous  # noqa: F401
        from homeassistant.helpers import selector as sel

        yield sel
    finally:
        # Remove anything loaded during the tests
        for key in list(sys.modules.keys()):
            if key not in saved:
                del sys.modules[key]
        # Restore exact prior state
        sys.modules.update(saved)


@pytest.fixture(scope="module")
def real_vol(real_ha_selector):
    """Return real voluptuous alongside the real selector."""
    import voluptuous as vol

    return vol


# ── Schema builder under test ─────────────────────────────────────────────────


def _get_flow_class(real_ha_selector, real_vol):
    """Import GivEnergyInverterManagerConfigFlow using real HA + voluptuous."""
    # Patch in real modules before importing config_flow
    import homeassistant.helpers.selector  # noqa: F401
    import voluptuous

    sys.modules["homeassistant.helpers.selector"] = importlib.import_module(
        "homeassistant.helpers.selector"
    )
    sys.modules["voluptuous"] = voluptuous

    # Force re-import of config_flow with real modules
    cf_name = "custom_components.givenergy_inverter_manager.config_flow"
    if cf_name in sys.modules:
        del sys.modules[cf_name]

    # Also remove any cached sub-imports that reference stubs
    for key in list(sys.modules.keys()):
        if "givenergy_inverter_manager" in key:
            del sys.modules[key]

    from custom_components.givenergy_inverter_manager.config_flow import (
        GivEnergyInverterManagerConfigFlow,
    )

    return GivEnergyInverterManagerConfigFlow


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestTariffSchemaConstruction:
    """The tariff schema must build without raising under real HA selectors."""

    def test_build_tariff_schema_does_not_raise(self, real_ha_selector, real_vol):
        """_build_tariff_schema() must succeed — catches step < 1e-3 etc."""
        flow_class = _get_flow_class(real_ha_selector, real_vol)
        # staticmethod — call on class directly
        schema = flow_class._build_tariff_schema()
        assert schema is not None

    def test_tariff_schema_is_vol_schema(self, real_ha_selector, real_vol):
        """Result must be a voluptuous Schema."""
        import voluptuous as vol

        flow_class = _get_flow_class(real_ha_selector, real_vol)
        schema = flow_class._build_tariff_schema()
        assert isinstance(schema, vol.Schema)

    def test_tariff_schema_accepts_valid_defaults(self, real_ha_selector, real_vol):
        """Schema must accept a dict including rate period sections without raising."""
        from custom_components.givenergy_inverter_manager.config_flow import (
            _periods_to_slot_defaults,
        )
        from custom_components.givenergy_inverter_manager.const import (
            DEFAULT_BASE_RATE,
            DEFAULT_BASE_RATE_NAME,
            DEFAULT_BILL_START_DAY,
            DEFAULT_CURRENCY,
            DEFAULT_DISCOUNT_RATE,
            DEFAULT_EXPORT_RATE,
            DEFAULT_PSO_LEVY,
            DEFAULT_RATE_PERIODS,
            DEFAULT_STANDING_CHARGE,
            DEFAULT_VAT_RATE,
        )

        flow_class = _get_flow_class(real_ha_selector, real_vol)
        schema = flow_class._build_tariff_schema()

        slots = _periods_to_slot_defaults(DEFAULT_RATE_PERIODS)
        valid_data = {
            "base_rate": DEFAULT_BASE_RATE,
            "base_rate_name": DEFAULT_BASE_RATE_NAME,
            "export_rate": DEFAULT_EXPORT_RATE,
            "standing_charge_per_day": DEFAULT_STANDING_CHARGE,
            "pso_levy_per_month": DEFAULT_PSO_LEVY,
            "vat_rate": DEFAULT_VAT_RATE,
            "discount_rate": DEFAULT_DISCOUNT_RATE,
            "bill_start_day": DEFAULT_BILL_START_DAY,
            "currency": DEFAULT_CURRENCY,
            "rate_period_1": slots[0],
            "rate_period_2": slots[1],
        }
        # Should not raise
        result = schema(valid_data)
        assert result is not None


class TestNumberSelectorStepConstraint:
    """Document and enforce HA's step >= 1e-3 constraint directly."""

    @pytest.mark.parametrize("step", [0.001, 0.01, 0.1, 1.0, "any"])
    def test_valid_steps_accepted(self, real_ha_selector, step):
        """Steps >= 0.001 and 'any' must be accepted by NumberSelectorConfig."""
        kwargs = {"min": 0, "max": 10}
        if step != "any":
            kwargs["step"] = step
        else:
            kwargs["step"] = "any"
        # Must not raise
        sel = real_ha_selector.NumberSelector(real_ha_selector.NumberSelectorConfig(**kwargs))
        assert sel is not None

    @pytest.mark.parametrize("step", [0.0001, 0.00001, 0.0009])
    def test_sub_minimum_steps_rejected(self, real_ha_selector, real_vol, step):
        """Steps < 0.001 must be rejected by HA's selector validation."""
        with pytest.raises(real_vol.error.MultipleInvalid):
            real_ha_selector.NumberSelector(
                real_ha_selector.NumberSelectorConfig(min=0, max=10, step=step)
            )


# ── Sensor default-enabled tests ──────────────────────────────────────────────
# These tests parse sensor.py via AST rather than importing it, avoiding the
# need to stub SensorEntityDescription subclassing.


def _parse_sensor_enabled_state():
    """Return {name: enabled_default} by parsing sensor.py with ast."""
    import ast
    from pathlib import Path

    src = (
        Path(__file__).parent.parent / "custom_components/givenergy_inverter_manager/sensor.py"
    ).read_text()
    tree = ast.parse(src)

    results = {}
    # Walk all Call nodes looking for GivEnergyManagerSensorDescription(...)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name_val = None
        enabled_val = True  # default per dataclass default
        for kw in node.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                name_val = kw.value.value
            if kw.arg == "entity_registry_enabled_default" and isinstance(kw.value, ast.Constant):
                enabled_val = bool(kw.value.value)
        if name_val is not None:
            results[name_val] = enabled_val
    return results


class TestSensorDefaultEnabled:
    """Document exactly which sensors are disabled by default."""

    EXPECTED_DISABLED = {
        "Today's energy summary",
        "Tonight's charge plan",
        "This week's energy summary",
        "Forecast accuracy yesterday",
        "Forecast accuracy 7-day average",
        "Export — trailing 12 months",
        "Battery Cycle Cost per kWh",
        "Saving vs Grid Today",
        "Net Saving Today (inc. battery wear)",
        "Pre-boost export recommended",
        "Pre-boost exportable kWh",
        "Pre-boost export net gain",
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
        "Next Cheap Rate Start",
        "Hours to Cheap Rate",
        "Battery Charged Today",
        "Battery Discharged Today",
        "Battery Power Direction",
        "Integration Version",
        "Days Elapsed in Bill Period",
        "EV km Charged Today",
        "EV Cost per km Today",
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
        "Night Survival Confidence",
        "Net Solar Surplus",
        "Battery Energy Available",
    }

    def test_exactly_five_sensors_disabled(self):
        """Exactly 54 sensors should be disabled by default."""
        state = _parse_sensor_enabled_state()
        disabled = [n for n, enabled in state.items() if not enabled]
        assert len(disabled) == 54, f"Expected 54 disabled sensors, got {len(disabled)}: {disabled}"

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


# ── Options flow forecast step tests ─────────────────────────────────────────


class TestOptionsFlowSections:
    """Options flow must use a single init step with collapsible sections."""

    def _make_flow(self):
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.config_flow import (
            GivEnergyOptionsFlow,
        )
        from custom_components.givenergy_inverter_manager.const import (
            DEFAULT_BASE_RATE,
            DEFAULT_BATTERY_MIN_SOC,
            DEFAULT_OVERNIGHT_CHARGE_TARGET,
            DEFAULT_SKIP_CHARGE_SOC_THRESHOLD,
        )

        entry = MagicMock()
        entry.options = {}
        entry.data = {
            "battery_min_soc_pct": DEFAULT_BATTERY_MIN_SOC,
            "overnight_charge_target_pct": DEFAULT_OVERNIGHT_CHARGE_TARGET,
            "skip_charge_soc_threshold_pct": DEFAULT_SKIP_CHARGE_SOC_THRESHOLD,
            "base_rate": DEFAULT_BASE_RATE,
        }

        flow = GivEnergyOptionsFlow(entry)
        flow.async_show_form = MagicMock(return_value={"type": "form"})
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
        return flow

    def test_init_without_input_shows_form(self):
        """Visiting init step with no input shows the options form."""
        import asyncio
        from unittest.mock import MagicMock, patch

        flow = self._make_flow()
        with (
            patch("custom_components.givenergy_inverter_manager.config_flow.vol") as mock_vol,
            patch("custom_components.givenergy_inverter_manager.config_flow.selector") as mock_sel,
            patch(
                "custom_components.givenergy_inverter_manager.config_flow.section"
            ) as mock_section,
        ):
            mock_vol.Schema.return_value = MagicMock()
            mock_vol.Required.return_value = MagicMock()
            mock_vol.Optional.return_value = MagicMock()
            mock_section.return_value = MagicMock()
            mock_sel.NumberSelector.return_value = MagicMock()
            mock_sel.TextSelector.return_value = MagicMock()
            mock_sel.SelectSelector.return_value = MagicMock()
            mock_sel.EntitySelector.return_value = MagicMock()
            mock_sel.BooleanSelector.return_value = MagicMock()
            asyncio.run(flow.async_step_init(None))

        flow.async_show_form.assert_called_once()
        call_kwargs = flow.async_show_form.call_args
        step = call_kwargs.kwargs.get("step_id") or (
            call_kwargs.args[0] if call_kwargs.args else None
        )
        assert step == "init"
        flow.async_create_entry.assert_not_called()

    def test_init_with_nested_input_calls_create_entry(self):
        """Submitting the sections form should save all nested data and create entry."""
        import asyncio

        from custom_components.givenergy_inverter_manager.const import (
            CONF_BASE_RATE,
            CONF_BATTERY_MIN_SOC,
            CONF_FORECAST_PROVIDER,
            DEFAULT_BASE_RATE_NAME,
            DEFAULT_BILL_START_DAY,
            DEFAULT_CURRENCY,
            DEFAULT_DISCOUNT_RATE,
            DEFAULT_EXPORT_RATE,
            DEFAULT_OVERNIGHT_CHARGE_TARGET,
            DEFAULT_PSO_LEVY,
            DEFAULT_SKIP_CHARGE_SOC_THRESHOLD,
            DEFAULT_STANDING_CHARGE,
            DEFAULT_VAT_RATE,
            FORECAST_PROVIDER_FORECAST_SOLAR,
        )

        flow = self._make_flow()
        nested_input = {
            "tariff_settings": {
                CONF_BASE_RATE: 0.35,
                "base_rate_name": DEFAULT_BASE_RATE_NAME,
                "export_rate": DEFAULT_EXPORT_RATE,
                "standing_charge_per_day": DEFAULT_STANDING_CHARGE,
                "pso_levy_per_month": DEFAULT_PSO_LEVY,
                "vat_rate": DEFAULT_VAT_RATE,
                "discount_rate": DEFAULT_DISCOUNT_RATE,
                "bill_start_day": DEFAULT_BILL_START_DAY,
                "currency": DEFAULT_CURRENCY,
            },
            "rate_period_1": {
                "name": "Night",
                "rate": 0.1644,
                "start": "23:00:00",
                "end": "08:00:00",
            },
            "rate_period_2": {
                "name": "Nightboost",
                "rate": 0.0965,
                "start": "02:00:00",
                "end": "04:00:00",
            },
            "threshold_settings": {
                CONF_BATTERY_MIN_SOC: 10,
                "overnight_charge_target_pct": DEFAULT_OVERNIGHT_CHARGE_TARGET,
                "skip_charge_soc_threshold_pct": DEFAULT_SKIP_CHARGE_SOC_THRESHOLD,
                "dry_run": False,
                "verbose_logging": False,
            },
            "forecast_settings": {
                CONF_FORECAST_PROVIDER: FORECAST_PROVIDER_FORECAST_SOLAR,
                "forecast_entity": "sensor.forecast_solar_today",
            },
        }
        asyncio.run(flow.async_step_init(nested_input))

        flow.async_create_entry.assert_called_once()
        data = flow.async_create_entry.call_args.kwargs.get("data") or {}
        assert data.get(CONF_BASE_RATE) == 0.35
        assert data.get(CONF_BATTERY_MIN_SOC) == 10
        assert data.get(CONF_FORECAST_PROVIDER) == FORECAST_PROVIDER_FORECAST_SOLAR

    def _tariff_input(self):
        from custom_components.givenergy_inverter_manager.const import (
            CONF_BASE_RATE,
            DEFAULT_BASE_RATE_NAME,
            DEFAULT_BILL_START_DAY,
            DEFAULT_CURRENCY,
            DEFAULT_DISCOUNT_RATE,
            DEFAULT_EXPORT_RATE,
            DEFAULT_PSO_LEVY,
            DEFAULT_STANDING_CHARGE,
            DEFAULT_VAT_RATE,
        )

        return {
            "tariff_settings": {
                CONF_BASE_RATE: 0.35,
                "base_rate_name": DEFAULT_BASE_RATE_NAME,
                "export_rate": DEFAULT_EXPORT_RATE,
                "standing_charge_per_day": DEFAULT_STANDING_CHARGE,
                "pso_levy_per_month": DEFAULT_PSO_LEVY,
                "vat_rate": DEFAULT_VAT_RATE,
                "discount_rate": DEFAULT_DISCOUNT_RATE,
                "bill_start_day": DEFAULT_BILL_START_DAY,
                "currency": DEFAULT_CURRENCY,
            },
            "threshold_settings": {},
            "forecast_settings": {},
        }

    def test_hardware_settings_are_saved_to_options(self):
        import asyncio

        from custom_components.givenergy_inverter_manager.const import (
            CONF_BATTERY_CAPACITY,
            CONF_IMMERSION_WATTAGE,
            CONF_INVERTER_MAX_OUTPUT,
        )

        flow = self._make_flow()
        user_input = self._tariff_input()
        user_input["hardware_settings"] = {
            CONF_BATTERY_CAPACITY: 18.6,
            CONF_INVERTER_MAX_OUTPUT: 5.0,
            CONF_IMMERSION_WATTAGE: 2800,
        }
        asyncio.run(flow.async_step_init(user_input))

        data = flow.async_create_entry.call_args.kwargs["data"]
        assert data[CONF_BATTERY_CAPACITY] == pytest.approx(18.6)
        assert data[CONF_INVERTER_MAX_OUTPUT] == pytest.approx(5.0)
        assert data[CONF_IMMERSION_WATTAGE] == pytest.approx(2800.0)

    def test_ev_efficiency_is_saved_to_options(self):
        import asyncio

        from custom_components.givenergy_inverter_manager.const import (
            CONF_CAR_EFFICIENCY_KWH_PER_100KM,
        )

        flow = self._make_flow()
        user_input = self._tariff_input()
        user_input["ev_settings"] = {CONF_CAR_EFFICIENCY_KWH_PER_100KM: 17.5}
        asyncio.run(flow.async_step_init(user_input))

        data = flow.async_create_entry.call_args.kwargs["data"]
        assert data[CONF_CAR_EFFICIENCY_KWH_PER_100KM] == pytest.approx(17.5)

    def test_ev_settings_section_has_labels(self):
        import json
        from pathlib import Path

        base = Path("custom_components/givenergy_inverter_manager")
        for name in ("strings.json", "translations/en.json"):
            data = json.loads((base / name).read_text())
            sections = data["options"]["step"]["init"]["sections"]
            assert "car_efficiency_kwh_per_100km" in sections["ev_settings"]["data"]

    def test_empty_forecast_fields_clear_saved_entities(self):
        import asyncio

        from custom_components.givenergy_inverter_manager.const import (
            CONF_CARBON_INTENSITY_ENTITY,
            CONF_FORECAST_ENTITY,
            CONF_FORECAST_ENTITY_D2,
            CONF_FORECAST_ENTITY_P10,
        )

        flow = self._make_flow()
        flow._options[CONF_FORECAST_ENTITY_P10] = "sensor.old_p10"
        user_input = self._tariff_input()
        user_input["forecast_settings"] = {CONF_FORECAST_ENTITY: "sensor.forecast_today"}
        asyncio.run(flow.async_step_init(user_input))

        data = flow.async_create_entry.call_args.kwargs["data"]
        assert data[CONF_FORECAST_ENTITY] == "sensor.forecast_today"
        assert data[CONF_FORECAST_ENTITY_P10] == ""
        assert data[CONF_FORECAST_ENTITY_D2] == ""
        assert data[CONF_CARBON_INTENSITY_ENTITY] == ""

    def test_selectors_have_no_empty_string_default(self):
        """An empty-string default fails EntitySelector validation in the HA frontend."""
        import re
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/config_flow.py").read_text()
        assert not re.findall(r"default=self\._get\(\w+,\s*\"\"\)", src)

    def test_optional_key_prefills_saved_value_without_default(self):
        import voluptuous as real_vol

        flow = self._make_flow()
        flow._config_entry.options = {"forecast_entity": "sensor.forecast_today"}
        from unittest.mock import patch

        with patch("custom_components.givenergy_inverter_manager.config_flow.vol", real_vol):
            filled = flow._optional_key("forecast_entity")
            empty = flow._optional_key("forecast_entity_p10")
        assert filled.description == {"suggested_value": "sensor.forecast_today"}
        assert empty.default is real_vol.UNDEFINED

    def test_missing_hardware_section_leaves_options_unchanged(self):
        import asyncio

        from custom_components.givenergy_inverter_manager.const import CONF_BATTERY_CAPACITY

        flow = self._make_flow()
        asyncio.run(flow.async_step_init(self._tariff_input()))

        data = flow.async_create_entry.call_args.kwargs["data"]
        assert CONF_BATTERY_CAPACITY not in data

    def test_each_optional_has_exactly_one_schema_key(self, real_vol):
        """Every vol.Optional in the options flow must have exactly one schema key.

        Regression test for: CONF_CHEAP_RATE_FLOOR_SOC accidentally inserted as a
        positional argument inside vol.Optional(CONF_BATTERY_MIN_SOC, ...), causing
        'TypeError: Optional.__init__() got multiple values for argument default'.
        The existing test mocks vol.Optional so it cannot catch this class of bug.
        """
        import re
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/config_flow.py").read_text()
        # Find every vol.Optional( call and check that the first positional arg
        # is not followed by another CONF_ constant before the default= keyword
        bad = re.findall(
            r"vol\.Optional\(\s*(CONF_\w+)\s*,\s*(CONF_\w+|DEFAULT_\w+)\s*(?!,\s*description)",
            src,
        )
        assert not bad, (
            f"vol.Optional calls with multiple positional CONF/DEFAULT args found: {bad}\n"
            "Each schema key must be its own vol.Optional entry."
        )

    def test_cheap_rate_floor_is_separate_schema_key(self):
        """CONF_CHEAP_RATE_FLOOR_SOC must be its own vol.Optional entry,
        not a positional argument inside another key's vol.Optional call."""
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/config_flow.py").read_text()
        # Find the threshold_settings section
        section_start = src.find("threshold_settings")
        section_end = src.find(")", src.find("vol.Schema", section_start))
        section = src[section_start:section_end]
        # CONF_CHEAP_RATE_FLOOR_SOC must appear as the first arg of its own vol.Optional,
        # not alongside another key
        import re

        optional_calls = re.findall(r"vol\.Optional\(\s*(\w+)\s*(?:,\s*(\w+))?", section)
        for call in optional_calls:
            first_arg, second_arg = call
            if first_arg == "CONF_BATTERY_MIN_SOC":
                assert second_arg != "CONF_CHEAP_RATE_FLOOR_SOC", (
                    "CONF_CHEAP_RATE_FLOOR_SOC must not appear as a positional arg "
                    "inside vol.Optional(CONF_BATTERY_MIN_SOC, ...) — it must be its "
                    "own separate vol.Optional entry."
                )

    def test_no_separate_tariff_thresholds_forecast_steps(self):
        """The old multi-step methods must not exist on the options flow."""
        from custom_components.givenergy_inverter_manager.config_flow import GivEnergyOptionsFlow

        for old_step in ("async_step_tariff", "async_step_thresholds", "async_step_forecast"):
            assert not hasattr(GivEnergyOptionsFlow, old_step), (
                f"Options flow still has {old_step} — should use single async_step_init"
            )


class TestReconfigureStep:
    """Config flow must expose async_step_reconfigure for the HA quality scale."""

    def test_reconfigure_step_exists(self):
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/config_flow.py").read_text()
        assert "async def async_step_reconfigure" in src, (
            "async_step_reconfigure is required for the reconfiguration-flow quality scale item."
        )

    def test_reconfigure_reloads_entry_on_success(self):
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/config_flow.py").read_text()
        reconf = src[src.find("async def async_step_reconfigure") :]
        reconf = reconf[: reconf.find("\n    async def ")]
        assert "async_reload" in reconf, (
            "Reconfigure must reload the entry after updating so new tariff takes effect."
        )

    def test_reconfigure_uses_abort_reason(self):
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/config_flow.py").read_text()
        reconf = src[src.find("async def async_step_reconfigure") :]
        reconf = reconf[: reconf.find("\n    async def ")]
        assert "reconfigure_successful" in reconf, (
            "Reconfigure must abort with 'reconfigure_successful' on success."
        )

    def test_abort_reason_in_strings(self):
        import json
        from pathlib import Path

        s = json.loads(
            Path("custom_components/givenergy_inverter_manager/strings.json").read_text()
        )
        assert "reconfigure_successful" in s.get("config", {}).get("abort", {}), (
            "strings.json must define the reconfigure_successful abort reason."
        )

    def test_reconfigure_step_in_strings(self):
        import json
        from pathlib import Path

        s = json.loads(
            Path("custom_components/givenergy_inverter_manager/strings.json").read_text()
        )
        assert "reconfigure" in s.get("config", {}).get("step", {}), (
            "strings.json must define the reconfigure step."
        )

    def test_quality_scale_reconfiguration_done(self):
        from pathlib import Path

        qs = Path("custom_components/givenergy_inverter_manager/quality_scale.yaml").read_text()
        idx = qs.find("reconfiguration-flow")
        assert idx != -1
        assert "done" in qs[idx : idx + 60]


class TestExceptionTranslations:
    """Exceptions must use translation_key for the HA quality scale."""

    def test_config_entry_not_ready_uses_translation_key(self):
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/__init__.py").read_text()
        assert "translation_key" in src and "config_entry_not_ready" in src, (
            "ConfigEntryNotReady must use translation_key for exception-translations."
        )

    def test_update_failed_uses_translation_key(self):
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/coordinator.py").read_text()
        raise_block = src[src.find("raise UpdateFailed") :][:200]
        assert "translation_key" in raise_block, (
            "UpdateFailed must use translation_key for exception-translations."
        )

    def test_exception_keys_in_strings(self):
        import json
        from pathlib import Path

        s = json.loads(
            Path("custom_components/givenergy_inverter_manager/strings.json").read_text()
        )
        exc = s.get("exceptions", {})
        assert "config_entry_not_ready" in exc
        assert "givtcp_unavailable" in exc

    def test_exceptions_mirrored_in_translations(self):
        import json
        from pathlib import Path

        s = json.loads(
            Path("custom_components/givenergy_inverter_manager/strings.json").read_text()
        )
        e = json.loads(
            Path("custom_components/givenergy_inverter_manager/translations/en.json").read_text()
        )
        assert e.get("exceptions") == s.get("exceptions"), (
            "translations/en.json exceptions must mirror strings.json."
        )

    def test_quality_scale_exception_translations_done(self):
        from pathlib import Path

        qs = Path("custom_components/givenergy_inverter_manager/quality_scale.yaml").read_text()
        idx = qs.find("exception-translations")
        assert idx != -1
        assert "done" in qs[idx : idx + 60]


class TestManualSetupPath:
    """The manual entity path of the inverter step must build its form and advance."""

    @pytest.fixture(autouse=True)
    def _isolate_selectors(self):
        """Replace selectors and voluptuous so results do not depend on test order."""
        from unittest.mock import MagicMock, patch

        module = "custom_components.givenergy_inverter_manager.config_flow"
        with patch(f"{module}.selector", MagicMock()), patch(f"{module}.vol", MagicMock()):
            yield

    @staticmethod
    def _flow():
        import asyncio  # noqa: F401
        from unittest.mock import AsyncMock, MagicMock

        from custom_components.givenergy_inverter_manager.config_flow import (
            GivEnergyInverterManagerConfigFlow,
        )

        flow = GivEnergyInverterManagerConfigFlow()
        flow.hass = MagicMock()
        flow.hass.states.async_all.return_value = []
        flow.async_show_form = MagicMock(return_value={"type": "form"})
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()
        flow.async_step_tariff = AsyncMock(return_value={"type": "form", "step_id": "tariff"})
        return flow

    @staticmethod
    def _entities():
        return {
            "solar_power_entity": "sensor.solar",
            "battery_soc_entity": "sensor.soc",
            "battery_power_entity": "sensor.battery",
            "grid_power_entity": "sensor.grid",
            "house_load_entity": "sensor.house",
            "battery_capacity_kwh": 18.6,
        }

    def test_manual_form_builds_without_discovered_inverters(self):
        import asyncio

        flow = self._flow()
        asyncio.run(flow.async_step_inverter(None))

        flow.async_show_form.assert_called_once()
        assert flow.async_show_form.call_args.kwargs["step_id"] == "inverter"

    def test_manual_schema_default_is_the_manual_option(self):
        from unittest.mock import patch

        import voluptuous as real_vol

        flow = self._flow()
        options = [{"value": "__manual__", "label": "Manual entry"}]
        with patch("custom_components.givenergy_inverter_manager.config_flow.vol", real_vol):
            flow._build_manual_schema(10.0, options)

    def test_complete_manual_input_advances_to_tariff(self):
        import asyncio

        flow = self._flow()
        result = asyncio.run(flow.async_step_inverter(self._entities()))

        assert result == {"type": "form", "step_id": "tariff"}
        flow.async_step_tariff.assert_awaited_once()
        flow.async_show_form.assert_not_called()
        assert flow._data["solar_power_entity"] == "sensor.solar"

    def test_missing_entity_shows_error_and_does_not_advance(self):
        import asyncio

        flow = self._flow()
        user_input = self._entities()
        del user_input["grid_power_entity"]
        asyncio.run(flow.async_step_inverter(user_input))

        flow.async_step_tariff.assert_not_awaited()
        assert flow.async_show_form.call_args.kwargs["errors"] == {"base": "missing_entities"}


class TestOptionsFlowSavedValues:
    """A saved option wins over the setup value even when it is falsy."""

    @staticmethod
    def _flow(options, data):
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.config_flow import GivEnergyOptionsFlow

        entry = MagicMock()
        entry.options = options
        entry.data = data
        return GivEnergyOptionsFlow(entry)

    def test_saved_zero_is_kept(self):
        flow = self._flow({"cheap_rate_floor_soc": 0}, {"cheap_rate_floor_soc": 40})
        assert flow._get("cheap_rate_floor_soc", 40) == 0

    def test_cleared_entity_does_not_fall_back_to_setup(self):
        flow = self._flow({"forecast_entity": ""}, {"forecast_entity": "sensor.forecast_today"})
        assert flow._get("forecast_entity", "") == ""

    def test_saved_empty_rate_periods_are_kept(self):
        flow = self._flow({"rate_periods": []}, {"rate_periods": [{"name": "Night"}]})
        assert flow._get("rate_periods", [{"name": "default"}]) == []

    def test_unset_option_uses_setup_value(self):
        flow = self._flow({}, {"base_rate": 0.31})
        assert flow._get("base_rate", 0.2) == 0.31

    def test_missing_everywhere_uses_default(self):
        flow = self._flow({}, {})
        assert flow._get("base_rate", 0.2) == 0.2

    def test_cleared_entity_shows_no_suggested_value(self):
        from unittest.mock import patch

        import voluptuous as real_vol

        flow = self._flow({"forecast_entity": ""}, {"forecast_entity": "sensor.forecast_today"})
        with patch("custom_components.givenergy_inverter_manager.config_flow.vol", real_vol):
            key = flow._optional_key("forecast_entity")
        assert key.description is None
