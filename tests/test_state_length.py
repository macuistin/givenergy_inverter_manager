"""
No sensor publishes a state longer than Home Assistant's 255 characters.

Home Assistant logs an error on every update of a longer state and reads it as unknown. The
overnight charge reason did this on 2026-10-11: "Forward simulation: 7.3kWh forecast ... Not
skipping: Battery may run low ... (capped at configured max 90%)" is 271 characters.

The audit builds the sensor entities and reads what they publish, over three kinds of data:
every case of the engine golden snapshot, the longest decision text the engine can build,
and a snapshot whose free text fields are all far over the limit.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.givenergy_inverter_manager.const import (
    ATTR_FULL_TEXT,
    CONF_FORECAST_CONSERVATISM,
    CONF_OVERNIGHT_CHARGE_TARGET,
    STATE_MAX_LENGTH,
)
from custom_components.givenergy_inverter_manager.core.battery import BatteryStats
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.core.reporting import (
    build_charge_plan_html,
    build_charge_plan_state,
    build_today_summary_state,
    build_week_summary_state,
)
from custom_components.givenergy_inverter_manager.core.rules import (
    ChargeDecision,
    forecast_accuracy,
)
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from custom_components.givenergy_inverter_manager.core.text_state import ELLIPSIS
from custom_components.givenergy_inverter_manager.sensor import (
    SENSOR_DESCRIPTIONS,
    GivEnergyManagerSensor,
)
from tests.conftest import _nightboost_cfg, _raw
from tests.core import engine_snapshot as snap
from tests.core.flat_engine import build_coordinator_data

_GOLDEN = json.loads(
    (Path(__file__).parent / "core" / "golden_engine_snapshots.json").read_text()
)["cases"]

# Home Assistant logs a warning when the attributes of one state are larger than this.
_MAX_ATTRIBUTE_BYTES = 16384

# 1000 characters of text with sentences, clauses and characters outside ASCII.
_LONG_NON_ASCII = ("Water at 48.2°C → heating — résumé, naïve café. " * 21)[:1000]

# The reason of the 2026-10-11 log line, as the charge plan builds it.
_LOGGED_REASON = (
    "Forward simulation: 7.3kWh forecast (forecast integration, x0.87 recent accuracy "
    "(cautious forecast, 50% of the way from the typical to the low estimate)). Target 100%. "
    "Not skipping: Battery may run low. Estimated shortfall: 1.0kWh before solar starts. "
    "Per-slot load profile used. (capped at configured max 90%)"
)


def _sensor(description, data) -> GivEnergyManagerSensor:
    coordinator = SimpleNamespace(data=data, entry=SimpleNamespace(entry_id="entry"))
    return GivEnergyManagerSensor(coordinator, description)


def _text_of(description, data) -> str | None:
    """What the description's value_fn says, when that is text."""
    try:
        value = description.value_fn(data)
    except Exception:  # noqa: BLE001
        return None
    return value if isinstance(value, str) else None


def _published_texts(data) -> list[tuple]:
    """(description, full text, published state, attributes) of every text sensor."""
    rows = []
    for description in SENSOR_DESCRIPTIONS:
        full = _text_of(description, data)
        if full is None:
            continue
        sensor = _sensor(description, data)
        rows.append((description, full, sensor.native_value, sensor.extra_state_attributes or {}))
    return rows


def _problems(data) -> list[str]:
    """Every way a text sensor of this snapshot publishes a state Home Assistant would refuse."""
    problems = []
    for description, full, state, attributes in _published_texts(data):
        if len(state) > STATE_MAX_LENGTH:
            problems.append(f"{description.key}: state is {len(state)} characters")
        if len(full) > STATE_MAX_LENGTH:
            if attributes.get(ATTR_FULL_TEXT) != full:
                problems.append(f"{description.key}: the full text is not in {ATTR_FULL_TEXT}")
        elif state != full or ATTR_FULL_TEXT in attributes:
            problems.append(f"{description.key}: a text that fits was changed")
    return problems


def _decision(reason: str, **fields) -> ChargeDecision:
    values = {
        "target_soc": 100,
        "skip_charge": False,
        "reason": reason,
        "forecast_kwh": 7.3,
        "current_soc": 40.0,
        "battery_capacity": 9.5,
        "car_plugged_in": False,
        "cost_to_charge": 1.2,
    }
    return ChargeDecision(**{**values, **fields})


def _engine_data(*, plugged_in: bool) -> CoordinatorData:
    """The longest decision text the engine builds, from a real cycle.

    A cautious forecast scaled by recent accuracy, a per-slot load profile, an overmorrow
    reduction, a configured maximum and either a car (the buffer note) or a battery that will
    not last the night (the "Not skipping" note). The two cannot both apply.
    """
    cfg = _nightboost_cfg()
    cfg[CONF_FORECAST_CONSERVATISM] = 0.5
    cfg[CONF_OVERNIGHT_CHARGE_TARGET] = 60
    raw = _raw(
        battery_soc=80.0,
        solar_power_w=0.0,
        forecast_kwh_tomorrow=30.0,
        forecast_kwh_p10=20.0,
        forecast_kwh_d2=30.0,
        ev_plugged_in=plugged_in,
    )
    data, _ = build_coordinator_data(
        raw=raw,
        cfg=cfg,
        acc=EnergyAccumulator(house_kwh=40.0),
        battery_stats=BatteryStats(),
        last_soc=None,
        last_update_time=None,
        now=datetime(2024, 6, 15, 21, 0),
        load_profile=[0.3] * 48,
        forecast_correction=0.8,
    )
    return data


def _saturated() -> CoordinatorData:
    """A snapshot in which every free text field is far over the limit, in non-ASCII text."""
    data = CoordinatorData()
    long = _LONG_NON_ASCII
    data.divert_reason = long
    data.survival_reason = long
    data.ev_protection_reason = long
    data.ev_charging_source = long
    data.cheap_rate_floor_status = long
    data.dry_run_last_skipped = long
    data.inverter_temperature_status = long
    data.battery_throughput_budget_status = long
    data.carbon_intensity_status = long
    data.current_rate_name = long
    data.cheapest_rate_name = long
    data.currency_symbol = "€" * 300
    data.charge_decision = _decision(long)
    data.published_charge_decision = _decision(long)
    return data


class TestEverySensorOfTheGoldenSnapshots:
    def test_no_case_publishes_a_state_over_the_limit(self):
        failures = []
        for number, case in enumerate(_GOLDEN):
            kwargs = {name: snap.decode(value) for name, value in case["in"].items()}
            data, _ = build_coordinator_data(**kwargs)
            failures += [f"case {number}: {problem}" for problem in _problems(data)]

        assert failures == []

    def test_a_golden_case_does_reach_the_limit(self):
        """The audit is only worth anything while the golden data holds a long text."""
        longest = 0
        for case in _GOLDEN:
            kwargs = {name: snap.decode(value) for name, value in case["in"].items()}
            data, _ = build_coordinator_data(**kwargs)
            longest = max(longest, max(len(text) for _, text, _, _ in _published_texts(data)))

        assert longest > STATE_MAX_LENGTH


class TestTheLongestDecisionTextTheEngineBuilds:
    @pytest.mark.parametrize("plugged_in", [False, True], ids=["battery_short", "car_plugged_in"])
    def test_every_sensor_fits(self, plugged_in):
        data = _engine_data(plugged_in=plugged_in)

        assert len(data.published_charge_decision.reason) > 200
        assert _problems(data) == []

    def test_the_not_skipping_reason_is_over_the_limit_and_is_cut(self):
        data = _engine_data(plugged_in=False)
        reason = data.published_charge_decision.reason
        sensor = _sensor(_description("overnight_charge_reason"), data)

        assert len(reason) > STATE_MAX_LENGTH
        assert "Not skipping" in reason
        assert len(sensor.native_value) <= STATE_MAX_LENGTH
        assert sensor.native_value.endswith(ELLIPSIS)
        assert sensor.extra_state_attributes[ATTR_FULL_TEXT] == reason


class TestFreeTextFields:
    def test_every_text_sensor_fits_when_every_text_is_far_too_long(self):
        assert _problems(_saturated()) == []

    def test_the_saturated_snapshot_does_cut_the_sensors_that_carry_free_text(self):
        cut = {
            d.key for d, full, _, _ in _published_texts(_saturated()) if len(full) > STATE_MAX_LENGTH
        }

        assert {
            "overnight_charge_reason",
            "immersion_divert_reason",
            "night_survival_reason",
            "ev_protection_reason",
            "cheap_rate_floor_status",
            "dry_run_last_skipped",
            "current_rate_period",
            "cheapest_rate_period",
        } <= cut

    def test_the_attributes_stay_under_the_size_home_assistant_warns_at(self):
        data = _saturated()
        for description in SENSOR_DESCRIPTIONS:
            attributes = _sensor(description, data).extra_state_attributes or {}
            size = len(json.dumps(attributes, default=str, ensure_ascii=False).encode())
            assert size < _MAX_ATTRIBUTE_BYTES, description.key


def _description(key: str):
    return next(d for d in SENSOR_DESCRIPTIONS if d.key == key)


class TestEveryDescription:
    """Each sensor description, on a snapshot whose texts are all 1000 characters long."""

    @pytest.mark.parametrize("key", [d.key for d in SENSOR_DESCRIPTIONS])
    def test_the_published_state_is_at_most_255_characters(self, key):
        sensor = _sensor(_description(key), _saturated())

        state = sensor.native_value

        if isinstance(state, str):
            assert len(state) <= STATE_MAX_LENGTH

    @pytest.mark.parametrize("key", [d.key for d in SENSOR_DESCRIPTIONS])
    def test_the_full_text_is_kept_whenever_the_state_was_cut(self, key):
        data = _saturated()
        full = _text_of(_description(key), data)
        sensor = _sensor(_description(key), data)

        attributes = sensor.extra_state_attributes or {}

        if full is not None and len(full) > STATE_MAX_LENGTH:
            assert attributes[ATTR_FULL_TEXT] == full
        else:
            assert ATTR_FULL_TEXT not in attributes


class TestTheFullTextIsKept:
    def test_a_text_that_fits_is_published_as_it_is_with_no_attribute(self):
        data = CoordinatorData()
        data.divert_reason = "Manual override"

        sensor = _sensor(_description("immersion_divert_reason"), data)

        assert sensor.native_value == "Manual override"
        assert sensor.extra_state_attributes is None

    def test_a_cut_text_is_in_full_text(self):
        data = CoordinatorData()
        data.cheap_rate_floor_status = _LONG_NON_ASCII

        sensor = _sensor(_description("cheap_rate_floor_status"), data)

        assert sensor.native_value != _LONG_NON_ASCII
        assert sensor.extra_state_attributes == {ATTR_FULL_TEXT: _LONG_NON_ASCII}

    def test_the_forecast_accuracy_attributes_stay_beside_full_text(self):
        data = _engine_data(plugged_in=False)
        data.forecast_accuracy = forecast_accuracy(
            [{"forecast": 10.0, "actual": 8.0, "clipped": False}] * 7
        )

        attributes = _sensor(_description("overnight_charge_reason"), data).extra_state_attributes

        assert attributes[ATTR_FULL_TEXT] == data.published_charge_decision.reason
        assert attributes["accuracy_applied_factor"] == 0.8

    def test_a_number_is_published_as_it_was(self):
        data = CoordinatorData()
        data.solar_power_w = 1234.56

        assert _sensor(_description("solar_power"), data).native_value == 1234.6

    def test_full_text_stays_out_of_the_recorder(self):
        assert ATTR_FULL_TEXT in GivEnergyManagerSensor._unrecorded_attributes


class TestTheLoggedReason:
    """The overnight charge reason that Home Assistant refused on 2026-10-11."""

    @staticmethod
    def _data() -> CoordinatorData:
        data = CoordinatorData()
        data.published_charge_decision = _decision(_LOGGED_REASON)
        return data

    def test_the_reason_is_over_the_limit(self):
        assert len(_LOGGED_REASON) > STATE_MAX_LENGTH

    def test_the_state_fits_and_says_it_was_cut(self):
        state = _sensor(_description("overnight_charge_reason"), self._data()).native_value

        assert len(state) <= STATE_MAX_LENGTH
        assert state.endswith(ELLIPSIS)
        assert state.startswith("Forward simulation: 7.3kWh forecast")

    def test_the_full_reason_is_in_full_text(self):
        sensor = _sensor(_description("overnight_charge_reason"), self._data())

        assert sensor.extra_state_attributes[ATTR_FULL_TEXT] == _LOGGED_REASON


class TestReportsUseTheFullText:
    def test_the_charge_plan_html_holds_the_whole_reason(self):
        data = _engine_data(plugged_in=False)
        reason = data.charge_decision.reason
        assert len(reason) > STATE_MAX_LENGTH

        assert reason in build_charge_plan_html(data)

    def test_the_report_states_fit(self):
        data = _saturated()
        data.immersion_configured = True

        for text in (
            build_charge_plan_state(data),
            build_today_summary_state(data),
            build_week_summary_state(data),
        ):
            assert len(text) <= STATE_MAX_LENGTH
