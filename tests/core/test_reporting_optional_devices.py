"""Reports leave out the immersion saving on an install with no immersion switch."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.core import reporting
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator

_IMMERSION_TEXT = ("Immersion", "Saved")


def _data(*, immersion_configured: bool) -> CoordinatorData:
    data = CoordinatorData()
    data.immersion_configured = immersion_configured
    data.today = EnergyAccumulator(solar_kwh=6.0, immersion_savings=0.0)
    data.week = EnergyAccumulator(solar_kwh=40.0)
    return data


@pytest.mark.parametrize(
    "report",
    [
        reporting.build_today_summary_html,
        reporting.build_today_summary_state,
        reporting.build_week_summary_html,
    ],
)
class TestImmersionLinesFollowTheSwitch:
    def test_present_with_an_immersion_switch(self, report):
        text = report(_data(immersion_configured=True))
        assert any(word in text for word in _IMMERSION_TEXT)

    def test_absent_without_one(self, report):
        text = report(_data(immersion_configured=False))
        assert not any(word in text for word in _IMMERSION_TEXT)


def test_the_other_savings_and_week_rows_stay_without_an_immersion_switch():
    data = _data(immersion_configured=False)
    assert "Self-sufficiency" in reporting.build_today_summary_html(data)
    assert "Self-sufficiency" in reporting.build_week_summary_html(data)
    assert "Self-suff" in reporting.build_today_summary_state(data)
