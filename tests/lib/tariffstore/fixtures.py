# Copied from the tariff store by scripts/copy_tariffstore.py. Do not edit here.
"""Made-up tariffs and a small store on disk, shared by the tests."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from custom_components.givenergy_inverter_manager.lib.tariffstore import layout

BILL = {"period": {"rule": "monthly", "start_day": "$input.bill_start_day"},
        "total": {"kind": "tax", "name": "VAT", "mode": "included", "percent": "$country.vat_percent",
                  "of": {"kind": "sum", "of": {"energy": {"kind": "energy_by_band", "round_bands": True},
                                               "standing": {"kind": "per_day"}}}}}
INPUTS = {"bill_start_day": {"type": "integer", "min": 1, "max": 28, "default": 1}}
SOURCE = {"id": "example-source", "url": "https://example.test/prices"}
META = {"country": "IE", "provider": "p", "tariff": "plan", "revision": 1}


def country(vat="9", code="IE") -> dict:
    return {"country": code, "currency": "EUR", "timezone": "Europe/Dublin", "vat_percent": vat,
            "bill": copy.deepcopy(BILL), "inputs": copy.deepcopy(INPUTS)}


def holidays(**regions) -> dict:
    """Public holidays for a country block: three days of 2026, and a region's own list if given."""
    held = {"source": "https://example.test/public-holidays",
            "years": {"2026": ["2026-01-01", "2026-10-26", "2026-12-25"]}}
    if regions:
        held["regions"] = {code.replace("_", "-"): years for code, years in regions.items()}
    return held


def tariff(**changes) -> dict:
    doc = {"schema": 1, "name": "Plan", "provider": "P Energy", "effective_from": "2026-11-01",
           "source": dict(SOURCE),
           "bands": [{"name": "Day"}, {"name": "Night", "hours": "23:00-08:00"}],
           "areas": {"urban": {"label": "Urban", "standing": "1",
                               "rates": {"Day": "0.3", "Night": "0.15"}},
                     "rural": {"label": "Rural", "standing": "1.1",
                               "rates": {"Day": "0.32", "Night": "0.16"}}}}
    doc.update(changes)
    return doc


def export(**changes) -> dict:
    doc = {"schema": 1, "name": "Out", "provider": "P Energy", "direction": "export",
           "effective_from": "2026-01-01", "source": dict(SOURCE), "bands": [{"name": "Flat"}],
           "areas": {"all": {"rates": {"Flat": "0.12"}}}}
    doc.update(changes)
    return doc


def flat(price="0.25", start="2026-01-01", **changes) -> dict:
    doc = {"schema": 1, "name": "Flat", "provider": "P Energy", "effective_from": start,
           "source": dict(SOURCE), "bands": [{"name": "All day"}],
           "areas": {"all": {"standing": "0.5", "rates": {"All day": price}}}}
    doc.update(changes)
    return doc


def write_store(root: Path, files: dict[str, dict] | None = None, block: dict | None = None,
                unavailable: dict | None = None) -> Path:
    """A tariffs/ folder with one country (IE) holding `files`, not yet built."""
    tariffs = Path(root) / "tariffs"
    folder = tariffs / "ie"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.json").write_text(json.dumps(block or country()), encoding="utf-8")
    for path, doc in (files if files is not None else {"p/plan/1.json": tariff()}).items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_text(layout.dumps_tariff(doc), encoding="utf-8")
    (tariffs / "unavailable.json").write_text(json.dumps(
        unavailable or {"schema": 1, "countries": {"XX": {"reason": "No source", "checked": "2026-11-10"}}}),
        encoding="utf-8")
    return tariffs
