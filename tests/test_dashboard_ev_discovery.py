"""The dashboard prefers a known external EV charger over the integration's own sensor."""


class TestEvChargerDiscovery:
    """_find_ev_charger_power prefers known external EV integrations over the
    integration's own sensor, which reads from GivTCP and may show 0W."""

    def _find(self, states_present=None):
        from unittest.mock import MagicMock

        from custom_components.givenergy_inverter_manager.dashboard_builder import (
            _find_ev_charger_power,
        )

        hass = MagicMock()
        hass.states.get = lambda eid: MagicMock() if eid in (states_present or []) else None
        return _find_ev_charger_power(hass, "sensor.givenergy_inverter_manager_ev_charging_power")

    def test_falls_back_to_integration_sensor_when_no_external_charger(self):
        assert self._find([]) == "sensor.givenergy_inverter_manager_ev_charging_power"

    def test_prefers_myenergi_zappi_when_present(self):
        assert (
            self._find(["sensor.myenergi_zappi_power_ct_internal_load"])
            == "sensor.myenergi_zappi_power_ct_internal_load"
        )

    def test_prefers_first_candidate_found(self):
        result = self._find(
            ["sensor.myenergi_zappi_power_ct_internal_load", "sensor.wallbox_charging_power"]
        )
        assert result == "sensor.myenergi_zappi_power_ct_internal_load"

    def test_wallbox_used_when_no_zappi(self):
        assert self._find(["sensor.wallbox_charging_power"]) == "sensor.wallbox_charging_power"
