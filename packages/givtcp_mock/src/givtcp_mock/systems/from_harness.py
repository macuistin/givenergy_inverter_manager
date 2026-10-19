"""Builds the harness fixtures from GivTCP's own test results.

GivTCP's repository has a test harness that runs its real code against eight device models, each
served from a real, serial-redacted wire capture, and records the Home Assistant entities GivTCP
creates on the first read (`tests/golden/<model>.json`, key `read` / `discovery topics`). The
entity ids in the files written here are those, so they are what GivTCP really publishes for that
kind of device, not a reading of its documentation.

Run it against a GivTCP checkout:

    python -m givtcp_mock.systems.from_harness /path/to/giv_tcp/tests/golden

What the files do not hold:

- States. Every entity reads `unknown`, apart from the device type, the serial and the version.
- Battery modules and the units behind a Gateway. GivTCP only creates those after a second read,
  so the first read's entities, which the harness records, do not include them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
GIVTCP_VERSION = "3.6.4"
PREFIX = "givtcp"

# GivTCP harness model -> (what the model is called here, what the system should be read as)
MODELS: dict[str, tuple[str, dict[str, Any]]] = {
    "hybrid_gen1": ("Hybrid Gen 1", {"kind": "hybrid"}),
    "hybrid_gen2": ("Hybrid Gen 2", {"kind": "hybrid"}),
    "hybrid_hv_gen3": ("Hybrid HV Gen 3", {"kind": "hybrid"}),
    "hybrid_3ph": ("three-phase hybrid", {"kind": "three_phase"}),
    "ac": ("AC-coupled inverter", {"kind": "ac_coupled"}),
    "all_in_one": ("All-In-One", {"kind": "all_in_one"}),
    "gateway": ("Gateway", {"kind": "gateway"}),
    "ems": ("EMS", {"kind": "ems"}),
}

SOURCE = (
    "Entity ids GivTCP 3.6.4 creates on its first read of a real, serial-redacted wire capture, "
    "taken from GivTCP's own test results (tests/golden). The serial is the capture's redacted "
    "one. Every state is unknown except the device type, the serial and the version. Battery "
    "modules and the units behind a Gateway are not in it, because GivTCP creates those after a "
    "second read."
)


def _find(tree: object, key: str) -> str | None:
    if isinstance(tree, dict):
        for name, value in tree.items():
            if name == key and isinstance(value, str):
                return value
            found = _find(value, key)
            if found:
                return found
    return None


def entity_of(topic: str) -> str:
    """`homeassistant/sensor/GivEnergy/AB1234G567_Item/config` as `sensor.givtcp_ab1234g567_item`."""
    parts = topic.split("/")
    return f"{parts[1]}.{PREFIX}_{parts[3]}".lower()


def build_one(model: str, golden: dict[str, Any]) -> dict[str, Any]:
    label, expected = MODELS[model]
    read = golden["read"]
    states = {entity_of(t): {"state": "unknown"} for t in read["discovery topics"]}
    output = read["cycle 1 output"]
    serial = _find(output, "Invertor_Serial_Number")
    kind = _find(output, "Invertor_Type")
    if serial and kind:
        prefix = f"{PREFIX}_{serial.lower()}"
        states[f"sensor.{prefix}_invertor_type"] = {"state": kind}
        states[f"sensor.{prefix}_invertor_serial_number"] = {"state": serial}
        states[f"sensor.{prefix}_givtcp_version"] = {"state": GIVTCP_VERSION}
    caps = golden["detect"]["capabilities"]
    return {
        "description": f"{label}, as GivTCP {GIVTCP_VERSION} publishes it from a real capture.",
        "provenance": "harness",
        "givtcp_version": GIVTCP_VERSION,
        "invertor_type": kind,
        "capabilities": caps,
        "source": SOURCE,
        "expected": {
            **expected,
            "controller": serial.upper() if serial else None,
            "ask": False,
            "modules": None,
        },
        "states": dict(sorted(states.items())),
    }


def build(golden_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        f"harness_{model}": build_one(model, json.loads((golden_dir / f"{model}.json").read_text()))
        for model in MODELS
    }


if __name__ == "__main__":
    out = build(Path(sys.argv[1]))
    for name, fixture in out.items():
        (HERE / f"{name}.json").write_text(json.dumps(fixture, indent=1) + "\n")
        print(name, len(fixture["states"]), "entities")
