"""The old module paths re-export lib/guards."""

import pytest

from custom_components.givenergy_inverter_manager import lib
from custom_components.givenergy_inverter_manager.core import counter_guard, feed_freshness


@pytest.mark.parametrize("module", [counter_guard, feed_freshness], ids=lambda m: m.__name__)
def test_every_public_name_is_the_lib_object(module):
    owner = lib.guards.counter if module is counter_guard else lib.guards.freshness

    assert module.__all__
    assert all(getattr(module, n) is getattr(owner, n) for n in module.__all__)
