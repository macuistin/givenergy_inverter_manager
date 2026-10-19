"""The old module paths re-export lib/givtcp."""

import pytest

from custom_components.givenergy_inverter_manager import lib
from custom_components.givenergy_inverter_manager.core import (
    battery_pause,
    inverter_values,
    system_types,
)

OWNERS = {
    battery_pause: lib.givtcp.pause,
    inverter_values: lib.givtcp.values,
    system_types: lib.givtcp.system,
}


@pytest.mark.parametrize("module", list(OWNERS), ids=lambda m: m.__name__)
def test_every_public_name_is_the_lib_object(module):
    assert module.__all__
    assert all(getattr(module, n) is getattr(OWNERS[module], n) for n in module.__all__)
