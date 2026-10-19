"""The old module paths re-export lib/givtcp."""

import pytest

from custom_components.givenergy_inverter_manager import lib
from custom_components.givenergy_inverter_manager.core import (
    battery_pause,
    feed_freshness,
    inverter_values,
    system_types,
)
from custom_components.givenergy_inverter_manager.inverter.givtcp import (
    battery_pause as pause_modes,
)
from custom_components.givenergy_inverter_manager.inverter.givtcp import (
    constants,
    discovery,
    reader,
    sequence,
    writer,
)

OWNERS = {
    battery_pause: lib.givtcp.pause,
    inverter_values: lib.givtcp.values,
    system_types: lib.givtcp.system,
    feed_freshness: lib.givtcp.freshness,
    pause_modes: lib.givtcp.pause_modes,
    constants: lib.givtcp.defaults,
    discovery: lib.givtcp.discovery,
    reader: lib.givtcp.reader,
    sequence: lib.givtcp.sequence,
    writer: lib.givtcp.writer,
}


@pytest.mark.parametrize("module", list(OWNERS), ids=lambda m: m.__name__)
def test_every_public_name_is_the_lib_object(module):
    assert module.__all__
    assert all(getattr(module, n) is getattr(OWNERS[module], n) for n in module.__all__)
