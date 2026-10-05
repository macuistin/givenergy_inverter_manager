"""Serialise engine inputs and the CoordinatorData snapshot for characterisation tests.

The golden file tests/core/golden_engine_snapshots.json holds, per case, the keyword
arguments of one build_coordinator_data call and the resulting CoordinatorData. Inputs are
stored as the fields that differ from the dataclass defaults. Outputs are stored as the
fields that differ from a freshly built CoordinatorData, which is pinned separately.
"""

from __future__ import annotations

import dataclasses
import enum
import importlib
from datetime import date, datetime
from typing import Any


def encode(obj: Any) -> Any:
    """Turn engine inputs into JSON-friendly data that decode() can rebuild."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {"__dc__": f"{type(obj).__module__}:{type(obj).__qualname__}", "f": _changed(obj)}
    if isinstance(obj, enum.Enum):
        return {"__enum__": f"{type(obj).__module__}:{type(obj).__qualname__}", "v": obj.value}
    if isinstance(obj, datetime):
        return {"__dt__": obj.isoformat()}
    if isinstance(obj, date):
        return {"__date__": obj.isoformat()}
    if isinstance(obj, tuple):
        return {"__tuple__": [encode(v) for v in obj]}
    if isinstance(obj, list):
        return [encode(v) for v in obj]
    if isinstance(obj, dict):
        return {"__dict__": [[encode(k), encode(v)] for k, v in obj.items()]}
    return obj


def _changed(obj: Any) -> dict[str, Any]:
    changed = {}
    for f in dataclasses.fields(obj):
        if not f.init:
            continue
        value = getattr(obj, f.name)
        if f.default is not dataclasses.MISSING and value == f.default:
            continue
        if f.default_factory is not dataclasses.MISSING and value == f.default_factory():
            continue
        changed[f.name] = encode(value)
    return changed


def decode(data: Any) -> Any:
    if isinstance(data, list):
        return [decode(v) for v in data]
    if not isinstance(data, dict):
        return data
    if "__dc__" in data:
        cls = _resolve(data["__dc__"])
        return cls(**{k: decode(v) for k, v in data["f"].items()})
    if "__enum__" in data:
        return _resolve(data["__enum__"])(data["v"])
    if "__dt__" in data:
        return datetime.fromisoformat(data["__dt__"])
    if "__date__" in data:
        return date.fromisoformat(data["__date__"])
    if "__tuple__" in data:
        return tuple(decode(v) for v in data["__tuple__"])
    if "__dict__" in data:
        return {decode(k): decode(v) for k, v in data["__dict__"]}
    raise ValueError(f"unexpected encoded value: {data!r}")


def _resolve(path: str) -> Any:
    module, _, name = path.partition(":")
    target: Any = importlib.import_module(module)
    for part in name.split("."):
        target = getattr(target, part)
    return target


def snapshot(obj: Any) -> Any:
    """Plain-data view of a CoordinatorData (slots object or slots dataclass) and its members."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: snapshot(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if hasattr(type(obj), "__slots__") and not isinstance(obj, (str, bytes)):
        return {name: snapshot(getattr(obj, name)) for name in sorted(type(obj).__slots__)}
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        # BatteryStats dates come from the wall clock, so only whether one is set is pinned.
        return "<date>"
    if isinstance(obj, (list, tuple)):
        return [snapshot(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): snapshot(v) for k, v in obj.items()}
    return obj


def diff(value: Any, base: Any) -> Any:
    """The parts of value that differ from base, recursing through dicts."""
    if isinstance(value, dict) and isinstance(base, dict):
        return {k: diff(v, base.get(k)) for k, v in value.items() if v != base.get(k)}
    return value
