"""example_definition.py: the worked tariff document the definition tests start from."""

from __future__ import annotations

import copy
import json
from typing import Any

_TEXT = """
{
  "schema": 1,
  "id": "example-nightboost",
  "revision": 1,
  "supersedes": null,
  "name": "Day, night and boost",
  "service": "electricity",
  "customer_class": "residential",
  "provider": {"id": "example-energy", "name": "Example Energy"},
  "country": "IE",
  "region": null,
  "currency": "EUR",
  "timezone": "Europe/Dublin",
  "effective_from": "2026-01-01",
  "effective_to": null,
  "source_url": "https://example.com/tariffs/nightboost",
  "last_verified": "2026-10-20",
  "completeness": "complete",
  "inputs": {"start_day": {"type": "integer", "min": 1, "max": 28, "default": 1}},
  "import": {
    "base": {"name": "Day", "price": "0.365"},
    "zones": [
      {"name": "Night", "priority": 1, "price": "0.18", "hours": "23:00-08:00"},
      {"name": "Boost", "priority": 2, "price": "0.1056", "hours": "02:00-04:00"}
    ]
  },
  "export": {"base": {"name": "Export", "price": "0.195"}},
  "bill": {
    "period": {"rule": "monthly", "start_day": {"input": "start_day"}},
    "total": {
      "kind": "sum",
      "of": {
        "charges": {
          "kind": "tax", "name": "VAT", "percent": "9", "mode": "added",
          "of": {
            "kind": "sum",
            "of": {
              "energy": {
                "kind": "adjust", "name": "Saving", "percent": "-5.5",
                "of": {"kind": "energy_by_band", "round_bands": true}
              },
              "standing": {"kind": "per_day", "amount": "0.8259"},
              "levy": {"kind": "per_period", "amount": "1.46", "share": "days_in_period"}
            }
          }
        },
        "credit": {"kind": "export_credit"}
      }
    }
  },
  "checks": {
    "october-2026": {
      "period_days": 30,
      "import_kwh_by_band": {"Boost": "257", "Day": "67", "Night": "619"},
      "export_kwh": "47",
      "expected_total": "187.35"
    }
  }
}
"""


def example_text() -> str:
    return _TEXT


def example_document() -> dict[str, Any]:
    """A fresh copy each call, so a test can change it freely."""
    return copy.deepcopy(json.loads(_TEXT))
