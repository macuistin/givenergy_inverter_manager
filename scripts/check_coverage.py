#!/usr/bin/env python3
"""Fail unless every module of the integration has more than 95% test coverage.

The quality scale rule `test-coverage` asks for it per module, over both test suites. Each suite
writes its own data file (`COVERAGE_FILE=coverage-unit`, `coverage-e2e`). This script combines
the files it is given and reports every module at or below the floor.

Usage:
    python scripts/check_coverage.py coverage-unit coverage-e2e
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

FLOOR = 95.0


def combined_report(data_files: list[str], workdir: Path) -> dict:
    """The coverage JSON report of *data_files* combined."""
    target = workdir / ".coverage"
    subprocess.run(
        [sys.executable, "-m", "coverage", "combine", "--keep", f"--data-file={target}"]
        + data_files,
        check=True,
    )
    out = workdir / "coverage.json"
    subprocess.run(
        [sys.executable, "-m", "coverage", "json", f"--data-file={target}", "-o", str(out)],
        check=True,
    )
    return json.loads(out.read_text())


def below_floor(report: dict) -> list[tuple[str, float]]:
    """The files whose coverage is not above the floor, worst first."""
    files = report["files"]
    low = [(name, f["summary"]["percent_covered"]) for name, f in files.items()]
    return sorted((item for item in low if item[1] <= FLOOR), key=lambda item: item[1])


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        report = combined_report(argv, Path(tmp))
    total = report["totals"]["percent_covered"]
    print(f"Combined coverage: {total:.1f}%")
    low = below_floor(report)
    for name, percent in low:
        print(f"  {percent:5.1f}%  {name}")
    if low:
        print(f"{len(low)} module(s) are not above {FLOOR:.0f}%.")
        return 1
    print(f"Every module is above {FLOOR:.0f}%.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
