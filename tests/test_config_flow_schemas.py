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
# hacs.json (2026.5.0). Run:  pip install -r requirements-test.txt
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


# ── Schema builders under test ────────────────────────────────────────────────


def _wizard(real_ha_selector, real_vol):
    """Import the wizard schema builders using real HA + voluptuous."""
    import homeassistant.helpers.selector  # noqa: F401
    import voluptuous

    sys.modules["homeassistant.helpers.selector"] = importlib.import_module(
        "homeassistant.helpers.selector"
    )
    sys.modules["voluptuous"] = voluptuous

    # Force re-import with real modules, so nothing keeps a reference to a stub.
    for key in list(sys.modules.keys()):
        if "givenergy_inverter_manager" in key:
            del sys.modules[key]

    from custom_components.givenergy_inverter_manager.core import wizard_model
    from custom_components.givenergy_inverter_manager.wizard import schemas

    return schemas, wizard_model


def _ctx(wizard_model, mode="setup", **current):
    from datetime import date

    return wizard_model.PageContext(
        wizard_model.Mode(mode), date(2031, 6, 15), current=current, home_currency="EUR"
    )


def _all_schemas(schemas, wizard_model, mode):
    ctx = _ctx(wizard_model, mode)
    return {
        "tariff": schemas.tariff_schema(ctx),
        "rates": schemas.rates_schema(ctx, 3, "IE"),
        "bill": schemas.bill_schema(ctx),
        "schedule": schemas.schedule_schema(ctx),
        "battery": schemas.battery_schema(ctx),
        "charge_planning": schemas.charge_planning_schema(ctx),
        "forecast": schemas.forecast_schema(ctx),
        "hot_water": schemas.hot_water_schema(ctx),
        "ev": schemas.ev_schema(ctx),
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestSchemaConstruction:
    """Every page schema must build without raising under real HA selectors."""

    @pytest.mark.parametrize("mode", ["setup", "options"])
    def test_every_page_schema_builds(self, real_ha_selector, real_vol, mode):
        """Catches step < 1e-3 and the like at construction time."""
        schemas, model = _wizard(real_ha_selector, real_vol)

        built = _all_schemas(schemas, model, mode)

        assert all(isinstance(schema, real_vol.Schema) for schema in built.values())

    def test_the_setup_tariff_schema_accepts_a_valid_submission(self, real_ha_selector, real_vol):
        schemas, model = _wizard(real_ha_selector, real_vol)
        schema = schemas.tariff_schema(_ctx(model))

        validated = schema({"base_rate": 0.3, "export_rate": 0.1, "rate_count": "2"})

        assert validated["rate_count"] == "2"

    def test_the_charge_planning_schema_takes_months_as_strings_and_defaults_from_latitude(
        self, real_ha_selector, real_vol
    ):
        schemas, model = _wizard(real_ha_selector, real_vol)
        from datetime import date

        north = model.PageContext(model.Mode.OPTIONS, date(2031, 6, 15), latitude=53.3)
        south = model.PageContext(model.Mode.OPTIONS, date(2031, 6, 15), latitude=-33.9)

        defaults = schemas.charge_planning_schema(north)({})
        southern = schemas.charge_planning_schema(south)({})

        assert defaults["charge_winter_months"] == ["1", "2", "12"]
        assert defaults["charge_shoulder_months"] == ["3", "4", "10", "11"]
        assert defaults["charge_winter_uses_forecast"] is False
        assert southern["charge_winter_months"] == ["6", "7", "8"]

    def test_the_charge_planning_schema_accepts_an_empty_month_list_and_refuses_a_bad_month(
        self, real_ha_selector, real_vol
    ):
        schemas, model = _wizard(real_ha_selector, real_vol)
        schema = schemas.charge_planning_schema(_ctx(model, "options"))

        assert schema({"charge_winter_months": []})["charge_winter_months"] == []
        with pytest.raises(real_vol.error.MultipleInvalid):
            schema({"charge_winter_months": ["13"]})

    def test_the_setup_tariff_schema_needs_both_rates_and_has_no_placeholder(
        self, real_ha_selector, real_vol
    ):
        schemas, model = _wizard(real_ha_selector, real_vol)
        schema = schemas.tariff_schema(_ctx(model))

        with pytest.raises(real_vol.error.MultipleInvalid):
            schema({"rate_count": "0"})

    def test_a_rate_row_accepts_what_the_form_sends(self, real_ha_selector, real_vol):
        schemas, model = _wizard(real_ha_selector, real_vol)
        schema = schemas.rates_schema(_ctx(model), 2, "IE")

        row = {"name": "Night", "rate": 0.12, "start": "23:00:00", "end": "08:00:00"}
        validated = schema({"rate_period_1": row, "rate_period_2": {**row, "name": "Peak"}})

        assert validated["rate_period_1"]["start"] == "23:00:00"

    def test_the_rates_schema_has_exactly_as_many_rows_as_asked(self, real_ha_selector, real_vol):
        schemas, model = _wizard(real_ha_selector, real_vol)

        for count in (1, 3, 5):
            schema = schemas.rates_schema(_ctx(model), count, None)
            assert [str(k) for k in schema.schema] == [f"rate_period_{i}" for i in range(1, count + 1)]


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
    "standing_charge_per_day": "day",
    "pso_levy_per_month": "month",
}


class TestCurrencyUnits:
    def test_default_is_the_home_currency_and_that_falls_back_to_eur(
        self, real_ha_selector, real_vol
    ):
        schemas, model = _wizard(real_ha_selector, real_vol)
        units = _selector_units(schemas.tariff_schema(_ctx(model)))
        assert units["base_rate"] == "EUR/kWh"
        assert units["export_rate"] == "EUR/kWh"
        assert _selector_units(schemas.bill_schema(_ctx(model)))["standing_charge_per_day"] == (
            "EUR/day"
        )
        assert _selector_units(schemas.rates_schema(_ctx(model), 1, None))[
            "rate_period_1.rate"
        ] == ("EUR/kWh")

    @pytest.mark.parametrize("code", ["GBP", "USD", "SEK"])
    def test_a_saved_currency_sets_every_money_unit(self, real_ha_selector, real_vol, code):
        schemas, model = _wizard(real_ha_selector, real_vol)
        ctx = _ctx(model, "options", currency=code, base_rate=0.3, export_rate=0.1)

        tariff = _selector_units(schemas.tariff_schema(ctx))
        bill = _selector_units(schemas.bill_schema(ctx))
        rows = _selector_units(schemas.rates_schema(ctx, 2, None))

        assert tariff["base_rate"] == f"{code}/kWh"
        assert tariff["export_rate"] == f"{code}/kWh"
        for field, per in _MONEY_FIELDS.items():
            assert bill[field] == f"{code}/{per}"
        assert rows["rate_period_1.rate"] == f"{code}/kWh"
        assert rows["rate_period_2.rate"] == f"{code}/kWh"

    def test_the_battery_cost_shows_the_symbol_of_the_saved_currency(
        self, real_ha_selector, real_vol
    ):
        schemas, model = _wizard(real_ha_selector, real_vol)

        gbp = _selector_units(schemas.battery_schema(_ctx(model, "options", currency="GBP")))
        eur = _selector_units(schemas.battery_schema(_ctx(model, "options", currency="EUR")))

        assert gbp["battery_cost_eur"] == "£"
        assert eur["battery_cost_eur"] == "€"

    def test_an_unknown_currency_falls_back_to_eur(self, real_ha_selector, real_vol):
        schemas, model = _wizard(real_ha_selector, real_vol)
        ctx = _ctx(model, "options", currency="XYZ", base_rate=0.3, export_rate=0.1)

        assert _selector_units(schemas.tariff_schema(ctx))["base_rate"] == "EUR/kWh"

    def test_the_currency_entered_on_the_bill_screen_wins_for_the_rows_after_it(
        self, real_ha_selector, real_vol
    ):
        from datetime import date

        schemas, model = _wizard(real_ha_selector, real_vol)
        ctx = model.PageContext(
            model.Mode.SETUP, date(2031, 6, 15), pending={"currency": "GBP"}, home_currency="EUR"
        )

        assert _selector_units(schemas.rates_schema(ctx, 1, None))["rate_period_1.rate"] == (
            "GBP/kWh"
        )
