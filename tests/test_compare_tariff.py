"""compare_tariff: both tariffs are billed the same way, for every loaded entry."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError

from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from custom_components.givenergy_inverter_manager.services import _make_compare_tariff_handler

KEEP = (1 - 0.055) * 1.09
CFG = {
    "base_rate": 0.365,
    "base_rate_name": "Day",
    "rate_periods": [
        {"name": "Night", "rate": 0.18, "start": "23:00", "end": "08:00"},
        {"name": "Nightboost", "rate": 0.1056, "start": "02:00", "end": "04:00"},
    ],
    "export_rate": 0.195,
    "standing_charge_per_day": 0.8259,
    "pso_levy_per_month": 1.46,
    "vat_rate": 9.0,
    "discount_rate": 5.5,
    "bill_start_day": 16,
}
ENERGY = 154 * 0.1056 + 33 * 0.365 + 517 * 0.18


def _coordinator(cfg=None, days_in=31, days_remaining=0, scale=1.0):
    month = EnergyAccumulator()
    month.import_cost_by_period["Nightboost"] = 154 * 0.1056 * KEEP * scale
    month.import_cost_by_period["Day"] = 33 * 0.365 * KEEP * scale
    month.import_cost_by_period["Night"] = 517 * 0.18 * KEEP * scale
    month.import_kwh = 704.0 * scale
    month.export_kwh = 179.0 * scale
    month.export_earnings = 179 * 0.195 * scale
    data = CoordinatorData()
    data.month = month
    data.days_in_period = days_in
    data.days_remaining = days_remaining
    return SimpleNamespace(data=data, _effective_cfg=lambda: dict(cfg or CFG))


def _entry(coordinator, entry_id="entry1", title="Home"):
    return SimpleNamespace(
        runtime_data=coordinator, entry_id=entry_id, title=title, state=ConfigEntryState.LOADED
    )


def _call(hass_entries, **data):
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = hass_entries
    handler = _make_compare_tariff_handler(hass)
    return asyncio.run(handler(SimpleNamespace(data=data)))


class TestCurrentTariffSide:
    def test_current_tariff_reproduces_the_real_bill(self):
        result = _call([_entry(_coordinator())], rate=0.25)
        bill = result["current_tariff"]["bill"]
        assert bill["energy"] == 121.37
        assert bill["supplier_saving"] == 6.68
        assert bill["standing_charge"] == 25.60
        assert bill["pso_levy"] == 1.46
        assert bill["vat"] == 12.76
        assert bill["export_credit"] == 34.91
        assert bill["total"] == 119.60
        assert result["current_tariff"]["net_cost"] == 119.60

    def test_net_cost_includes_standing_charge_and_pso(self):
        result = _call([_entry(_coordinator())], rate=0.25)
        side = result["current_tariff"]
        assert side["standing_charges"] == pytest.approx((25.60 + 1.46) * 1.09, abs=0.01)
        assert side["import_cost"] + side["standing_charges"] - side["export_earnings"] == (
            pytest.approx(side["net_cost"], abs=1e-3)
        )

    def test_part_period_prorates_the_pso_over_the_real_period(self):
        coord = _coordinator(days_in=10, days_remaining=21, scale=10 / 31)
        bill = _call([_entry(coord)], rate=0.25)["current_tariff"]["bill"]
        assert bill["pso_levy"] == 0.47
        assert bill["standing_charge"] == 8.26


class TestLikeForLike:
    def test_identical_tariff_has_no_saving(self):
        result = _call(
            [_entry(_coordinator())],
            rate=ENERGY / 704.0,
            standing_charge=0.8259,
            export_rate=0.195,
        )
        assert result["saving"] == pytest.approx(0.0, abs=1e-9)
        assert result["comparison_tariff"]["net_cost"] == result["current_tariff"]["net_cost"]
        assert result["comparison_tariff"]["bill"] == result["current_tariff"]["bill"]

    def test_alternative_gets_discount_vat_and_pso_of_the_configured_tariff(self):
        result = _call([_entry(_coordinator())], rate=0.2, standing_charge=0.5, export_rate=0.1)
        alt = result["comparison_tariff"]
        assert alt["discount_rate"] == 5.5
        assert alt["vat_rate"] == 9.0
        assert alt["bill"]["energy"] == round(704 * 0.2, 2)
        assert alt["bill"]["supplier_saving"] == round(704 * 0.2 * 0.055, 2)
        assert alt["bill"]["pso_levy"] == 1.46
        assert alt["bill"]["standing_charge"] == round(0.5 * 31, 2)
        assert alt["bill"]["export_credit"] == round(179 * 0.1, 2)
        before_vat = (
            alt["bill"]["energy"]
            - alt["bill"]["supplier_saving"]
            + alt["bill"]["standing_charge"]
            + alt["bill"]["pso_levy"]
        )
        assert alt["bill"]["vat"] == pytest.approx(before_vat * 0.09, abs=0.006)

    def test_service_call_can_override_discount_vat_and_pso(self):
        result = _call(
            [_entry(_coordinator())],
            rate=0.2,
            discount_rate=0,
            vat_rate=13.5,
            pso_levy=2.0,
        )
        alt = result["comparison_tariff"]
        assert alt["discount_rate"] == 0.0
        assert alt["vat_rate"] == 13.5
        assert alt["bill"]["supplier_saving"] == 0.0
        assert alt["bill"]["pso_levy"] == 2.0
        assert result["current_tariff"]["discount_rate"] == 5.5

    def test_saving_is_current_minus_alternative(self):
        result = _call([_entry(_coordinator())], rate=0.1)
        assert result["saving"] == pytest.approx(
            result["current_tariff"]["net_cost"] - result["comparison_tariff"]["net_cost"]
        )
        assert result["saving"] > 0

    def test_zero_standing_default_is_kept(self):
        result = _call([_entry(_coordinator())], rate=0.2)
        assert result["comparison_tariff"]["standing_charge_per_day"] == 0.0
        assert result["comparison_tariff"]["bill"]["standing_charge"] == 0.0


class TestResponseShape:
    def test_existing_keys_are_kept(self):
        result = _call([_entry(_coordinator())], rate=0.25, standing_charge=0.6, export_rate=0.1)
        for key in ("period_days", "import_kwh", "export_kwh", "current_tariff", "saving"):
            assert key in result
        for key in ("import_cost", "export_earnings", "net_cost"):
            assert key in result["current_tariff"]
        for key in (
            "rate",
            "standing_charge_per_day",
            "export_rate",
            "import_cost",
            "standing_charges",
            "export_earnings",
            "net_cost",
        ):
            assert key in result["comparison_tariff"]
        assert result["period_days"] == 31
        assert result["period_length_days"] == 31
        assert result["import_kwh"] == 704.0
        assert result["export_kwh"] == 179.0

    def test_both_sides_report_the_same_line_items(self):
        result = _call([_entry(_coordinator())], rate=0.25)
        assert set(result["current_tariff"]["bill"]) == set(result["comparison_tariff"]["bill"])


class TestEntries:
    def test_no_loaded_entry_raises_no_config_entry(self):
        with pytest.raises(ServiceValidationError) as err:
            _call([], rate=0.25)
        assert err.value.translation_key == "no_config_entry"

    def test_entry_that_is_not_loaded_counts_as_no_entry(self):
        not_loaded = _entry(_coordinator())
        not_loaded.state = ConfigEntryState.NOT_LOADED
        with pytest.raises(ServiceValidationError):
            _call([not_loaded], rate=0.25)

    def test_entry_without_data_is_skipped(self):
        empty = SimpleNamespace(data=None, _effective_cfg=lambda: dict(CFG))
        assert _call([_entry(empty)], rate=0.25) == {}

    def test_two_entries_are_each_compared_against_their_own_tariff(self):
        other_cfg = {**CFG, "discount_rate": 0.0, "vat_rate": 0.0, "pso_levy_per_month": 0.0}
        first = _entry(_coordinator(), "e1", "House")
        second = _entry(_coordinator(cfg=other_cfg), "e2", "Annex")
        result = _call([first, second], rate=0.25)

        assert [e["entry_id"] for e in result["entries"]] == ["e1", "e2"]
        assert [e["title"] for e in result["entries"]] == ["House", "Annex"]
        assert result["current_tariff"] == result["entries"][0]["current_tariff"]
        assert result["entries"][0]["current_tariff"]["bill"]["total"] == 119.60
        annex_bill = result["entries"][1]["current_tariff"]["bill"]
        assert annex_bill["supplier_saving"] == 0.0
        assert annex_bill["vat"] == 0.0
        assert annex_bill["pso_levy"] == 0.0
        assert annex_bill["total"] != 119.60

    def test_second_entry_is_used_when_first_has_no_data(self):
        empty = SimpleNamespace(data=None, _effective_cfg=lambda: dict(CFG))
        result = _call([_entry(empty, "e1"), _entry(_coordinator(), "e2")], rate=0.25)
        assert result["entry_id"] == "e2"
        assert len(result["entries"]) == 1
