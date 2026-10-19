"""The banner for a scheduled immersion run that was stopped by the longest run."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.core.devices import Device
from tests.dashboard_support import dashboard_dict, default_entity_ids
from tests.dashboard_visibility import seen, states_with

LIMIT = default_entity_ids()["immersion_run_limit"]
BANNER = "The immersion stopped at its longest run"
EVERYTHING = set(Device)


def _power_flow(dashboard: dict) -> dict:
    return next(v for v in dashboard["views"] if v["path"] == "power-flow")


def _headings(view: dict) -> list[str | None]:
    return [s["cards"][0].get("heading") for s in view["sections"]]


def _seen(state: str, devices=EVERYTHING) -> list[str | None]:
    return _headings(_power_flow(seen(dashboard_dict(), states_with(devices, {LIMIT: state}))))


class TestTheBanner:
    def test_it_shows_while_the_sensor_says_reached(self):
        assert BANNER in _seen("reached")

    def test_it_is_hidden_while_the_sensor_says_idle_or_off(self):
        assert BANNER not in _seen("idle")
        assert BANNER not in _seen("off")

    def test_it_is_hidden_without_the_immersion_switch(self):
        assert BANNER not in _seen("reached", EVERYTHING - {Device.IMMERSION_SWITCH})

    def test_it_sits_after_the_alternative_heating_banner(self):
        headings = _headings(_power_flow(dashboard_dict()))
        assert headings.index(BANNER) == headings.index("Start the alternative heating") + 1

    def test_it_uses_only_conditions_the_floor_has(self):
        section = next(
            s for s in _power_flow(dashboard_dict())["sections"]
            if s["cards"][0].get("heading") == BANNER
        )
        assert {c["condition"] for c in section["visibility"]} <= {"state", "numeric_state", "user", "or"}

    def test_the_text_says_what_to_change(self):
        section = next(
            s for s in _power_flow(dashboard_dict())["sections"]
            if s["cards"][0].get("heading") == BANNER
        )
        assert "Longest immersion run" in section["cards"][1]["content"]
