"""The old module paths re-export lib/ev, so importers that were not moved keep working."""

import pytest

from custom_components.givenergy_inverter_manager import lib
from custom_components.givenergy_inverter_manager.core import (
    ev_base_rate,
    ev_session,
)
from custom_components.givenergy_inverter_manager.discovery import ev_charger

_OLD_PATHS = [ev_base_rate, ev_session, ev_charger]


@pytest.mark.parametrize("module", _OLD_PATHS, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_every_public_name_is_the_lib_object(module):
    assert module.__all__
    assert all(getattr(module, n) is getattr(lib.ev, n) for n in module.__all__)
