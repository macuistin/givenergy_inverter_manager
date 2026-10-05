"""
dashboard.py — services for GivEnergy Inverter Manager.

Registers the get_dashboard_yaml service, which writes the generated dashboard
(see dashboard_builder.py) to givenergy_dashboard.yaml in the config directory,
and the appliance, tariff, ROI, year-on-year and export services.

How to use the dashboard:
  1. Developer Tools → Actions → givenergy_inverter_manager.get_dashboard_yaml
  2. Click Perform Action
  3. Copy the YAML from givenergy_dashboard.yaml
  4. Settings → Dashboards → New dashboard (Blank)
  5. Three-dot menu → Edit dashboard → Raw configuration editor
  6. Paste, save
"""

from __future__ import annotations

import os
from dataclasses import replace

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN
from .core.rules import suggest_appliance_run
from .core.tariff import BillBreakdown, TariffConfig, build_tariff
from .dashboard_builder import (
    SERVICE_GET_DASHBOARD_YAML,
    async_lovelace_resource_urls,
    render_dashboard,
)
from .logging import get_logger

_LOG = get_logger(__name__)

SERVICE_SUGGEST_APPLIANCE = "suggest_appliance_run"
SERVICE_COMPARE_TARIFF = "compare_tariff"
SERVICE_YEAR_ON_YEAR = "year_on_year_summary"
SERVICE_EXPORT_ENERGY_DATA = "export_energy_data"
SERVICE_GET_ROI_SUMMARY = "get_roi_summary"


def loaded_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Return the config entries of this integration that are currently loaded."""
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


def require_loaded_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Return the loaded entries, or raise when none is loaded."""
    if not (entries := loaded_entries(hass)):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_config_entry",
        )
    return entries


def _make_roi_summary_handler(hass: HomeAssistant):
    """Return the get_roi_summary service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Return ROI metrics for today/week/month/year and battery health."""
        entries = require_loaded_entries(hass)
        coordinator = entries[0].runtime_data
        if coordinator.data is None:
            return {}
        d = coordinator.data
        self_consumed_kwh = max(0.0, d.today.solar_kwh - d.today.export_kwh)
        avg_import_rate = (
            d.today.total_import_cost / d.today.import_kwh
            if d.today.import_kwh > 0
            else d.current_rate
        )
        export_rate = (
            d.today.export_earnings / d.today.export_kwh if d.today.export_kwh > 0 else 0.0
        )
        self_consumption_saving = self_consumed_kwh * max(0.0, avg_import_rate - export_rate)
        return {
            "today": {
                "solar_kwh": round(d.today.solar_kwh, 3),
                "export_kwh": round(d.today.export_kwh, 3),
                "import_kwh": round(d.today.import_kwh, 3),
                "self_consumed_kwh": round(self_consumed_kwh, 3),
                "self_consumption_saving": round(self_consumption_saving, 4),
                "import_cost": round(d.today.total_import_cost, 4),
                "export_earnings": round(d.today.export_earnings, 4),
                "net_position": round(d.today.net_position, 4),
                "battery_throughput_kwh": round(d.today.battery_throughput_kwh, 3),
                "self_sufficiency_pct": round(d.today.self_sufficiency_pct, 1),
            },
            "week": {
                "solar_kwh": round(d.week.solar_kwh, 3),
                "export_kwh": round(d.week.export_kwh, 3),
                "import_kwh": round(d.week.import_kwh, 3),
                "import_cost": round(d.week.total_import_cost, 4),
                "export_earnings": round(d.week.export_earnings, 4),
                "net_position": round(d.week.net_position, 4),
            },
            "month": {
                "solar_kwh": round(d.month.solar_kwh, 3),
                "export_kwh": round(d.month.export_kwh, 3),
                "import_kwh": round(d.month.import_kwh, 3),
                "import_cost": round(d.month.total_import_cost, 4),
                "export_earnings": round(d.month.export_earnings, 4),
                "net_position": round(d.month.net_position, 4),
            },
            "year": {
                "solar_kwh": round(d.year.solar_kwh, 3),
                "export_kwh": round(d.year.export_kwh, 3),
                "import_kwh": round(d.year.import_kwh, 3),
                "export_earnings": round(d.year.export_earnings, 4),
            },
            "battery": {
                "total_cycles": round(d.battery_stats.total_cycles, 2),
                "remaining_life_pct": round(d.battery_stats.estimated_remaining_life_pct, 1),
                "throughput_today_kwh": round(d.today.battery_throughput_kwh, 3),
            },
        }

    return handle


def _bill_side(bill: BillBreakdown, tariff: TariffConfig) -> dict:
    """Return one side of a tariff comparison from a bill breakdown."""
    import_cost = (bill.energy - bill.supplier_saving) * (1 + tariff.vat_rate / 100)
    before_export = bill.before_vat + bill.vat
    return {
        "import_cost": round(import_cost, 4),
        "standing_charges": round(before_export - import_cost, 4),
        "export_earnings": round(bill.export_credit, 4),
        "net_cost": round(bill.total, 4),
        "discount_rate": tariff.discount_rate,
        "vat_rate": tariff.vat_rate,
        "bill": {
            "energy": bill.energy,
            "supplier_saving": bill.supplier_saving,
            "standing_charge": bill.standing_charge,
            "pso_levy": bill.pso_levy,
            "vat": bill.vat,
            "export_credit": bill.export_credit,
            "total": bill.total,
        },
    }


def _compare_tariff_for_entry(coordinator, data) -> dict:
    """Compare one entry's bill period so far with a flat-rate alternative.

    Both sides go through TariffConfig.calculate_bill, so energy, supplier saving,
    standing charge, PSO levy, VAT and export credit are worked out the same way.
    """
    d = coordinator.data
    tariff = build_tariff(coordinator._effective_cfg())
    alt_rate = float(data["rate"])
    alt_standing = float(data.get("standing_charge", 0.0))
    alt_export_rate = float(data.get("export_rate", 0.0))
    overrides = {
        "standing_charge": alt_standing,
        "export_rate": alt_export_rate,
    }
    for field_name in ("discount_rate", "vat_rate", "pso_levy"):
        if data.get(field_name) is not None:
            overrides[field_name] = float(data[field_name])
    alt_tariff = replace(tariff, **overrides)

    days = d.days_in_period
    period_days = days + d.days_remaining
    import_kwh = d.month.import_kwh
    export_kwh = d.month.export_kwh

    current_bill = tariff.calculate_bill(
        tariff.energy_cost_from_import_cost(d.month.total_import_cost),
        days,
        period_days,
        d.month.export_earnings,
    )
    alt_bill = alt_tariff.calculate_bill(
        import_kwh * alt_rate, days, period_days, export_kwh * alt_export_rate
    )
    current = _bill_side(current_bill, tariff)
    alternative = _bill_side(alt_bill, alt_tariff)
    alternative.update(
        {
            "rate": alt_rate,
            "standing_charge_per_day": alt_standing,
            "export_rate": alt_export_rate,
            "pso_levy_per_period": alt_tariff.pso_levy,
        }
    )
    current["pso_levy_per_period"] = tariff.pso_levy
    return {
        "period_days": days,
        "period_length_days": period_days,
        "import_kwh": round(import_kwh, 3),
        "export_kwh": round(export_kwh, 3),
        "current_tariff": current,
        "comparison_tariff": alternative,
        "saving": round(current_bill.total - alt_bill.total, 4),
    }


def _make_compare_tariff_handler(hass: HomeAssistant):
    """Return the compare_tariff service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Compare the current bill period against a flat-rate alternative tariff.

        Service data fields:
          rate            - flat import rate of the comparison tariff (EUR/kWh, required)
          standing_charge - daily standing charge of the comparison tariff (EUR/day, default 0)
          export_rate     - export rate of the comparison tariff (EUR/kWh, default 0)
          discount_rate   - supplier discount in percent (default: the configured tariff's)
          vat_rate        - VAT in percent (default: the configured tariff's)
          pso_levy        - PSO levy per bill period (default: the configured tariff's)

        The top level of the response describes the first loaded entry. With more than
        one entry set up, "entries" lists every entry's comparison.
        """
        results = []
        for entry in require_loaded_entries(hass):
            coordinator = entry.runtime_data
            if coordinator.data is None:
                continue
            result = _compare_tariff_for_entry(coordinator, call.data)
            result["entry_id"] = entry.entry_id
            result["title"] = entry.title
            results.append(result)
        if not results:
            return {}
        return {**results[0], "entries": results}

    return handle


def _make_year_on_year_handler(hass: HomeAssistant):
    """Return the year_on_year_summary service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Compare current billing month against the same month one year ago."""
        entries = require_loaded_entries(hass)
        coordinator = entries[0].runtime_data
        if coordinator.data is None:
            return {}

        d = coordinator.data
        snapshots: list[dict] = getattr(coordinator._acc, "monthly_snapshots", [])
        n_snapshots = len(snapshots)

        current = {
            "solar_kwh": round(d.month.solar_kwh, 3),
            "import_kwh": round(d.month.import_kwh, 3),
            "export_kwh": round(d.month.export_kwh, 3),
            "import_cost": round(d.month.total_import_cost, 4),
            "export_earnings": round(d.month.export_earnings, 4),
            "self_sufficiency_pct": round(d.month.self_sufficiency_pct, 1),
        }

        if n_snapshots < 12:
            return {
                "snapshots_available": n_snapshots,
                "snapshots_needed": 12,
                "no_data": True,
                "message": (
                    f"Year-on-year comparison requires 12 completed billing months. "
                    f"{n_snapshots} available. "
                    f"Full comparison will be ready in {12 - n_snapshots} more billing cycles."
                ),
                "current_month": current,
            }

        last_year = snapshots[-12]

        def _delta(key: str) -> float:
            curr_val = current.get(key, 0.0) or 0.0
            prev_val = float(last_year.get(key, 0.0) or 0.0)
            return round(curr_val - prev_val, 4)

        def _delta_pct(key: str) -> float | None:
            prev_val = float(last_year.get(key, 0.0) or 0.0)
            if prev_val == 0:
                return None
            return round((current.get(key, 0.0) - prev_val) / prev_val * 100, 1)

        return {
            "snapshots_available": n_snapshots,
            "no_data": False,
            "current_month": current,
            "last_year_same_month": {
                "solar_kwh": round(float(last_year.get("solar_kwh", 0.0)), 3),
                "import_kwh": round(float(last_year.get("import_kwh", 0.0)), 3),
                "export_kwh": round(float(last_year.get("export_kwh", 0.0)), 3),
                "import_cost": round(
                    sum(last_year.get("import_cost_by_period", {}).values()), 4
                ),
                "export_earnings": round(float(last_year.get("export_earnings", 0.0)), 4),
                "self_sufficiency_pct": round(
                    float(last_year.get("solar_kwh", 0.0))
                    / max(1.0, float(last_year.get("house_kwh", 1.0)))
                    * 100,
                    1,
                ),
            },
            "delta": {
                "solar_kwh": _delta("solar_kwh"),
                "import_kwh": _delta("import_kwh"),
                "export_kwh": _delta("export_kwh"),
                "import_cost": _delta("import_cost"),
                "export_earnings": _delta("export_earnings"),
            },
            "delta_pct": {
                "solar_kwh": _delta_pct("solar_kwh"),
                "import_kwh": _delta_pct("import_kwh"),
                "export_kwh": _delta_pct("export_kwh"),
                "import_cost": _delta_pct("import_cost"),
                "export_earnings": _delta_pct("export_earnings"),
            },
        }

    return handle


_CSV_HEADER = (
    "period,solar_kwh,import_kwh,export_kwh,battery_throughput_kwh,"
    "import_cost,export_earnings,net_position,self_sufficiency_pct"
)


def _acc_to_csv_row(period: str, acc) -> str:
    """Format one EnergyAccumulator as a CSV row."""
    import_cost = getattr(acc, "total_import_cost", 0.0)
    export_earn = getattr(acc, "export_earnings", 0.0)
    net = export_earn - import_cost
    ss = getattr(acc, "self_sufficiency_pct", 0.0)
    return (
        f"{period},"
        f"{round(acc.solar_kwh, 3)},"
        f"{round(acc.import_kwh, 3)},"
        f"{round(acc.export_kwh, 3)},"
        f"{round(acc.battery_throughput_kwh, 3)},"
        f"{round(import_cost, 4)},"
        f"{round(export_earn, 4)},"
        f"{round(net, 4)},"
        f"{round(ss, 1)}"
    )


def _snapshot_to_csv_row(index: int, snap: dict) -> str:
    """Format one monthly snapshot dict as a CSV row."""
    import_cost = sum((snap.get("import_cost_by_period") or {}).values())
    export_earn = snap.get("export_earnings", 0.0)
    net = (export_earn or 0.0) - import_cost
    solar = snap.get("solar_kwh", 0.0) or 0.0
    house = snap.get("house_kwh", 0.0) or 1.0
    ss = min(100.0, (solar / house) * 100) if house > 0 else 0.0
    return (
        f"month_snapshot_{index:02d},"
        f"{round(snap.get('solar_kwh', 0.0) or 0.0, 3)},"
        f"{round(snap.get('import_kwh', 0.0) or 0.0, 3)},"
        f"{round(snap.get('export_kwh', 0.0) or 0.0, 3)},"
        f"{round(snap.get('battery_throughput_kwh', 0.0) or 0.0, 3)},"
        f"{round(import_cost, 4)},"
        f"{round(export_earn or 0.0, 4)},"
        f"{round(net, 4)},"
        f"{round(ss, 1)}"
    )


def _make_export_handler(hass: HomeAssistant):
    """Return the export_energy_data service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Export energy history to /config/givenergy_energy_export.csv."""
        entries = require_loaded_entries(hass)
        coordinator = entries[0].runtime_data
        if coordinator.data is None:
            return {"file": None, "rows_written": 0, "header": _CSV_HEADER, "rows": []}

        d = coordinator.data
        rows = [_CSV_HEADER]
        rows.append(_acc_to_csv_row("today", d.today))
        rows.append(_acc_to_csv_row("yesterday", d.yesterday))
        rows.append(_acc_to_csv_row("this_week", d.week))
        rows.append(_acc_to_csv_row("this_month", d.month))
        rows.append(_acc_to_csv_row("this_year", d.year))

        snapshots: list[dict] = getattr(coordinator._acc, "monthly_snapshots", [])
        for idx, snap in enumerate(reversed(snapshots), 1):
            rows.append(_snapshot_to_csv_row(idx, snap))

        csv_content = "\n".join(rows) + "\n"
        file_path = os.path.join(hass.config.config_dir, "givenergy_energy_export.csv")

        def _write() -> None:
            with open(file_path, "w", encoding="utf-8") as fh:
                fh.write(csv_content)

        try:
            await hass.async_add_executor_job(_write)
        except OSError as err:
            _LOG.error("Failed to write energy export %s: %s", file_path, err)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="dashboard_write_failed",
            ) from err

        n_rows = len(rows) - 1
        _LOG.info("Energy data exported to %s (%d rows)", file_path, n_rows)
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "GivEnergy Energy Export Complete",
                "message": (
                    f"Exported {n_rows} rows to `{file_path}`.\n\n"
                    "Rows: today, yesterday, this_week, this_month, this_year"
                    + (
                        f", and {len(snapshots)} completed billing months."
                        if snapshots
                        else "."
                    )
                ),
                "notification_id": "givenergy_energy_export",
            },
            blocking=False,
        )
        return {
            "file": file_path,
            "rows_written": n_rows,
            "header": _CSV_HEADER,
            "rows": rows[1:],
        }

    return handle


async def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's service actions."""

    async def handle_get_dashboard_yaml(call: ServiceCall) -> None:
        """Write dashboard YAML to /config/givenergy_dashboard.yaml."""
        entries = require_loaded_entries(hass)

        entry = entries[0]
        resources = await async_lovelace_resource_urls(hass)
        yaml_output, skipped = render_dashboard(hass, entry.entry_id, resources)

        file_path = os.path.join(hass.config.config_dir, "givenergy_dashboard.yaml")

        def _write_file() -> None:
            with open(file_path, "w", encoding="utf-8") as fh:
                fh.write(yaml_output)

        try:
            await hass.async_add_executor_job(_write_file)
        except OSError as err:
            _LOG.error("Failed to write dashboard file %s: %s", file_path, err)
            raise ServiceValidationError(
                translation_domain="givenergy_inverter_manager",
                translation_key="dashboard_write_failed",
            ) from err

        _LOG.info("Dashboard YAML written to %s", file_path)

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "GivEnergy Dashboard Ready",
                "message": (
                    f"Dashboard written to `{file_path}`.\n\n"
                    "**To apply (UI mode):**\n"
                    "1. Settings → Dashboards → Add Dashboard → Blank\n"
                    "2. Three-dot menu → Edit dashboard → Raw configuration editor\n"
                    "3. Paste the contents of `givenergy_dashboard.yaml`\n\n"
                    "**To apply (YAML mode):** add to `configuration.yaml`:\n"
                    "```yaml\n"
                    "lovelace:\n"
                    "  dashboards:\n"
                    "    givenergy:\n"
                    "      mode: yaml\n"
                    "      filename: givenergy_dashboard.yaml\n"
                    "      title: GivEnergy Inverter Manager\n"
                    "      icon: mdi:solar-power-variant\n"
                    "      show_in_sidebar: true\n"
                    "```\n\n"
                    "Run this action again after reconfiguring to regenerate the file."
                    + (
                        "\n\nLeft out because the sensors are disabled: "
                        + ", ".join(skipped)
                        + ". Enable them under Settings → Devices & services → Entities, "
                        "then run this action again."
                        if skipped
                        else ""
                    )
                ),
                "notification_id": "givenergy_dashboard_yaml",
            },
            blocking=False,
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DASHBOARD_YAML,
        handle_get_dashboard_yaml,
    )
    _LOG.debug("Registered service %s.%s", DOMAIN, SERVICE_GET_DASHBOARD_YAML)

    async def handle_suggest_appliance(call) -> None:
        """Evaluate whether now is a good time to run a high-load appliance."""
        entries = require_loaded_entries(hass)
        coordinator = entries[0].runtime_data
        if coordinator.data is None:
            return

        appliance_name: str = call.data["appliance_name"]
        appliance_power_w: float = float(call.data["appliance_power_w"])
        data = coordinator.data

        recommended, reason = suggest_appliance_run(
            solar_power_w=data.solar_power_w,
            house_load_w=data.house_load_w,
            battery_soc=data.battery_soc,
            battery_power_w=data.battery_power_w,
            appliance_power_w=appliance_power_w,
            appliance_name=appliance_name,
            rate_period_name=data.current_rate_name,
            rate=data.current_rate,
            export_rate=coordinator.export_rate,
        )

        verdict = "Good time to run" if recommended else "Not recommended right now"
        notification_id = f"givenergy_appliance_{appliance_name.lower().replace(' ', '_')}"
        hass.async_create_task(
            hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"Appliance Suggestion — {appliance_name}",
                    "message": f"**{verdict}**\n\n{reason}",
                    "notification_id": notification_id,
                },
                blocking=False,
            )
        )
        _LOG.info(
            "Appliance suggestion for %r: %s — %s",
            appliance_name,
            verdict,
            reason,
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SUGGEST_APPLIANCE,
        handle_suggest_appliance,
    )
    _LOG.debug("Registered service %s.%s", DOMAIN, SERVICE_SUGGEST_APPLIANCE)

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ROI_SUMMARY,
        _make_roi_summary_handler(hass),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _LOG.debug("Registered service %s.%s", DOMAIN, SERVICE_GET_ROI_SUMMARY)

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPARE_TARIFF,
        _make_compare_tariff_handler(hass),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _LOG.debug("Registered service %s.%s", DOMAIN, SERVICE_COMPARE_TARIFF)

    hass.services.async_register(
        DOMAIN,
        SERVICE_YEAR_ON_YEAR,
        _make_year_on_year_handler(hass),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _LOG.debug("Registered service %s.%s", DOMAIN, SERVICE_YEAR_ON_YEAR)

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_ENERGY_DATA,
        _make_export_handler(hass),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _LOG.debug("Registered service %s.%s", DOMAIN, SERVICE_EXPORT_ENERGY_DATA)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister services when the integration is unloaded."""
    hass.services.async_remove(DOMAIN, SERVICE_GET_DASHBOARD_YAML)
    hass.services.async_remove(DOMAIN, SERVICE_SUGGEST_APPLIANCE)
    hass.services.async_remove(DOMAIN, SERVICE_GET_ROI_SUMMARY)
    hass.services.async_remove(DOMAIN, SERVICE_COMPARE_TARIFF)
    hass.services.async_remove(DOMAIN, SERVICE_YEAR_ON_YEAR)
    hass.services.async_remove(DOMAIN, SERVICE_EXPORT_ENERGY_DATA)
