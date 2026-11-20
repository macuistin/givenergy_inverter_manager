"""No module of the integration grows past the size it has, and no new one starts large.

Epic #665 splits the biggest files. This is a ratchet: a file over the limit is listed with the
line count it has now, and may not grow. When a split makes a file smaller, lower its cap. When it
falls under the limit, remove its row, which the last test requires. A new file over the limit fails until it is split.
"""

from __future__ import annotations

from tests.helpers import PKG

LIMIT = 600

# The files over the limit today, with the most lines each may have.
CAPS = {
    "coordinator.py": 2545,
    "core/engine.py": 2177,
    "dashboard/views.py": 2061,
    "core/rules.py": 1443,
    "accumulation.py": 1017,
    "sensor_values.py": 848,
    "services.py": 780,
    "wizard/options_flow.py": 721,
    "dashboard/templates.py": 689,
    "repairs.py": 601,
}


def _line_counts() -> dict[str, int]:
    counts = {}
    for path in PKG.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        counts[path.relative_to(PKG).as_posix()] = len(path.read_text(encoding="utf-8").splitlines())
    return counts


def test_a_new_module_does_not_start_over_the_limit():
    big = {name for name, lines in _line_counts().items() if lines > LIMIT}

    assert sorted(big - set(CAPS)) == []


def test_a_large_module_does_not_grow():
    counts = _line_counts()
    grown = {name: counts[name] for name, cap in CAPS.items() if counts.get(name, 0) > cap}

    assert grown == {}


def test_a_module_that_fell_under_the_limit_is_removed_from_the_list():
    counts = _line_counts()
    stale = [name for name, cap in CAPS.items() if counts.get(name, 0) <= LIMIT]

    assert stale == []
