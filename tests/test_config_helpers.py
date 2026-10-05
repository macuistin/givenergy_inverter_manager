"""effective_config: saved options over setup data, with None meaning unset."""

from types import SimpleNamespace

from custom_components.givenergy_inverter_manager.config_helpers import effective_config


def _entry(data: dict, options: dict) -> SimpleNamespace:
    return SimpleNamespace(data=data, options=options)


def test_options_win_over_data():
    entry = _entry({"export_rate": 0.1, "vat_rate": 9}, {"export_rate": 0.2})
    assert effective_config(entry) == {"export_rate": 0.2, "vat_rate": 9}


def test_falsy_option_is_a_real_choice():
    entry = _entry({"cheap_rate_floor_soc": 40, "forecast_entity": "sensor.a"},
                   {"cheap_rate_floor_soc": 0, "forecast_entity": ""})
    assert effective_config(entry) == {"cheap_rate_floor_soc": 0, "forecast_entity": ""}


def test_none_option_does_not_hide_the_setup_value():
    entry = _entry({"export_rate": 0.1}, {"export_rate": None})
    assert effective_config(entry) == {"export_rate": 0.1}


def test_none_setup_value_is_left_out():
    assert effective_config(_entry({"export_rate": None}, {})) == {}


def test_does_not_change_the_entry():
    data, options = {"a": 1}, {"b": 2}
    effective_config(_entry(data, options))
    assert data == {"a": 1}
    assert options == {"b": 2}
