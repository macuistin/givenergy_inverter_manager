"""The entity ids of the rate sensors GivTCP holds."""


class TestRateEntities:
    def test_the_rate_sensors_are_named_by_the_inverter_serial(self):
        from custom_components.givenergy_inverter_manager.discovery import givtcp_rate_entity_ids

        assert givtcp_rate_entity_ids("fd2309f069") == {
            "day": "sensor.givtcp_fd2309f069_day_rate",
            "night": "sensor.givtcp_fd2309f069_night_rate",
            "export": "sensor.givtcp_fd2309f069_export_rate",
        }
