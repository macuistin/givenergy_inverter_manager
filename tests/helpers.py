"""Shared paths for the unit tests, so no test depends on the working directory."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "custom_components" / "givenergy_inverter_manager"
