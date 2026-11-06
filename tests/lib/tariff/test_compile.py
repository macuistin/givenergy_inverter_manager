"""The options written as a definition bill the same as the existing bill maths."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from custom_components.givenergy_inverter_manager.lib.tariff import (
    BillInputs,
    DefinitionError,
    RatePeriod,
    price_bill,
)
from custom_components.givenergy_inverter_manager.lib.tariff.billing import money
from custom_components.givenergy_inverter_manager.lib.tariff.compile import (
    Locale,
    definition_from_config,
)
from custom_components.givenergy_inverter_manager.lib.tariff.reprice import import_by_band
from tests.lib.tariff.test_bands import history
from tests.lib.tariff.test_reprice import _tariff

LOCALE = Locale("EUR", "IE", "Europe/Dublin", date(2026, 1, 1))


def compiled(**changes):  # type: ignore[no-untyped-def]
    return definition_from_config(_tariff(**changes), LOCALE)


@pytest.mark.parametrize("days", [1, 15, 30, 31])
@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"discount_rate": 0.0},
        {"vat_rate": 0.0, "pso_levy": 0.0},
        {"standing_charge": 0.0, "export_rate": 0.0},
        {"base_rate": 0.3334, "discount_rate": 3.25},
        {"rate_periods": []},
    ],
)
def test_bill_matches_calculate_bill(changes: dict, days: int) -> None:
    tariff = _tariff(**changes)
    kwh = {"Day": 67.0, "Night": 619.0}
    if tariff.rate_periods:
        kwh["Nightboost"] = 257.0
    rates = {p.name: p.rate for p in tariff.rate_periods} | {tariff.base_rate_name: tariff.base_rate}
    cost = sum(money(v * rates[k]) for k, v in kwh.items() if k in rates)
    export = 47.0
    old = tariff.calculate_bill(cost, days, 31, tariff.calculate_export_earnings(export))
    inputs = BillInputs(
        days,
        31,
        {k: Decimal(repr(v)) for k, v in kwh.items() if k in rates},
        Decimal(repr(export)),
    )
    assert price_bill(compiled(**changes), inputs).total == Decimal(repr(old.total))


def test_cheapest_rate_wins_through_priorities() -> None:
    zones = compiled().import_prices.zones
    by_name = {z.name: z for z in zones}
    assert by_name["Night"].priority < by_name["Boost"].priority


def test_equal_rates_pick_the_first_listed_like_the_old_model() -> None:
    periods = [
        RatePeriod("A", 0.2, time(0, 0), time(12, 0)),
        RatePeriod("B", 0.2, time(6, 0), time(18, 0)),
    ]
    zones = compiled(rate_periods=periods).import_prices.zones
    by_name = {z.name: z.priority for z in zones}
    assert by_name["A"] > by_name["B"]  # min() keeps the first, so A outranks B


def test_history_bands_match_the_old_bands() -> None:
    from custom_components.givenergy_inverter_manager.lib.tariff.bands import (
        import_by_band as new_bands,
    )

    days = history()
    new = new_bands(days, compiled())
    old = import_by_band(days, _tariff())
    assert set(new) == set(old)
    for band, kwh in old.items():
        assert abs(float(new[band]) - kwh) < 1e-5


def test_a_start_day_a_month_cannot_name_is_refused() -> None:
    with pytest.raises(DefinitionError, match="1 to 28"):
        compiled(bill_start_day=31)


def test_bad_identity_is_refused_by_the_same_validator() -> None:
    with pytest.raises(DefinitionError, match="country"):
        definition_from_config(_tariff(), Locale("EUR", "Ireland", "Europe/Dublin", date(2026, 1, 1)))
