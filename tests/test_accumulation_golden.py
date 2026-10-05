"""Pins the midnight reset and the storage round trip of AccumulationStore.

golden_accumulation.json was generated from accumulation.py before on_midnight and
_deserialize were split into steps. "midnight" holds 110 random stored states, the time of
the reset and the bill start day, with the exact state after on_midnight (Mondays, bill days
and 1 January are frequent). "odd" holds 50 damaged payloads with the state they load into.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.givenergy_inverter_manager.accumulation import (
    AccumulationStore,
    _deserialize,
    _serialize,
)

_GOLDEN = json.loads((Path(__file__).parent / "golden_accumulation.json").read_text())


@pytest.mark.parametrize("case", _GOLDEN["midnight"], ids=range(len(_GOLDEN["midnight"])))
def test_on_midnight_is_unchanged(case):
    store = AccumulationStore.__new__(AccumulationStore)
    store._store = MagicMock()
    store._bill_start_day = case["bill_day"]
    store.state = _deserialize(case["in"])
    store.on_midnight(datetime.fromisoformat(case["now"]))
    assert _serialize(store.state) == case["out"]


@pytest.mark.parametrize("case", _GOLDEN["odd"], ids=range(len(_GOLDEN["odd"])))
def test_damaged_payload_loads_as_before(case):
    expected = case["out"]
    if "error" in expected:
        with pytest.raises(Exception) as raised:
            _deserialize(case["in"])
        assert type(raised.value).__name__ == expected["error"]
    else:
        assert _serialize(_deserialize(case["in"])) == expected
