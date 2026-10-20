"""GivTCP system fixtures: entity ids and states of one GivTCP install, as a dict of states."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

HERE = Path(__file__).parent


def names() -> list[str]:
    return sorted(p.stem for p in HERE.glob("*.json"))


def raw(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((HERE / f"{name}.json").read_text())
    return data


def states(name: str) -> dict[str, Any]:
    """The fixture as {entity_id: object with .state}, the shape the discovery code takes."""
    return {
        entity_id: SimpleNamespace(state=value["state"], attributes=value.get("attributes", {}))
        for entity_id, value in raw(name)["states"].items()
    }
