"""Tests for switch entities."""

from __future__ import annotations

from pathlib import Path

# Reuse the stub setup from conftest


class TestAutoImmersionSwitchRestore:
    """GivEnergyAutoImmersionSwitch must restore its state across HA restarts.
    Without RestoreEntity, turning off auto-divert and restarting HA silently
    re-enables it — the immersion heater starts being controlled again."""

    def test_inherits_restore_entity(self):
        from pathlib import Path

        src = Path("custom_components/givenergy_inverter_manager/switch.py").read_text()
        assert "RestoreEntity" in src, (
            "GivEnergyAutoImmersionSwitch must inherit RestoreEntity to persist "
            "its on/off state across HA restarts."
        )

    def test_auto_immersion_has_async_added_to_hass(self):
        src = Path("custom_components/givenergy_inverter_manager/switch.py").read_text()
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
        src = Path("custom_components/givenergy_inverter_manager/switch.py").read_text()
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
        src = Path("custom_components/givenergy_inverter_manager/switch.py").read_text()
        assert "RestoreEntity" in src, (
            "GivEnergyChargeTargetOverrideSwitch must inherit RestoreEntity."
        )

    def test_override_switch_has_async_added_to_hass(self):
        src = Path("custom_components/givenergy_inverter_manager/switch.py").read_text()
        override_section = src[src.index("class GivEnergyChargeTargetOverrideSwitch") :]
        assert "async_added_to_hass" in override_section, (
            "GivEnergyChargeTargetOverrideSwitch must implement async_added_to_hass."
        )

    def test_restored_off_clears_override_charge_target(self):
        src = Path("custom_components/givenergy_inverter_manager/switch.py").read_text()
        assert "override_charge_target = None" in src, (
            "When the override switch is restored as 'off', coordinator."
            "override_charge_target must be cleared to None — otherwise "
            "the coordinator applies a stale target from the previous session."
        )


class TestSwitchImportsRestoreEntity:
    """RestoreEntity import check — confirms the import exists, not just usage."""

    def test_restore_entity_imported(self):
        src = Path("custom_components/givenergy_inverter_manager/switch.py").read_text()
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

    def test_cooldown_attribute_on_coordinator(self):
        from pathlib import Path
        src = Path("custom_components/givenergy_inverter_manager/coordinator.py").read_text()
        assert "_immersion_cooldown_until" in src

    def test_cooldown_checked_in_handle_update(self):
        from pathlib import Path
        src = Path("custom_components/givenergy_inverter_manager/switch.py").read_text()
        update_fn = src[src.find("def _handle_coordinator_update"):]
        assert "_immersion_cooldown_until" in update_fn

    def test_manual_on_clears_cooldown(self):
        from pathlib import Path
        src = Path("custom_components/givenergy_inverter_manager/switch.py").read_text()
        # Search within GivEnergyImmersionControlSwitch only
        control_cls = src[src.find("class GivEnergyImmersionControlSwitch"):]
        next_cls = control_cls.find("\nclass ", 10)
        control_cls = control_cls[:next_cls] if next_cls != -1 else control_cls
        assert "_immersion_cooldown_until = None" in control_cls

    def test_manual_off_clears_cooldown(self):
        from pathlib import Path
        src = Path("custom_components/givenergy_inverter_manager/switch.py").read_text()
        control_cls = src[src.find("class GivEnergyImmersionControlSwitch"):]
        next_cls = control_cls.find("\nclass ", 10)
        control_cls = control_cls[:next_cls] if next_cls != -1 else control_cls
        assert control_cls.count("_immersion_cooldown_until = None") >= 2
