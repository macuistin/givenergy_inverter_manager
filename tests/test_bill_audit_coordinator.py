"""The coordinator feeds the bill audit: the tariff of the day that ended, and the audit sensors."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from custom_components.givenergy_inverter_manager.accumulation import AccumulationStore
from custom_components.givenergy_inverter_manager.const import CONF_BASE_RATE, CONF_TARIFF_CHANGES
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from tests.test_coordinator import FakeCoordinator, _cfg

NEW_BASE = 0.55


def _change(effective: str) -> dict:
    return {
        "effective": effective,
        CONF_BASE_RATE: NEW_BASE,
        "base_rate_name": "Day",
        "export_rate": 0.2,
        "rate_periods": [],
    }


def _coord(*changes: dict) -> FakeCoordinator:
    coord = FakeCoordinator(cfg=_cfg(**({CONF_TARIFF_CHANGES: list(changes)} if changes else {})))
    # The real store, so the midnight reset runs the code that adds the day to the period.
    with patch(
        "custom_components.givenergy_inverter_manager.accumulation._create_store",
        return_value=MagicMock(),
    ):
        coord._acc = AccumulationStore(MagicMock(), 16)
    coord._acc.state.today.import_kwh = 4.0
    coord._acc.state.today.import_kwh_by_period = {"Day": 4.0}
    coord._acc.state.today.import_cost_by_period = {"Day": 1.6}
    coord.hass.async_create_task = lambda coro: coro.close()
    coord._register_charge_target_listener = MagicMock()
    return coord


def _midnight(coord: FakeCoordinator, day: str) -> None:
    coord._midnight_reset(datetime.fromisoformat(day).replace(tzinfo=timezone.utc))


def test_the_row_for_the_finished_day_is_added_with_the_tariff_in_force_that_day():
    coord = _coord()

    _midnight(coord, "2026-10-14")

    [row] = coord._acc.state.bill_days
    assert row["date"] == "2026-10-13"
    assert row["tariff"]["base_rate"] == 0.3334


def test_a_change_that_starts_on_the_new_day_does_not_price_the_day_that_ended():
    coord = _coord(_change("2026-10-14"))

    _midnight(coord, "2026-10-14")

    assert coord._acc.state.bill_days[0]["tariff"]["base_rate"] == 0.3334


def test_a_change_that_started_before_the_day_that_ended_prices_it():
    coord = _coord(_change("2026-10-10"))

    _midnight(coord, "2026-10-14")

    assert coord._acc.state.bill_days[0]["tariff"]["base_rate"] == NEW_BASE


def test_the_audit_sensors_are_filled_each_cycle():
    coord = _coord()
    data = CoordinatorData()
    now = datetime(2026, 10, 20, 12, 0)

    coord._attach_bill_audit(data, coord._effective_cfg(), now)

    assert data.bill_audit_state.startswith("Bill €")
    assert "This bill period" in data.bill_audit_html
    assert data.previous_bill_audit_state == "Not recorded"
