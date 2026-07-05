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
