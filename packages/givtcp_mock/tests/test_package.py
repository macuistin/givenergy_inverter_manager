"""The package on its own: no Home Assistant, data files present, command line works."""

from __future__ import annotations

import json
import subprocess
import sys

import givtcp_mock
from givtcp_mock import systems


def test_imports_without_home_assistant() -> None:
    code = (
        "import sys; sys.modules['homeassistant'] = None; "
        "import givtcp_mock, givtcp_mock.systems"
    )
    subprocess.run([sys.executable, "-I", "-c", code], check=True)


def test_fixture_data_is_installed() -> None:
    names = systems.names()
    assert "hybrid_gen3_two_batteries_3_6_3" in names
    assert "ems_3_6_3" in names


def test_states_have_state_and_attributes() -> None:
    states = systems.states("hybrid_gen3_two_batteries_3_6_3")
    assert states
    assert all(hasattr(value, "state") and hasattr(value, "attributes") for value in states.values())


def test_describe_lists_the_write_services() -> None:
    described = givtcp_mock.describe("zz9999z999")
    assert described["serial"] == "zz9999z999"
    assert "number.set_value" in described["write_services"]


def test_command_line_prints_json() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "givtcp_mock", "zz9999z999"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert json.loads(out)["serial"] == "zz9999z999"
