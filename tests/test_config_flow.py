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
        """Schema must accept a dict of all default values without raising."""
        from custom_components.givenergy_inverter_manager.config_flow import (
            _rate_periods_to_text,
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

        valid_data = {
            "base_rate": DEFAULT_BASE_RATE,
            "base_rate_name": DEFAULT_BASE_RATE_NAME,
            "rate_periods_text": _rate_periods_to_text(DEFAULT_RATE_PERIODS),
            "export_rate": DEFAULT_EXPORT_RATE,
            "standing_charge_per_day": DEFAULT_STANDING_CHARGE,
            "pso_levy_per_month": DEFAULT_PSO_LEVY,
            "vat_rate": DEFAULT_VAT_RATE,
            "discount_rate": DEFAULT_DISCOUNT_RATE,
            "bill_start_day": DEFAULT_BILL_START_DAY,
            "currency": DEFAULT_CURRENCY,
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
    }

    def test_exactly_five_sensors_disabled(self):
        """Exactly 5 sensors should be disabled by default."""
        state = _parse_sensor_enabled_state()
        disabled = [n for n, enabled in state.items() if not enabled]
        assert len(disabled) == 5, f"Expected 5 disabled sensors, got {len(disabled)}: {disabled}"

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

        from custom_components.givenergy_inverter_manager.config_flow import (
            _rate_periods_to_text,
        )
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
            DEFAULT_RATE_PERIODS,
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
                "rate_periods_text": _rate_periods_to_text(DEFAULT_RATE_PERIODS),
                "export_rate": DEFAULT_EXPORT_RATE,
                "standing_charge_per_day": DEFAULT_STANDING_CHARGE,
                "pso_levy_per_month": DEFAULT_PSO_LEVY,
                "vat_rate": DEFAULT_VAT_RATE,
                "discount_rate": DEFAULT_DISCOUNT_RATE,
                "bill_start_day": DEFAULT_BILL_START_DAY,
                "currency": DEFAULT_CURRENCY,
            },
            "threshold_settings": {
                CONF_BATTERY_MIN_SOC: 10,
                "overnight_charge_target_pct": DEFAULT_OVERNIGHT_CHARGE_TARGET,
                "skip_charge_soc_threshold_pct": DEFAULT_SKIP_CHARGE_SOC_THRESHOLD,
                "ev_battery_protect_soc_pct": 20,
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

    def test_no_separate_tariff_thresholds_forecast_steps(self):
        """The old multi-step methods must not exist on the options flow."""
        from custom_components.givenergy_inverter_manager.config_flow import GivEnergyOptionsFlow

        for old_step in ("async_step_tariff", "async_step_thresholds", "async_step_forecast"):
            assert not hasattr(GivEnergyOptionsFlow, old_step), (
                f"Options flow still has {old_step} — should use single async_step_init"
            )
