"""The dashboard prefers a known external EV charger over the integration's own sensor."""

from tests.dashboard_support import all_cards, dashboard_dict, default_entity_ids

ZAPPI = "sensor.myenergi_zappi_power_ct_internal_load"
WALLBOX = "sensor.wallbox_charging_power"


def _car_charger_entity(*present: str) -> str:
    """The entity the power flow card draws as Car Charger, given these external entities."""
    views = dashboard_dict(states=present)["views"]
    flow = next(c for c in all_cards(views) if c["type"] == "custom:power-flow-card-plus")
    row = next(r for r in flow["entities"]["individual"] if r["name"] == "Car Charger")
    return row["entity"]


class TestEvChargerDiscovery:
    """The integration's own sensor reads from GivTCP and may show 0W, so a known external
    EV integration wins when it is present."""

    def test_falls_back_to_integration_sensor_when_no_external_charger(self):
        assert _car_charger_entity() == default_entity_ids()["ev_power"]

    def test_prefers_myenergi_zappi_when_present(self):
        assert _car_charger_entity(ZAPPI) == ZAPPI

    def test_prefers_first_candidate_found(self):
        assert _car_charger_entity(WALLBOX, ZAPPI) == ZAPPI

    def test_wallbox_used_when_no_zappi(self):
        assert _car_charger_entity(WALLBOX) == WALLBOX
