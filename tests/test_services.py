"""Behaviour of the service actions, called through a fake Home Assistant."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError

from custom_components.givenergy_inverter_manager import services
from custom_components.givenergy_inverter_manager.const import DOMAIN
from custom_components.givenergy_inverter_manager.core.engine import CoordinatorData
from custom_components.givenergy_inverter_manager.core.tariff import EnergyAccumulator
from custom_components.givenergy_inverter_manager.dashboard import HostFacts
from tests.helpers import ROOT

ALL_SERVICES = {
    "get_dashboard_yaml",
    "suggest_appliance_run",
    "get_roi_summary",
    "compare_tariff",
    "year_on_year_summary",
    "export_energy_data",
}
RESPONSE_SERVICES = {
    "get_roi_summary",
    "compare_tariff",
    "year_on_year_summary",
    "export_energy_data",
}


def _data() -> CoordinatorData:
    data = CoordinatorData()
    data.solar_power_w = 3000.0
    data.house_load_w = 500.0
    data.battery_soc = 80.0
    data.battery_power_w = 100.0
    data.current_rate = 0.3
    data.current_rate_name = "Day"
    data.currency_symbol = "£"
    data.today.solar_kwh = 10.0
    data.today.export_kwh = 4.0
    data.today.import_kwh = 2.0
    return data


def _coordinator(data=None, snapshots=()):
    return SimpleNamespace(
        data=_data() if data is None else data,
        export_rate=0.15,
        _acc=SimpleNamespace(monthly_snapshots=list(snapshots)),
    )


def _entry(coordinator, entry_id="entry1"):
    return SimpleNamespace(
        runtime_data=coordinator,
        entry_id=entry_id,
        title="Home",
        state=ConfigEntryState.LOADED,
    )


class FakeHass:
    """The slice of Home Assistant the service handlers touch."""

    def __init__(self, entries, config_dir):
        self.hass = MagicMock()
        self.hass.config_entries.async_entries.return_value = entries
        self.hass.config.config_dir = str(config_dir)
        self.hass.services.async_call = AsyncMock()
        self.hass.async_create_task = lambda coroutine: coroutine.close()
        self.hass.async_add_executor_job = self._run_job
        self.registered: dict[str, dict] = {}
        self.hass.services.async_register = self._register
        asyncio.run(services.async_register_services(self.hass))

    @staticmethod
    async def _run_job(function, *args):
        return function(*args)

    def _register(self, domain, name, handler, **kwargs):
        assert domain == DOMAIN
        self.registered[name] = {"handler": handler, **kwargs}

    def call(self, name, **data):
        handler = self.registered[name]["handler"]
        return asyncio.run(handler(SimpleNamespace(data=data)))

    @property
    def notification(self) -> dict:
        args = self.hass.services.async_call.call_args.args
        assert args[:2] == ("persistent_notification", "create")
        return args[2]


@pytest.fixture
def home(tmp_path):
    return FakeHass([_entry(_coordinator())], tmp_path)


@pytest.fixture
def empty_home(tmp_path):
    return FakeHass([], tmp_path)


class TestRegistration:
    def test_every_action_is_registered(self, home):
        assert set(home.registered) == ALL_SERVICES

    def test_only_the_data_actions_return_a_response(self, home):
        returning = {n for n, r in home.registered.items() if "supports_response" in r}
        assert returning == RESPONSE_SERVICES

    def test_unregistering_removes_every_action(self):
        hass = MagicMock()
        services.async_unregister_services(hass)
        removed = {call.args[1] for call in hass.services.async_remove.call_args_list}
        assert removed == ALL_SERVICES


class TestNoLoadedEntry:
    @pytest.mark.parametrize("name", sorted(ALL_SERVICES))
    def test_every_action_raises_when_nothing_is_loaded(self, empty_home, name):
        data = {"appliance_name": "Oven", "appliance_power_w": 2000, "rate": 0.2}
        with pytest.raises(ServiceValidationError) as raised:
            empty_home.call(name, **data)
        assert raised.value.translation_key == "no_config_entry"
        assert raised.value.translation_domain == DOMAIN

    def test_require_loaded_entries_skips_entries_that_are_not_loaded(self):
        not_loaded = SimpleNamespace(state="setup_error")
        hass = MagicMock()
        hass.config_entries.async_entries.return_value = [not_loaded]
        with pytest.raises(ServiceValidationError):
            services.require_loaded_entries(hass)


class TestGetDashboardYaml:
    def _call(self, home, skipped=()):
        with (
            patch.object(services, "async_host_facts", AsyncMock(return_value=HostFacts())),
            patch.object(services, "render_dashboard", return_value=("views: []\n", list(skipped))),
        ):
            home.call("get_dashboard_yaml")

    def test_writes_the_rendered_yaml_to_the_config_directory(self, home, tmp_path):
        self._call(home)
        assert (tmp_path / "givenergy_dashboard.yaml").read_text() == "views: []\n"

    def test_notification_names_the_file_and_the_steps(self, home, tmp_path):
        self._call(home)
        note = home.notification
        assert note["notification_id"] == "givenergy_dashboard_yaml"
        assert str(tmp_path / "givenergy_dashboard.yaml") in note["message"]
        assert "Raw configuration editor" in note["message"]
        assert "Left out" not in note["message"]

    def test_notification_lists_the_sensors_left_out(self, home):
        self._call(home, skipped=["Battery Cycles", "Solar Clipping"])
        assert "Battery Cycles, Solar Clipping" in home.notification["message"]

    def test_unwritable_directory_raises_a_translated_error(self, tmp_path):
        home = FakeHass([_entry(_coordinator())], tmp_path / "missing")
        with pytest.raises(ServiceValidationError) as raised:
            self._call(home)
        assert raised.value.translation_key == "dashboard_write_failed"
        assert raised.value.translation_domain == DOMAIN


class TestSuggestAppliance:
    def _call(self, home, **data):
        data = {"appliance_name": "Dishwasher", "appliance_power_w": 2000} | data
        with patch.object(services, "suggest_appliance_run", return_value=(True, "ok")) as engine:
            home.call("suggest_appliance_run", **data)
        return engine

    def test_passes_the_live_readings_to_the_rule(self, home):
        site, appliance, rates = self._call(home).call_args.args
        assert site.solar_power_w == 3000.0
        assert site.house_load_w == 500.0
        assert site.battery_soc == 80.0
        assert site.battery_power_w == 100.0
        assert appliance.power_w == 2000.0
        assert appliance.name == "Dishwasher"
        assert rates.period_name == "Day"
        assert rates.rate == 0.3

    def test_export_rate_comes_from_the_coordinator(self, home):
        assert self._call(home).call_args.args[2].export_rate == 0.15

    def test_reply_uses_the_configured_currency_symbol(self, home):
        assert self._call(home).call_args.args[2].currency_symbol == "£"

    def test_notification_carries_the_verdict(self, home):
        self._call(home)
        note = home.notification
        assert note["title"].endswith("Dishwasher")
        assert note["message"] == "**Good time to run**\n\nok"
        assert note["notification_id"] == "givenergy_appliance_dishwasher"

    def test_negative_verdict_text(self, home):
        with patch.object(services, "suggest_appliance_run", return_value=(False, "no")):
            home.call("suggest_appliance_run", appliance_name="Oven", appliance_power_w=1)
        assert home.notification["message"].startswith("**Not recommended right now**")

    def test_does_nothing_before_the_first_update(self, tmp_path):
        home = FakeHass([_entry(SimpleNamespace(data=None))], tmp_path)
        assert home.call("suggest_appliance_run", appliance_name="Oven", appliance_power_w=1) is None
        home.hass.services.async_call.assert_not_called()


class TestRoiSummary:
    def test_reports_today_week_month_year_and_battery(self, home):
        result = home.call("get_roi_summary")
        assert set(result) == {"today", "week", "month", "year", "battery"}
        assert result["today"]["solar_kwh"] == 10.0
        assert result["today"]["self_consumed_kwh"] == 6.0

    def test_empty_before_the_first_update(self, tmp_path):
        home = FakeHass([_entry(SimpleNamespace(data=None))], tmp_path)
        assert home.call("get_roi_summary") == {}


class TestYearOnYear:
    def test_asks_for_more_history_under_twelve_months(self, tmp_path):
        home = FakeHass([_entry(_coordinator(snapshots=[{}] * 3))], tmp_path)
        result = home.call("year_on_year_summary")
        assert result["no_data"] is True
        assert result["snapshots_available"] == 3
        assert "9 more billing cycles" in result["message"]

    def test_compares_against_the_same_month_last_year(self, tmp_path):
        data = _data()
        data.month.solar_kwh = 100.0
        snapshots = [{"solar_kwh": 80.0, "house_kwh": 160.0}] * 12
        home = FakeHass([_entry(_coordinator(data, snapshots))], tmp_path)
        result = home.call("year_on_year_summary")
        assert result["no_data"] is False
        assert result["delta"]["solar_kwh"] == 20.0
        assert result["delta_pct"]["solar_kwh"] == 25.0
        assert result["last_year_same_month"]["self_sufficiency_pct"] == 50.0


class TestExportEnergyData:
    def test_writes_one_row_per_period_and_per_snapshot(self, tmp_path):
        snapshots = [{"solar_kwh": 45.0, "house_kwh": 90.0}] * 2
        home = FakeHass([_entry(_coordinator(snapshots=snapshots))], tmp_path)
        result = home.call("export_energy_data")
        path = tmp_path / "givenergy_energy_export.csv"
        lines = path.read_text().splitlines()
        assert lines[0] == services._CSV_HEADER
        assert [row.split(",")[0] for row in lines[1:]] == [
            "today",
            "yesterday",
            "this_week",
            "this_month",
            "this_year",
            "month_snapshot_01",
            "month_snapshot_02",
        ]
        assert result["rows_written"] == 7
        assert result["file"] == str(path)

    def test_notification_mentions_the_completed_months(self, tmp_path):
        home = FakeHass([_entry(_coordinator(snapshots=[{}]))], tmp_path)
        home.call("export_energy_data")
        assert home.notification["notification_id"] == "givenergy_energy_export"
        assert "1 completed billing months" in home.notification["message"]

    def test_unwritable_directory_raises_a_translated_error(self, tmp_path):
        home = FakeHass([_entry(_coordinator())], tmp_path / "missing")
        with pytest.raises(ServiceValidationError) as raised:
            home.call("export_energy_data")
        assert raised.value.translation_key == "dashboard_write_failed"

    def test_empty_response_before_the_first_update(self, tmp_path):
        home = FakeHass([_entry(SimpleNamespace(data=None))], tmp_path)
        result = home.call("export_energy_data")
        assert result == {
            "file": None,
            "rows_written": 0,
            "header": services._CSV_HEADER,
            "rows": [],
        }


class TestExportCsvHelpers:
    """Unit tests for the CSV export helper functions."""

    def test_acc_to_csv_row_format(self):
        acc = EnergyAccumulator()
        acc.solar_kwh = 12.5
        acc.import_kwh = 3.2
        acc.export_kwh = 2.1
        parts = services._acc_to_csv_row("today", acc).split(",")
        assert parts[0] == "today"
        assert float(parts[1]) == pytest.approx(12.5)
        assert float(parts[2]) == pytest.approx(3.2)
        assert float(parts[3]) == pytest.approx(2.1)

    def test_snapshot_to_csv_row_format(self):
        snap = {
            "solar_kwh": 45.0,
            "import_kwh": 20.0,
            "export_kwh": 10.0,
            "battery_throughput_kwh": 8.0,
            "export_earnings": 1.95,
            "import_cost_by_period": {"Night": 1.5, "Day": 2.0},
        }
        parts = services._snapshot_to_csv_row(1, snap).split(",")
        assert parts[0] == "month_snapshot_01"
        assert float(parts[1]) == pytest.approx(45.0)  # solar_kwh
        assert float(parts[5]) == pytest.approx(3.5)  # import_cost (1.5 + 2.0)

    def test_csv_header_fields(self):
        fields = services._CSV_HEADER.split(",")
        assert fields[0] == "period"
        assert "solar_kwh" in fields
        assert "import_cost" in fields
        assert "net_position" in fields


GOLDEN = ROOT / "tests" / "golden_services.json"


def _filled(scale: float) -> EnergyAccumulator:
    acc = EnergyAccumulator()
    acc.solar_kwh = 10.0 * scale
    acc.import_kwh = 7.0 * scale
    acc.export_kwh = 3.0 * scale
    acc.house_kwh = 14.0 * scale
    acc.battery_throughput_kwh = 4.0 * scale
    acc.export_earnings = 0.6 * scale
    acc.import_cost_by_period = {"Day": 1.4 * scale, "Night": 0.5 * scale}
    return acc


def _full_data() -> CoordinatorData:
    data = _data()
    data.today = _filled(1.0)
    data.yesterday = _filled(0.9)
    data.week = _filled(6.0)
    data.month = _filled(25.0)
    data.year = _filled(300.0)
    data.battery_stats.total_cycles = 123.456
    data.days_in_period = 12
    data.days_remaining = 18
    return data


def _snapshots() -> list[dict]:
    return [
        {
            "solar_kwh": 200.0 + month,
            "import_kwh": 150.0 + month,
            "export_kwh": 60.0 + month,
            "house_kwh": 400.0,
            "battery_throughput_kwh": 80.0 + month,
            "export_earnings": 12.5,
            "import_cost_by_period": {"Day": 30.0, "Night": 9.5 + month},
        }
        for month in range(12)
    ]


class TestPinnedOutput:
    """The exact responses and notification text, so a refactor cannot change them."""

    @pytest.fixture(scope="class")
    def golden(self):
        return json.loads(GOLDEN.read_text())

    @staticmethod
    def _home(tmp_path, snapshots=()):
        coordinator = _coordinator(_full_data(), snapshots)
        return FakeHass([_entry(coordinator)], tmp_path)

    def test_roi_summary(self, tmp_path, golden):
        assert self._home(tmp_path).call("get_roi_summary") == golden["roi_summary"]

    def test_year_on_year_without_enough_history(self, tmp_path, golden):
        home = self._home(tmp_path, _snapshots()[:5])
        assert home.call("year_on_year_summary") == golden["year_on_year_short"]

    def test_year_on_year_with_a_full_year(self, tmp_path, golden):
        home = self._home(tmp_path, _snapshots())
        assert home.call("year_on_year_summary") == golden["year_on_year_full"]

    def test_export_response_and_file(self, tmp_path, golden):
        home = self._home(tmp_path, _snapshots()[:3])
        result = home.call("export_energy_data")
        assert result["file"] == str(tmp_path / "givenergy_energy_export.csv")
        result["file"] = "<file>"
        assert result == golden["export_response"]
        assert (tmp_path / "givenergy_energy_export.csv").read_text() == golden["export_csv"]
        assert home.notification["message"] == golden["export_message"].replace("<dir>", str(tmp_path))

    def test_dashboard_notification_text(self, tmp_path, golden):
        home = self._home(tmp_path)
        with (
            patch.object(services, "async_host_facts", AsyncMock(return_value=HostFacts())),
            patch.object(services, "render_dashboard", return_value=("views: []\n", ["A", "B"])),
        ):
            home.call("get_dashboard_yaml")
        expected = golden["dashboard_message"].replace("<dir>", str(tmp_path))
        assert home.notification["message"] == expected
        assert home.notification["title"] == "GivEnergy Dashboard Ready"

    def test_appliance_suggestion_text(self, tmp_path, golden):
        home = self._home(tmp_path)
        home.call("suggest_appliance_run", appliance_name="Heat Pump", appliance_power_w=1500)
        assert home.notification["message"] == golden["appliance_message"]
