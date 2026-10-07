"""What the dashboard generator promises about the entities it asks for and the order it builds."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.dashboard.registry import HostFacts
from custom_components.givenergy_inverter_manager.dashboard.views import Builder
from tests.dashboard_support import (
    FULL_CONFIG,
    RecordingRegistry,
    dashboard_text,
    default_entity_ids,
    fake_entry,
    fake_states_hass,
)


def test_every_unique_id_suffix_the_generator_asks_for_exists():
    """A misspelt suffix finds nothing, and the tile it feeds silently disappears."""
    registry = RecordingRegistry(enable_all=True)
    dashboard_text(FULL_CONFIG, registry, states=("sensor.wallbox_charging_power",))
    unknown = registry.requested - set(default_entity_ids())
    assert unknown == set()
    assert len(registry.requested) > 60


class TestBuildOrder:
    def _builder(self):
        return Builder(fake_states_hass(), fake_entry(FULL_CONFIG), HostFacts(), RecordingRegistry())

    def test_tabs_can_be_linked_before_the_sub_views_are_built(self):
        assert self._builder().go("today") == {"action": "navigate", "navigation_path": "today"}

    def test_a_sub_view_link_needs_the_sub_views_to_be_built_first(self):
        with pytest.raises(RuntimeError, match="sub-views"):
            self._builder().go("immersion")

    def test_an_empty_sub_view_gets_no_link(self):
        """Settings has no cards without an administrator to show them to."""
        builder = Builder(fake_states_hass(), fake_entry({}), HostFacts(), RecordingRegistry())
        builder.build_subviews()
        assert builder.go("settings") is None
        assert builder.go("tariff") is not None

    def test_a_device_sub_view_is_linked_before_the_device_exists(self):
        """Its cards wait for the device, so a stored dashboard can open it when it arrives."""
        builder = Builder(fake_states_hass(), fake_entry({}), HostFacts(), RecordingRegistry())
        builder.build_subviews()
        assert builder.go("immersion") is not None
        assert builder.go("ev-charger") is not None
