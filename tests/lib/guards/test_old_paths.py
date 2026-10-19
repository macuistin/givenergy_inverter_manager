"""The old module path re-exports lib/guards."""

from custom_components.givenergy_inverter_manager import lib
from custom_components.givenergy_inverter_manager.core import counter_guard, write_confirmation


def test_every_public_name_is_the_lib_object():
    assert counter_guard.__all__
    assert all(
        getattr(counter_guard, n) is getattr(lib.guards.counter, n) for n in counter_guard.__all__
    )


def test_write_confirmation_old_path_is_the_lib_object():
    assert write_confirmation.__all__
    assert all(
        getattr(write_confirmation, n) is getattr(lib.guards, n) for n in write_confirmation.__all__
    )
