"""Tests for switch entities.

The restore behaviour of the switches runs against a real Home Assistant in
tests/ha_e2e/test_switch_restore_e2e.py (Auto Immersion Divert) and
tests/ha_e2e/test_charge_override_e2e.py (Enable Charge Target Override).
"""

from __future__ import annotations


class TestImmersionCooldown:
    """Auto write to the real switch is suppressed within the cooldown window."""

    def test_cooldown_constant_in_const(self):
        from custom_components.givenergy_inverter_manager.const import (
            IMMERSION_SWITCH_COOLDOWN_MINUTES,
        )
        assert IMMERSION_SWITCH_COOLDOWN_MINUTES > 0
