"""Shadow tariff code can observe and never write to the inverter, the immersion or the EV.

A shadow tariff only re-prices measured usage (epic #569). Nothing it does may reach a write path.
Shadow modules are the files named `shadow*.py` in the integration. Two rules apply:

- A pure shadow module (under `core/` or `lib/`) must not reach a write path through any chain of
  imports. Home Assistant is allowed there as little as the inverter is.
- A shadow module that sits on the Home Assistant side (a sensor, the options form) may read the
  coordinator, so only its own imports and calls are checked: it must not import a write module
  and must not name a write method.

The write modules are the inverter package, the GivTCP adapter, the coordinator's write helpers, the
service actions, the immersion actuator and the optional devices. The write methods are the
`apply_` and `clear_` methods of the inverter interface, and `async_call`.

The shadow modules are core/shadow_tariffs.py, core/shadow_pricing.py, wizard/shadow_form.py and
shadow_sensor.py. The checks themselves are proved on a small tree built below.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.helpers import PKG

WRITE_MODULES = ("inverter", "coordinator", "services", "immersion_actuator", "optional_devices")
WRITE_LIBS = ("givtcp",)
EXTRA_WRITE_NAMES = frozenset({"async_call"})


def _module_name(root: Path, path: Path) -> tuple[str, ...]:
    parts = path.relative_to(root).with_suffix("").parts
    return parts[:-1] if parts[-1] == "__init__" else parts


def _imports(root: Path, path: Path) -> set[tuple[str, ...]]:
    """The modules inside *root* that *path* imports, anywhere in the file."""
    here = _module_name(root, path)
    package = here if path.name == "__init__.py" else here[:-1]
    found: set[tuple[str, ...]] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ImportFrom) or node.level == 0:
            continue
        base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
        module = (*base, *(node.module.split(".") if node.module else ()))
        names = [alias.name for alias in node.names]
        for candidate in [module, *((*module, name) for name in names)]:
            if (root / Path(*candidate)).with_suffix(".py").exists() or (
                root / Path(*candidate) / "__init__.py"
            ).exists():
                found.add(tuple(candidate))
    return found


def _is_write_module(module: tuple[str, ...]) -> bool:
    if module[0] in WRITE_MODULES:
        return True
    return module[0] == "lib" and len(module) > 1 and module[1] in WRITE_LIBS


def _file_of(root: Path, module: tuple[str, ...]) -> Path:
    plain = (root / Path(*module)).with_suffix(".py")
    return plain if plain.exists() else root / Path(*module) / "__init__.py"


def _reaches_a_write_module(root: Path, start: Path) -> list[str]:
    """The write module, if any, that *start* reaches, with the import chain that gets there."""
    seen = {_module_name(root, start)}
    queue = [(_module_name(root, start), [".".join(_module_name(root, start))])]
    while queue:
        module, chain = queue.pop(0)
        for target in sorted(_imports(root, _file_of(root, module))):
            if _is_write_module(target):
                return [*chain, ".".join(target)]
            if target not in seen:
                seen.add(target)
                queue.append((target, [*chain, ".".join(target)]))
    return []


def _write_method_names(root: Path) -> frozenset[str]:
    """The `apply_` and `clear_` methods of the inverter interface, plus `async_call`."""
    backend = root / "inverter" / "backend.py"
    names = {
        node.name
        for node in ast.walk(ast.parse(backend.read_text(encoding="utf-8")))
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
        and node.name.startswith(("apply_", "clear_"))
    }
    return frozenset(names) | EXTRA_WRITE_NAMES


def _names_used(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
    }


def shadow_violations(root: Path, write_names: frozenset[str]) -> list[str]:
    """What the shadow modules under *root* do that they must not."""
    problems: list[str] = []
    for path in sorted(root.rglob("shadow*.py")):
        rel = path.relative_to(root)
        if rel.parts[0] in ("core", "lib"):
            chain = _reaches_a_write_module(root, path)
            if chain:
                problems.append(f"{rel}: reaches a write module through {' -> '.join(chain)}")
            continue
        for target in sorted(_imports(root, path)):
            if _is_write_module(target):
                problems.append(f"{rel}: imports the write module {'.'.join(target)}")
        for name in sorted(_names_used(path) & write_names):
            problems.append(f"{rel}: uses the write method {name}")
    return problems


def test_no_shadow_module_can_reach_a_write_path() -> None:
    assert shadow_violations(PKG, _write_method_names(PKG)) == []


def test_the_write_methods_are_read_from_the_inverter_interface() -> None:
    names = _write_method_names(PKG)

    assert {"apply_charge_plan", "apply_floor_target", "clear_charge_slot", "async_call"} <= names
    assert "read" not in names


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_the_check_finds_a_pure_shadow_module_that_reaches_a_write_module(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "inverter/__init__.py": "",
            "inverter/backend.py": "async def apply_charge_plan(): ...\n",
            "core/__init__.py": "",
            "core/helper.py": "from ..inverter import backend\n",
            "core/shadow_price.py": "from . import helper\n",
        },
    )

    problems = shadow_violations(root, _write_method_names(root))

    assert problems == [
        "core/shadow_price.py: reaches a write module through "
        "core.shadow_price -> core.helper -> inverter"
    ]


def test_the_check_finds_a_lib_shadow_module_that_reaches_the_givtcp_adapter(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "inverter/__init__.py": "",
            "inverter/backend.py": "async def apply_charge_plan(): ...\n",
            "lib/__init__.py": "",
            "lib/givtcp/__init__.py": "",
            "lib/givtcp/writer.py": "",
            "lib/tariff/__init__.py": "",
            "lib/tariff/shadow_run.py": "from ..givtcp import writer\n",
        },
    )

    problems = shadow_violations(root, _write_method_names(root))

    assert problems == [
        "lib/tariff/shadow_run.py: reaches a write module through "
        "lib.tariff.shadow_run -> lib.givtcp"
    ]


def test_the_check_finds_a_sensor_side_module_that_imports_or_calls_a_write(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "inverter/__init__.py": "",
            "inverter/backend.py": "async def apply_charge_plan(): ...\n",
            "coordinator.py": "",
            "shadow_sensor.py": (
                "from .coordinator import Coordinator\n"
                "async def go(coordinator, hass):\n"
                "    await coordinator.backend.apply_charge_plan(None, None)\n"
                "    await hass.services.async_call('x', 'y')\n"
            ),
        },
    )

    problems = shadow_violations(root, _write_method_names(root))

    assert problems == [
        "shadow_sensor.py: imports the write module coordinator",
        "shadow_sensor.py: uses the write method apply_charge_plan",
        "shadow_sensor.py: uses the write method async_call",
    ]


def test_the_check_lets_a_shadow_module_that_only_reads_pass(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "inverter/__init__.py": "",
            "inverter/backend.py": "async def apply_charge_plan(): ...\n",
            "core/__init__.py": "",
            "core/shadow_price.py": "from datetime import date\n",
            "shadow_sensor.py": "def value(coordinator):\n    return coordinator.data.bill\n",
        },
    )

    assert shadow_violations(root, _write_method_names(root)) == []
