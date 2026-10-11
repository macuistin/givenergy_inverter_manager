"""The one-time move from the oil price options to alternative heating.

The live install saved an oil price of 1.37 a litre. The conversion has to carry that number
over exactly, give it the label Oil and the unit litre, and drop the old keys. Anything else is
left alone: an install without an oil price, one that already has the new keys, and one that
has both.
"""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.const import (
    LEGACY_OIL_PRICE_ENTITY,
    LEGACY_OIL_PRICE_PER_LITRE,
)
from custom_components.givenergy_inverter_manager.core.alt_heat_conversion import (
    converted_alt_heat,
)

OLD_KEYS = {"oil_price_per_litre", "oil_price_entity"}
WIRING = {"inverter_serial": "ab1", "base_rate": 0.30, "immersion_switch_entity": "switch.heater"}


def convert(data=None, options=None):
    return converted_alt_heat({**WIRING, **(data or {})}, options or {})


def converted_options(data=None, options=None):
    result = convert(data, options)
    assert result is not None, "nothing was converted"
    return result[1]


class TestAnOilInstallIsConverted:
    def test_the_price_of_the_live_install_carries_over_exactly(self):
        options = converted_options(options={"oil_price_per_litre": 1.37})
        assert options["alt_heat_cost"] == 1.37

    def test_it_is_switched_on_with_the_label_oil_and_the_unit_litre(self):
        options = converted_options(options={"oil_price_per_litre": 1.37})
        assert options["alt_heat_enabled"] is True
        assert options["alt_heat_label"] == "Oil"
        assert options["alt_heat_cost_unit"] == "litre"

    def test_the_old_keys_are_removed(self):
        options = converted_options(
            options={"oil_price_per_litre": 1.37, "oil_price_entity": "sensor.oil"}
        )
        assert OLD_KEYS.isdisjoint(options)

    def test_the_cost_sensor_carries_over(self):
        options = converted_options(options={"oil_price_entity": "sensor.oil_price"})
        assert options["alt_heat_cost_entity"] == "sensor.oil_price"
        assert "alt_heat_cost" not in options

    def test_a_price_and_a_sensor_both_carry_over(self):
        options = converted_options(
            options={"oil_price_per_litre": 1.37, "oil_price_entity": "sensor.oil_price"}
        )
        assert options["alt_heat_cost"] == 1.37
        assert options["alt_heat_cost_entity"] == "sensor.oil_price"

    def test_a_cleared_sensor_is_not_carried(self):
        """The old form saved an empty string for a cleared sensor."""
        options = converted_options(options={"oil_price_per_litre": 1.37, "oil_price_entity": ""})
        assert "alt_heat_cost_entity" not in options
        assert options["alt_heat_cost"] == 1.37

    def test_a_zero_price_with_a_sensor_carries_only_the_sensor(self):
        options = converted_options(
            options={"oil_price_per_litre": 0.0, "oil_price_entity": "sensor.oil_price"}
        )
        assert "alt_heat_cost" not in options
        assert options["alt_heat_cost_entity"] == "sensor.oil_price"

    @pytest.mark.parametrize("price", ["1.37", 1.37, 1])
    def test_a_price_saved_as_text_or_a_whole_number_becomes_a_number(self, price):
        options = converted_options(options={"oil_price_per_litre": price})
        assert options["alt_heat_cost"] == float(price)
        assert isinstance(options["alt_heat_cost"], float)

    def test_the_other_options_are_kept(self):
        options = converted_options(
            options={"oil_price_per_litre": 1.37, "dry_run": True, "vat_rate": 9.0}
        )
        assert options["dry_run"] is True
        assert options["vat_rate"] == 9.0

    def test_the_setup_data_is_kept_apart_from_the_old_keys(self):
        data, _options = convert(options={"oil_price_per_litre": 1.37})
        assert data == WIRING

    def test_old_keys_in_the_setup_data_are_converted_and_removed_too(self):
        data, options = convert(data={"oil_price_per_litre": 1.37})
        assert OLD_KEYS.isdisjoint(data)
        assert options["alt_heat_cost"] == 1.37

    def test_options_win_over_the_setup_data(self):
        _data, options = convert(
            data={"oil_price_per_litre": 0.50}, options={"oil_price_per_litre": 1.37}
        )
        assert options["alt_heat_cost"] == 1.37

    def test_the_input_is_not_changed(self):
        options = {"oil_price_per_litre": 1.37}
        convert(options=options)
        assert options == {"oil_price_per_litre": 1.37}

    def test_the_legacy_keys_are_the_ones_the_old_form_wrote(self):
        assert LEGACY_OIL_PRICE_PER_LITRE == "oil_price_per_litre"
        assert LEGACY_OIL_PRICE_ENTITY == "oil_price_entity"


class TestAnInstallWithoutOilIsLeftAlone:
    def test_nothing_set(self):
        assert convert() is None

    def test_other_options_only(self):
        assert convert(options={"dry_run": True, "vat_rate": 9.0}) is None

    @pytest.mark.parametrize("empty", [None, "", 0, 0.0])
    def test_an_empty_oil_price_and_an_empty_sensor(self, empty):
        """The old form saved an empty sensor string for every install that saved options."""
        options = {"oil_price_per_litre": empty, "oil_price_entity": ""}
        assert convert(options=options) is None

    def test_an_empty_oil_sensor_alone(self):
        assert convert(options={"oil_price_entity": ""}) is None

    @pytest.mark.parametrize("junk", ["cheap", "-1", -1.0, [], {}])
    def test_a_price_that_is_not_a_price(self, junk):
        assert convert(options={"oil_price_per_litre": junk}) is None


class TestAnAlreadyConvertedInstallIsNotRewritten:
    NEW = {
        "alt_heat_enabled": True,
        "alt_heat_label": "Gas",
        "alt_heat_cost_unit": "kwh_heat",
        "alt_heat_cost": 0.08,
    }

    def test_the_new_keys_alone(self):
        assert convert(options=dict(self.NEW)) is None

    def test_switched_off_is_still_saved(self):
        assert convert(options={"alt_heat_enabled": False}) is None

    def test_both_the_new_and_the_old_keys_present(self):
        options = {**self.NEW, "oil_price_per_litre": 1.37}
        assert convert(options=options) is None

    def test_the_new_switch_in_the_setup_data_counts_as_saved(self):
        assert convert(data={"alt_heat_enabled": False}, options={"oil_price_per_litre": 1.37}) is None

    def test_a_switch_saved_as_none_counts_as_not_saved(self):
        options = {"alt_heat_enabled": None, "oil_price_per_litre": 1.37}
        assert convert(options=options) is not None


class TestRunningItAgain:
    def test_the_second_run_finds_nothing_to_do(self):
        data, options = convert(options={"oil_price_per_litre": 1.37, "oil_price_entity": "s.o"})
        assert converted_alt_heat(data, options) is None

    def test_a_third_run_changes_nothing_either(self):
        data, options = convert(options={"oil_price_per_litre": 1.37})
        for _ in range(3):
            assert converted_alt_heat(data, options) is None
