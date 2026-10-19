"""The GivTCP reader: signs, counters, and whether the feed is live."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_GRID_POWER,
    CONF_HOUSE_LOAD,
    CONF_INVERTER_SERIAL,
    CONF_SOLAR_POWER,
    GIVTCP_FROZEN_AFTER_S,
)
from custom_components.givenergy_inverter_manager.core.inverter_values import FeedState
from custom_components.givenergy_inverter_manager.lib.givtcp.reader import GivTCPReader

NOW = datetime(2031, 3, 4, 12, 0, tzinfo=timezone.utc)
SERIAL = "ab1234c567"
PFX = f"sensor.givtcp_{SERIAL}"
CFG = {
    CONF_INVERTER_SERIAL: SERIAL,
    CONF_SOLAR_POWER: f"{PFX}_pv_power",
    CONF_BATTERY_SOC: f"{PFX}_soc",
    CONF_BATTERY_POWER: f"{PFX}_battery_power",
    CONF_GRID_POWER: f"{PFX}_grid_power",
    CONF_HOUSE_LOAD: f"{PFX}_load_power",
}


def _states(**overrides: str | tuple[str, datetime]) -> dict:
    base = {
        CFG[CONF_SOLAR_POWER]: "3000",
        CFG[CONF_BATTERY_SOC]: "60",
        CFG[CONF_BATTERY_POWER]: "500",
        CFG[CONF_GRID_POWER]: "1200",
        CFG[CONF_HOUSE_LOAD]: "1500",
    }
    base.update({f"{PFX}_{k}" if "." not in k else k: v for k, v in overrides.items()})
    out = {}
    for entity_id, value in base.items():
        value, reported = value if isinstance(value, tuple) else (value, NOW)
        out[entity_id] = SimpleNamespace(state=value, last_reported=reported)
    return out


def _reader(states: dict) -> GivTCPReader:
    return GivTCPReader(states.get)


class TestSigns:
    def test_grid_power_published_as_export_is_negative_import(self):
        values = _reader(_states()).read(CFG)

        assert values.grid_power_w == -1200

    def test_battery_power_published_as_discharging_is_negative_charging(self):
        values = _reader(_states()).read(CFG)

        assert values.battery_power_w == -500

    def test_an_idle_battery_reads_positive_zero(self):
        values = _reader(_states(battery_power="0")).read(CFG)

        assert str(values.battery_power_w) == "0.0"


class TestUnavailableInputs:
    def test_a_missing_required_input_is_named_and_reads_zero(self):
        states = _states()
        del states[CFG[CONF_HOUSE_LOAD]]

        values = _reader(states).read(CFG)

        assert values.unavailable_inputs == ("house_load",)
        assert values.house_load_w == 0.0

    def test_counters_are_none_without_a_serial(self):
        values = _reader(_states()).read({**CFG, CONF_INVERTER_SERIAL: ""})

        assert values.import_energy_today_kwh is None
        assert values.battery_charge_rate_w is None

    def test_a_charge_rate_of_zero_is_none(self):
        states = _states(**{f"number.givtcp_{SERIAL}_battery_charge_rate": "0"})

        assert _reader(states).read(CFG).battery_charge_rate_w is None


class TestDataAge:
    def test_data_age_is_read_where_givtcp_publishes_it(self):
        assert _reader(_states(data_age="2.5")).read(CFG).data_age_s == 2.5

    def test_data_age_is_none_where_givtcp_does_not_publish_it(self):
        assert _reader(_states()).read(CFG).data_age_s is None


class TestFeedStatus:
    def test_a_live_feed_is_publishing(self):
        assert _reader(_states()).feed_status(CFG, NOW).is_publishing

    def test_both_anchor_entities_missing_is_missing(self):
        states = _states()
        del states[CFG[CONF_SOLAR_POWER]], states[CFG[CONF_BATTERY_SOC]]

        assert _reader(states).feed_status(CFG, NOW).state is FeedState.MISSING

    def test_both_anchor_entities_unavailable_is_silent(self):
        states = _states(pv_power="unavailable", soc="unavailable")

        assert _reader(states).feed_status(CFG, NOW).state is FeedState.SILENT

    def test_one_anchor_entity_unavailable_is_not_silent(self):
        assert _reader(_states(pv_power="unavailable")).feed_status(CFG, NOW).is_publishing

    def test_nothing_reported_for_longer_than_the_limit_is_frozen(self):
        old = NOW - timedelta(seconds=GIVTCP_FROZEN_AFTER_S + 1)
        states = {k: SimpleNamespace(state=v.state, last_reported=old) for k, v in _states().items()}

        status = _reader(states).feed_status(CFG, NOW)

        assert status.state is FeedState.FROZEN
        assert status.last_report == old

    def test_a_paused_status_is_paused(self):
        assert _reader(_states(status="paused")).feed_status(CFG, NOW).state is FeedState.PAUSED

    def test_an_online_status_is_publishing(self):
        assert _reader(_states(status="online")).feed_status(CFG, NOW).is_publishing

    @pytest.mark.parametrize("age", ["-1", str(GIVTCP_FROZEN_AFTER_S + 1)])
    def test_data_that_is_old_or_never_read_is_stale(self, age):
        assert _reader(_states(data_age=age)).feed_status(CFG, NOW).state is FeedState.STALE

    @pytest.mark.parametrize("age", ["0", "30", str(GIVTCP_FROZEN_AFTER_S)])
    def test_fresh_data_is_publishing(self, age):
        assert _reader(_states(data_age=age)).feed_status(CFG, NOW).is_publishing

    def test_a_data_age_that_cannot_be_read_does_not_count_against_the_feed(self):
        assert _reader(_states(data_age="unavailable")).feed_status(CFG, NOW).is_publishing


class TestRateDefaults:
    def _rates(self, **rates: str):
        states = _states(**{f"{k}_rate": v for k, v in rates.items()})
        return _reader(states).rate_defaults(SERIAL)

    def test_rates_the_user_set_are_returned(self):
        held = self._rates(day="0.2918", night="0.1432", export="0.1")

        assert (held.day_rate, held.night_rate, held.export_rate) == (0.2918, 0.1432, 0.1)

    def test_the_rates_givtcp_ships_with_are_not_returned(self):
        assert self._rates(day="0.395", night="0.155", export="0.04") is None

    def test_a_shipped_default_is_skipped_but_a_changed_rate_beside_it_is_kept(self):
        held = self._rates(day="0.395", night="0.1432", export="0.04")

        assert (held.day_rate, held.night_rate, held.export_rate) == (None, 0.1432, None)

    @pytest.mark.parametrize("value", ["0", "-0.1", "unavailable", "unknown", "not a number"])
    def test_a_zero_negative_or_unreadable_rate_is_not_returned(self, value):
        assert self._rates(day=value, night=value, export=value) is None

    def test_no_rate_sensors_gives_none(self):
        assert _reader(_states()).rate_defaults(SERIAL) is None

    def test_no_serial_gives_none(self):
        assert _reader(_states(day_rate="0.3")).rate_defaults(None) is None
