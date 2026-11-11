# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""lib/tariff prices energy from typed fields alone."""

from datetime import datetime, time, timezone

from custom_components.givenergy_inverter_manager.lib.tariff import (
    RatePeriod,
    TariffConfig,
    money,
)


def _tariff() -> TariffConfig:
    return TariffConfig(
        rate_periods=[
            RatePeriod("Night", 0.16, time(23, 0), time(8, 0)),
            RatePeriod("Boost", 0.09, time(2, 0), time(4, 0)),
        ],
        base_rate=0.33,
        base_rate_name="Day",
        export_rate=0.19,
        standing_charge=0.8,
        pso_levy=1.5,
        vat_rate=9.0,
        discount_rate=5.5,
        bill_start_day=1,
    )


def _at(hour: int) -> datetime:
    return datetime(2026, 6, 15, hour, 0, tzinfo=timezone.utc)


def test_the_cheapest_active_period_wins_inside_an_overnight_period():
    assert _tariff().get_current_rate(_at(3)).name == "Boost"
    assert _tariff().get_current_rate(_at(23)).name == "Night"
    assert _tariff().get_current_rate(_at(12)).name == "Day"


def test_money_rounds_halves_upward_to_cents():
    assert money(0.125) == 0.13
    assert money(2.675) == 2.68

