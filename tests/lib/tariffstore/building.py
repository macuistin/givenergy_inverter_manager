"""Build the indexes of a small store on disk, as the tariff store's own build step does.

Written here, not copied: the store's build script is not part of the library.
"""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.givenergy_inverter_manager.lib.tariffstore import index as idx
from custom_components.givenergy_inverter_manager.lib.tariffstore import layout


def build_store(tariffs: Path) -> None:
    """Write every index of a tariffs/ folder from its tariff files."""
    countries = {}
    for folder in sorted(p for p in tariffs.iterdir() if p.is_dir()):
        block = idx.block_of(json.loads((folder / "index.json").read_text(encoding="utf-8")))
        block.pop("schema", None)
        files = {
            p.relative_to(folder).as_posix(): json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(folder.rglob("*.json"))
            if p.name != "index.json"
        }
        code = folder.name.upper()
        assert idx.problems(code, block, files) == []
        countries[code] = idx.country_index(block, files)
        (folder / "index.json").write_text(layout.dumps_index(countries[code]), encoding="utf-8")
    unavailable = json.loads((tariffs / "unavailable.json").read_text(encoding="utf-8"))
    root = idx.root_index(countries, unavailable)
    (tariffs / "index.json").write_text(layout.dumps_root(root), encoding="utf-8")
