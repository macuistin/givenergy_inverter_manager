"""The cost of one kWh of heat from the alternative water heating, for each unit."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.const import (
    ALT_HEAT_UNIT_KWH_HEAT,
    ALT_HEAT_UNIT_LITRE,
    OIL_BOILER_EFFICIENCY_PCT,
    OIL_KWH_PER_LITRE,
)
from custom_components.givenergy_inverter_manager.core.alt_heat_cost import (
    heat_cost_per_kwh,
    litre_heat_cost_per_kwh,
)


class TestLitreCost:
    def test_it_is_the_price_over_the_heat_a_litre_gives(self):
        heat_per_litre = OIL_KWH_PER_LITRE * OIL_BOILER_EFFICIENCY_PCT / 100
        assert litre_heat_cost_per_kwh(1.00) == pytest.approx(1.00 / heat_per_litre)

    def test_the_assumptions_are_a_typical_boiler_and_kerosene(self):
        assert OIL_KWH_PER_LITRE == pytest.approx(10.35)
        assert OIL_BOILER_EFFICIENCY_PCT == 85

    def test_a_dearer_litre_costs_more_per_kwh(self):
        assert litre_heat_cost_per_kwh(1.20) > litre_heat_cost_per_kwh(0.90)

    def test_a_negative_price_is_refused(self):
        with pytest.raises(ValueError, match="oil price"):
            litre_heat_cost_per_kwh(-0.1)

    def test_the_price_of_the_live_install_is_worked_out_to_the_penny(self):
        """1.37 a litre is 0.1557 a kWh of heat, the figure the oil advice always gave."""
        assert litre_heat_cost_per_kwh(1.37) == pytest.approx(0.15572, abs=1e-5)


class TestHeatCost:
    @pytest.mark.parametrize(
        ("unit", "cost", "expected"),
        [
            (ALT_HEAT_UNIT_LITRE, 1.37, 1.37 / (10.35 * 0.85)),
            (ALT_HEAT_UNIT_LITRE, 0.001, 0.001 / (10.35 * 0.85)),
            (ALT_HEAT_UNIT_KWH_HEAT, 0.08, 0.08),
            (ALT_HEAT_UNIT_KWH_HEAT, 5, 5),
            (ALT_HEAT_UNIT_KWH_HEAT, 0.0, 0.0),
        ],
    )
    def test_each_unit_gives_a_cost_per_kwh_of_heat(self, unit, cost, expected):
        assert heat_cost_per_kwh(unit, cost) == pytest.approx(expected)

    def test_a_kwh_of_heat_is_not_converted_again(self):
        """The efficiency is already in it, so a boiler's 85% is not applied twice."""
        assert heat_cost_per_kwh(ALT_HEAT_UNIT_KWH_HEAT, 0.10) == 0.10

    @pytest.mark.parametrize("unit", [None, "", "gallon", 3])
    def test_an_unknown_unit_reads_as_a_litre(self, unit):
        assert heat_cost_per_kwh(unit, 1.0) == pytest.approx(litre_heat_cost_per_kwh(1.0))

    @pytest.mark.parametrize("unit", [ALT_HEAT_UNIT_LITRE, ALT_HEAT_UNIT_KWH_HEAT])
    def test_a_negative_cost_is_refused(self, unit):
        with pytest.raises(ValueError, match="negative"):
            heat_cost_per_kwh(unit, -0.01)
