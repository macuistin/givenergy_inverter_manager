"""
optimizer.py — Re-export shim for backward compatibility.

All decision logic has been consolidated into rules.py.
This module re-exports the public API so existing imports keep working.

For new code, import directly from rules.py.
"""
from .rules import (  # noqa: F401
    ChargeDecision,
    calculate_overnight_charge_target,
    monthly_solar_fractions,
    should_divert_to_immersion,
    suggest_appliance_run,
)
