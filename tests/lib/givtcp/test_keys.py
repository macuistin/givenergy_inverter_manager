"""The keys lib/givtcp reads are the integration's own stored option keys."""

import pytest

from custom_components.givenergy_inverter_manager import conf
from custom_components.givenergy_inverter_manager.lib.givtcp import keys

NAMES = sorted(name for name in vars(keys) if name.startswith("KEY_"))


def test_there_are_keys_to_check():
    assert len(NAMES) == 12


@pytest.mark.parametrize("name", NAMES)
def test_each_key_has_the_value_of_the_matching_option_key(name):
    assert getattr(keys, name) == getattr(conf, name.replace("KEY_", "CONF_", 1))
