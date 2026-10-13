"""Every error a wizard page can return is in the list the strings are checked against."""

from __future__ import annotations

from datetime import date

from custom_components.givenergy_inverter_manager.core.wizard_model import (
    ERROR_KEYS,
    Mode,
    PageContext,
)
from custom_components.givenergy_inverter_manager.core.wizard_pages import (
    missing_wiring,
    validate_hot_water,
)
from custom_components.givenergy_inverter_manager.core.wizard_tariff import (
    validate_bill,
    validate_change_date,
    validate_rates,
    validate_tariff,
)

NIGHT = {"name": "Night", "rate": 0.15, "start": "23:00", "end": "08:00"}
CTX = PageContext(Mode.OPTIONS, date(2031, 6, 15))


def _key(errors: dict[str, str]) -> str:
    assert set(errors) == {"base"}
    return errors["base"]


def _produced() -> set[str]:
    """The error keys the validators return for the inputs that trigger each of them."""
    results = [
        validate_tariff({"base_rate": 0, "rate_count": "0"}).errors,
        validate_tariff({"base_rate": 0.3, "rate_count": "9"}).errors,
        validate_bill({"base_rate_name": ""}, []).errors,
        validate_bill({"base_rate_name": "night"}, [NIGHT]).errors,
        validate_rates([{**NIGHT, "end": "23:00"}], "Day").errors,
        validate_rates([{**NIGHT, "name": ""}], "Day").errors,
        validate_rates([NIGHT] * 6, "Day").errors,
        validate_change_date(date(2031, 6, 1), date(2031, 6, 15)).errors,
        validate_hot_water({"immersion_ready_times": ["x"]}, CTX).errors,
        validate_hot_water({"alt_heat_enabled": True, "alt_heat_label": ""}, CTX).errors,
        validate_hot_water({"alt_heat_enabled": True, "alt_heat_label": "x" * 40}, CTX).errors,
        missing_wiring({}),
    ]
    return {_key(errors) for errors in results}


def test_every_error_a_validator_returns_is_listed():
    assert _produced() <= set(ERROR_KEYS)


def test_every_listed_error_is_returned_by_a_validator():
    assert set(ERROR_KEYS) == _produced()
