"""`const.py` re-exports names, and mypy strict only follows them through `__all__`."""

from __future__ import annotations

import ast

from tests.helpers import PKG


def _public_names() -> set[str]:
    names: set[str] = set()
    for node in ast.parse((PKG / "const.py").read_text()).body:
        if isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return {n for n in names if not n.startswith("_")}


def _exported() -> list[str]:
    for node in ast.parse((PKG / "const.py").read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("const.py has no __all__")


def test_all_lists_every_public_name() -> None:
    exported = _exported()
    assert len(exported) == len(set(exported))
    assert set(exported) == _public_names()
