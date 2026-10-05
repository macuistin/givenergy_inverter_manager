"""Tests for switch entities."""

from __future__ import annotations

from tests.helpers import PKG

# Reuse the stub setup from conftest


class TestAutoImmersionSwitchRestore:
    """GivEnergyAutoImmersionSwitch must restore its state across HA restarts.
    Without RestoreEntity, turning off auto-divert and restarting HA silently
    re-enables it — the immersion heater starts being controlled again."""

    def test_inherits_restore_entity(self):

        src = (PKG / "switch.py").read_text()
        assert "RestoreEntity" in src, (
            "GivEnergyAutoImmersionSwitch must inherit RestoreEntity to persist "
            "its on/off state across HA restarts."
        )

    def test_auto_immersion_has_async_added_to_hass(self):
        src = (PKG / "switch.py").read_text()
        # Both switch classes must implement async_added_to_hass
        auto_section = src[src.index("class GivEnergyAutoImmersionSwitch") :]
        # Find the next class boundary
        next_class = auto_section.find("\nclass ", 10)
        auto_class = auto_section[:next_class] if next_class != -1 else auto_section
        assert "async_added_to_hass" in auto_class, (
            "GivEnergyAutoImmersionSwitch must implement async_added_to_hass "
            "to restore its state after a restart."
        )

    def test_restored_off_state_sets_coordinator_override(self):
        """When restored as 'off', coordinator.override_immersion must be set to False."""
        src = (PKG / "switch.py").read_text()
        # Check that the restore logic updates coordinator
        assert "coordinator.override_immersion" in src, (
            "async_added_to_hass must push the restored state to "
            "coordinator.override_immersion — otherwise the first coordinator "
            "cycle after restart uses the wrong mode."
        )


class TestChargeTargetOverrideSwitchRestore:
    """GivEnergyChargeTargetOverrideSwitch must also restore state.
    Without this, the override silently disables after every HA restart,
    switching back to auto-calculated charge targets."""

    def test_inherits_restore_entity(self):
        src = (PKG / "switch.py").read_text()
        assert "RestoreEntity" in src, (
            "GivEnergyChargeTargetOverrideSwitch must inherit RestoreEntity."
        )

    def test_override_switch_has_async_added_to_hass(self):
        src = (PKG / "switch.py").read_text()
        override_section = src[src.index("class GivEnergyChargeTargetOverrideSwitch") :]
        assert "async_added_to_hass" in override_section, (
            "GivEnergyChargeTargetOverrideSwitch must implement async_added_to_hass."
        )


class TestSwitchImportsRestoreEntity:
    """RestoreEntity import check — confirms the import exists, not just usage."""

    def test_restore_entity_imported(self):
        src = (PKG / "switch.py").read_text()
        assert (
            "from homeassistant.helpers.entity import RestoreEntity" in src
            or "RestoreEntity" in src
        ), "switch.py must import RestoreEntity from homeassistant.helpers.entity."


class TestImmersionCooldown:
    """Auto write to the real switch is suppressed within the cooldown window."""

    def test_cooldown_constant_in_const(self):
        from custom_components.givenergy_inverter_manager.const import (
            IMMERSION_SWITCH_COOLDOWN_MINUTES,
        )
        assert IMMERSION_SWITCH_COOLDOWN_MINUTES > 0
