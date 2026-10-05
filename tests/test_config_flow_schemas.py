"""
test_config_flow_schemas.py — Integration tests for config flow schema construction.

These tests use the REAL homeassistant selector module (not the MagicMock stubs in
conftest.py) to catch selector validation failures that would be silently swallowed
by HA's flow manager at runtime.

HA's NumberSelectorConfig enforces:
  - step must be a float >= 1e-3 OR the literal string "any"
  - min/max must be valid floats when provided

SelectSelectorConfig and TextSelectorConfig are also validated at construction time.

This file is the dedicated contract test for selector-level constraints.
"""

import importlib
import sys

import pytest

# ── Ensure the real homeassistant is used, not the stub from conftest ──────────
# conftest.py installs stubs into sys.modules before collection.
# We must temporarily replace them with real modules for these tests.
#
# NOTE: homeassistant must be installed in the test environment, at the floor in
# hacs.json (2026.2.0). Run:  pip install -r requirements-test.txt
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


# ── Currency units follow the selected currency ───────────────────────────────


def _selector_units(schema):
    """Return {field name: unit} for every NumberSelector, descending into sections."""
    units = {}
    for key, validator in schema.schema.items():
        name = str(getattr(key, "schema", key))
        inner = getattr(validator, "schema", None)
        if inner is not None and hasattr(inner, "schema"):
            units.update({f"{name}.{k}": v for k, v in _selector_units(inner).items()})
        elif hasattr(validator, "config") and "unit_of_measurement" in validator.config:
            units[name] = validator.config["unit_of_measurement"]
    return units


_MONEY_FIELDS = {
    "base_rate": "kWh",
    "export_rate": "kWh",
    "standing_charge_per_day": "day",
    "pso_levy_per_month": "month",
}


class TestTariffSchemaCurrencyUnits:
    def test_default_is_eur(self, real_ha_selector, real_vol):
        flow_class = _get_flow_class(real_ha_selector, real_vol)
        units = _selector_units(flow_class._build_tariff_schema())
        assert units["base_rate"] == "EUR/kWh"
        assert units["export_rate"] == "EUR/kWh"
        assert units["standing_charge_per_day"] == "EUR/day"
        assert units["pso_levy_per_month"] == "EUR/month"
        assert units["rate_period_1.rate"] == "EUR/kWh"

    @pytest.mark.parametrize("code", ["GBP", "USD", "SEK"])
    def test_saved_currency_sets_every_money_unit(self, real_ha_selector, real_vol, code):
        flow_class = _get_flow_class(real_ha_selector, real_vol)
        units = _selector_units(flow_class._build_tariff_schema(values={"currency": code}))
        for field, per in _MONEY_FIELDS.items():
            assert units[field] == f"{code}/{per}"
        assert units["rate_period_1.rate"] == f"{code}/kWh"
        assert units["rate_period_2.rate"] == f"{code}/kWh"

    def test_explicit_currency_wins_over_saved_values(self, real_ha_selector, real_vol):
        flow_class = _get_flow_class(real_ha_selector, real_vol)
        schema = flow_class._build_tariff_schema(values={"currency": "EUR"}, currency="GBP")
        assert _selector_units(schema)["base_rate"] == "GBP/kWh"

    def test_unknown_currency_falls_back_to_eur(self, real_ha_selector, real_vol):
        flow_class = _get_flow_class(real_ha_selector, real_vol)
        units = _selector_units(flow_class._build_tariff_schema(values={"currency": "XYZ"}))
        assert units["base_rate"] == "EUR/kWh"


class TestOptionsFlowCurrencyUnits:
    @staticmethod
    def _form_schema(real_ha_selector, real_vol, data):
        import asyncio
        from unittest.mock import MagicMock

        _get_flow_class(real_ha_selector, real_vol)
        config_flow = importlib.import_module(
            "custom_components.givenergy_inverter_manager.config_flow"
        )
        entry = MagicMock()
        entry.options = {}
        entry.data = data
        flow = config_flow.GivEnergyOptionsFlow(entry)
        flow.async_show_form = MagicMock(return_value={"type": "form"})
        asyncio.run(flow.async_step_init(None))
        return flow.async_show_form.call_args.kwargs["data_schema"]

    def test_gbp_entry_shows_gbp_units(self, real_ha_selector, real_vol):
        schema = self._form_schema(real_ha_selector, real_vol, {"currency": "GBP"})
        units = _selector_units(schema)
        assert units["tariff_settings.base_rate"] == "GBP/kWh"
        assert units["tariff_settings.export_rate"] == "GBP/kWh"
        assert units["tariff_settings.standing_charge_per_day"] == "GBP/day"
        assert units["tariff_settings.pso_levy_per_month"] == "GBP/month"
        assert units["rate_period_1.rate"] == "GBP/kWh"
        assert units["threshold_settings.battery_cost_eur"] == "£"

    def test_eur_entry_is_unchanged(self, real_ha_selector, real_vol):
        schema = self._form_schema(real_ha_selector, real_vol, {"currency": "EUR"})
        units = _selector_units(schema)
        assert units["tariff_settings.base_rate"] == "EUR/kWh"
        assert units["rate_period_1.rate"] == "EUR/kWh"
        assert units["threshold_settings.battery_cost_eur"] == "€"
