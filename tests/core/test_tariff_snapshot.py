"""The tariff snapshot stored with a bill period: only what prices a bill, as a copy."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.core.tariff_snapshot import tariff_snapshot
from tests.conftest import _nightboost_cfg


def test_it_keeps_only_what_prices_a_bill():
    snap = tariff_snapshot({**_nightboost_cfg(), "target_soc_entity": "number.x"})

    assert "target_soc_entity" not in snap
    assert snap["base_rate"] == 0.3334
    assert [p["name"] for p in snap["rate_periods"]] == ["Night", "Nightboost"]
    assert snap["standing_charge_per_day"] == 0.8259
    assert snap["bill_start_day"] == 16


def test_a_snapshot_is_a_copy_of_the_options():
    cfg = _nightboost_cfg()
    snap = tariff_snapshot(cfg)

    snap["rate_periods"][0]["rate"] = 99
    assert cfg["rate_periods"][0]["rate"] != 99
