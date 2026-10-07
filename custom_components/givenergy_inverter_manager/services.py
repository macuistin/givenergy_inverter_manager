"""
services.py — service actions for GivEnergy Inverter Manager.

Registers the get_dashboard_yaml action, which writes the generated dashboard
(see the dashboard package) to givenergy_dashboard.yaml in the config directory,
and the appliance, tariff, ROI, year-on-year and export actions.

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
from collections.abc import Callable
from dataclasses import dataclass, replace

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError

from .const import (
    DOMAIN,
    SERVICE_COMPARE_TARIFF,
    SERVICE_EXPORT_ENERGY_DATA,
    SERVICE_GET_DASHBOARD_YAML,
    SERVICE_GET_ROI_SUMMARY,
    SERVICE_SUGGEST_APPLIANCE,
    SERVICE_YEAR_ON_YEAR,
)
from .core.rules import ApplianceRequest, RateContext, SiteReadings, suggest_appliance_run
from .core.tariff import BillBreakdown, TariffConfig, build_tariff
from .dashboard import async_host_facts, render_dashboard
from .logging import get_logger

_LOG = get_logger(__name__)

DASHBOARD_FILENAME = "givenergy_dashboard.yaml"
_EXPORT_FILENAME = "givenergy_energy_export.csv"


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


def primary_entry(hass: HomeAssistant) -> ConfigEntry:
    """Return the entry an action without an entry selector acts on: the first loaded one.

    The dashboard action and the dashboard strategy use the same entry.
    """
    return require_loaded_entries(hass)[0]


def _notification(hass: HomeAssistant, title: str, message: str, notification_id: str):
    """Return the awaitable that creates a persistent notification, without waiting on it."""
    return hass.services.async_call(
        "persistent_notification",
        "create",
        {"title": title, "message": message, "notification_id": notification_id},
        blocking=False,
    )


async def _write_config_file(hass: HomeAssistant, filename: str, content: str) -> str:
    """Write *content* to *filename* in the config directory and return the path."""
    file_path = os.path.join(hass.config.config_dir, filename)

    def write() -> None:
        with open(file_path, "w", encoding="utf-8") as fh:
            fh.write(content)

    try:
        await hass.async_add_executor_job(write)
    except OSError as err:
        _LOG.error("Failed to write %s: %s", file_path, err)
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="dashboard_write_failed",
        ) from err
    return file_path


# ── get_dashboard_yaml ───────────────────────────────────────────────────────

_APPLY_STEPS = (
    "**To apply (UI mode):**\n"
    "1. Settings → Dashboards → Add Dashboard → Blank\n"
    "2. Three-dot menu → Edit dashboard → Raw configuration editor\n"
    f"3. Paste the contents of `{DASHBOARD_FILENAME}`\n\n"
    "**To apply (YAML mode):** add to `configuration.yaml`:\n"
    "```yaml\n"
    "lovelace:\n"
    "  dashboards:\n"
    "    givenergy:\n"
    "      mode: yaml\n"
    f"      filename: {DASHBOARD_FILENAME}\n"
    "      title: GivEnergy Inverter Manager\n"
    "      icon: mdi:solar-power-variant\n"
    "      show_in_sidebar: true\n"
    "```\n\n"
    "Run this action again after you change the tariff or rename entities. "
    "Adding or removing an EV charger or immersion device needs no new file."
)


def _ready_message(file_path: str, skipped: list[str]) -> str:
    """Return the notification text shown after the dashboard file is written."""
    message = f"Dashboard written to `{file_path}`.\n\n{_APPLY_STEPS}"
    if skipped:
        message += (
            "\n\nLeft out because the sensors are disabled: "
            + ", ".join(skipped)
            + ". Enable them under Settings → Devices & services → Entities, "
            "then run this action again."
        )
    return message


def _make_get_dashboard_yaml_handler(hass: HomeAssistant):
    """Return the get_dashboard_yaml service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> None:
        """Write the generated dashboard to the config directory."""
        entry = primary_entry(hass)
        facts = await async_host_facts(hass)
        yaml_output, skipped = render_dashboard(hass, entry, facts)
        file_path = await _write_config_file(hass, DASHBOARD_FILENAME, yaml_output)
        _LOG.info("Dashboard YAML written to %s", file_path)
        await _notification(
            hass,
            "GivEnergy Dashboard Ready",
            _ready_message(file_path, skipped),
            "givenergy_dashboard_yaml",
        )

    return handle


# ── suggest_appliance_run ────────────────────────────────────────────────────


def _appliance_arguments(
    coordinator, service_data
) -> tuple[SiteReadings, ApplianceRequest, RateContext]:
    """Return the three arguments of suggest_appliance_run for the live readings."""
    data = coordinator.data
    return (
        SiteReadings(
            solar_power_w=data.solar_power_w,
            house_load_w=data.house_load_w,
            battery_soc=data.battery_soc,
            battery_power_w=data.battery_power_w,
        ),
        ApplianceRequest(
            name=service_data["appliance_name"],
            power_w=float(service_data["appliance_power_w"]),
        ),
        RateContext(
            period_name=data.current_rate_name,
            rate=data.current_rate,
            export_rate=coordinator.export_rate,
            currency_symbol=data.currency_symbol,
        ),
    )


def _make_suggest_appliance_handler(hass: HomeAssistant):
    """Return the suggest_appliance_run service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> None:
        """Evaluate whether now is a good time to run a high-load appliance."""
        coordinator = primary_entry(hass).runtime_data
        if coordinator.data is None:
            return
        appliance_name: str = call.data["appliance_name"]
        recommended, reason = suggest_appliance_run(*_appliance_arguments(coordinator, call.data))
        verdict = "Good time to run" if recommended else "Not recommended right now"
        hass.async_create_task(
            _notification(
                hass,
                f"Appliance Suggestion — {appliance_name}",
                f"**{verdict}**\n\n{reason}",
                f"givenergy_appliance_{appliance_name.lower().replace(' ', '_')}",
            )
        )
        _LOG.info("Appliance suggestion for %r: %s — %s", appliance_name, verdict, reason)

    return handle


# ── get_roi_summary ──────────────────────────────────────────────────────────


def _flows(acc) -> dict:
    """Return the solar, export and import energy of one period."""
    return {
        "solar_kwh": round(acc.solar_kwh, 3),
        "export_kwh": round(acc.export_kwh, 3),
        "import_kwh": round(acc.import_kwh, 3),
    }


def _money(acc) -> dict:
    """Return the import cost, export earnings and net position of one period."""
    return {
        "import_cost": round(acc.total_import_cost, 4),
        "export_earnings": round(acc.export_earnings, 4),
        "net_position": round(acc.net_position, 4),
    }


def _today_summary(d) -> dict:
    """Return today's flows and money, with the self-consumption saving."""
    today = d.today
    self_consumed_kwh = max(0.0, today.solar_kwh - today.export_kwh)
    avg_import_rate = (
        today.total_import_cost / today.import_kwh if today.import_kwh > 0 else d.current_rate
    )
    export_rate = today.export_earnings / today.export_kwh if today.export_kwh > 0 else 0.0
    saving = self_consumed_kwh * max(0.0, avg_import_rate - export_rate)
    return {
        **_flows(today),
        "self_consumed_kwh": round(self_consumed_kwh, 3),
        "self_consumption_saving": round(saving, 4),
        **_money(today),
        "battery_throughput_kwh": round(today.battery_throughput_kwh, 3),
        "self_sufficiency_pct": round(today.self_sufficiency_pct, 1),
    }


def _roi_summary(d) -> dict:
    """Return ROI metrics for today, week, month and year, and battery health."""
    return {
        "today": _today_summary(d),
        "week": {**_flows(d.week), **_money(d.week)},
        "month": {**_flows(d.month), **_money(d.month)},
        "year": {**_flows(d.year), "export_earnings": round(d.year.export_earnings, 4)},
        "battery": {
            "total_cycles": round(d.battery_stats.total_cycles, 2),
            "remaining_life_pct": round(d.battery_stats.estimated_remaining_life_pct, 1),
            "throughput_today_kwh": round(d.today.battery_throughput_kwh, 3),
        },
    }


def _make_roi_summary_handler(hass: HomeAssistant):
    """Return the get_roi_summary service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Return ROI metrics for today/week/month/year and battery health."""
        coordinator = primary_entry(hass).runtime_data
        if coordinator.data is None:
            return {}
        return _roi_summary(coordinator.data)

    return handle


# ── compare_tariff ───────────────────────────────────────────────────────────


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


def _alternative_tariff(tariff: TariffConfig, data) -> TariffConfig:
    """Return the configured tariff with the service call's flat-rate overrides applied."""
    overrides = {
        "standing_charge": float(data.get("standing_charge", 0.0)),
        "export_rate": float(data.get("export_rate", 0.0)),
    }
    for field_name in ("discount_rate", "vat_rate", "pso_levy"):
        if data.get(field_name) is not None:
            overrides[field_name] = float(data[field_name])
    return replace(tariff, **overrides)


def _month_bills(d, tariff: TariffConfig, alt_tariff: TariffConfig, alt_rate: float):
    """Return this period's bill on the configured tariff and on the flat-rate alternative."""
    days = d.days_in_period
    period_days = days + d.days_remaining
    current = tariff.calculate_bill(
        tariff.energy_cost_from_import_cost(d.month.total_import_cost),
        days,
        period_days,
        d.month.export_earnings,
    )
    alternative = alt_tariff.calculate_bill(
        d.month.import_kwh * alt_rate,
        days,
        period_days,
        d.month.export_kwh * alt_tariff.export_rate,
    )
    return current, alternative


def _compare_tariff_for_entry(coordinator, data) -> dict:
    """Compare one entry's bill period so far with a flat-rate alternative.

    Both sides go through TariffConfig.calculate_bill, so energy, supplier saving,
    standing charge, PSO levy, VAT and export credit are worked out the same way.
    """
    d = coordinator.data
    tariff = build_tariff(coordinator._effective_cfg())
    alt_tariff = _alternative_tariff(tariff, data)
    alt_rate = float(data["rate"])
    current_bill, alt_bill = _month_bills(d, tariff, alt_tariff, alt_rate)

    current = _bill_side(current_bill, tariff)
    current["pso_levy_per_period"] = tariff.pso_levy
    alternative = _bill_side(alt_bill, alt_tariff)
    alternative.update(
        {
            "rate": alt_rate,
            "standing_charge_per_day": alt_tariff.standing_charge,
            "export_rate": alt_tariff.export_rate,
            "pso_levy_per_period": alt_tariff.pso_levy,
        }
    )
    return {
        "period_days": d.days_in_period,
        "period_length_days": d.days_in_period + d.days_remaining,
        "import_kwh": round(d.month.import_kwh, 3),
        "export_kwh": round(d.month.export_kwh, 3),
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


# ── year_on_year_summary ─────────────────────────────────────────────────────

_MONTHS_NEEDED = 12
_COMPARED_KEYS = ("solar_kwh", "import_kwh", "export_kwh", "import_cost", "export_earnings")


def _current_month(d) -> dict:
    """Return this billing month's totals."""
    return {
        "solar_kwh": round(d.month.solar_kwh, 3),
        "import_kwh": round(d.month.import_kwh, 3),
        "export_kwh": round(d.month.export_kwh, 3),
        "import_cost": round(d.month.total_import_cost, 4),
        "export_earnings": round(d.month.export_earnings, 4),
        "self_sufficiency_pct": round(d.month.self_sufficiency_pct, 1),
    }


def _same_month_last_year(snapshot: dict) -> dict:
    """Return the totals of the snapshot taken twelve billing months ago."""
    return {
        "solar_kwh": round(float(snapshot.get("solar_kwh", 0.0)), 3),
        "import_kwh": round(float(snapshot.get("import_kwh", 0.0)), 3),
        "export_kwh": round(float(snapshot.get("export_kwh", 0.0)), 3),
        "import_cost": round(sum(snapshot.get("import_cost_by_period", {}).values()), 4),
        "export_earnings": round(float(snapshot.get("export_earnings", 0.0)), 4),
        "self_sufficiency_pct": round(
            float(snapshot.get("solar_kwh", 0.0))
            / max(1.0, float(snapshot.get("house_kwh", 1.0)))
            * 100,
            1,
        ),
    }


def _delta(current: dict, snapshot: dict, key: str) -> float:
    """Return how much *key* changed since the snapshot."""
    curr_val = current.get(key, 0.0) or 0.0
    prev_val = float(snapshot.get(key, 0.0) or 0.0)
    return round(curr_val - prev_val, 4)


def _delta_pct(current: dict, snapshot: dict, key: str) -> float | None:
    """Return the percentage change of *key* since the snapshot, or None from a zero base."""
    prev_val = float(snapshot.get(key, 0.0) or 0.0)
    if prev_val == 0:
        return None
    return round((current.get(key, 0.0) - prev_val) / prev_val * 100, 1)


def _not_enough_history(available: int, current: dict) -> dict:
    """Return the response while fewer than twelve billing months are stored."""
    return {
        "snapshots_available": available,
        "snapshots_needed": _MONTHS_NEEDED,
        "no_data": True,
        "message": (
            f"Year-on-year comparison requires {_MONTHS_NEEDED} completed billing months. "
            f"{available} available. "
            f"Full comparison will be ready in {_MONTHS_NEEDED - available} more billing cycles."
        ),
        "current_month": current,
    }


def _year_on_year(d, snapshots: list[dict]) -> dict:
    """Compare this billing month with the same month one year ago."""
    current = _current_month(d)
    if len(snapshots) < _MONTHS_NEEDED:
        return _not_enough_history(len(snapshots), current)
    last_year = snapshots[-_MONTHS_NEEDED]
    return {
        "snapshots_available": len(snapshots),
        "no_data": False,
        "current_month": current,
        "last_year_same_month": _same_month_last_year(last_year),
        "delta": {key: _delta(current, last_year, key) for key in _COMPARED_KEYS},
        "delta_pct": {key: _delta_pct(current, last_year, key) for key in _COMPARED_KEYS},
    }


def _make_year_on_year_handler(hass: HomeAssistant):
    """Return the year_on_year_summary service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Compare current billing month against the same month one year ago."""
        coordinator = primary_entry(hass).runtime_data
        if coordinator.data is None:
            return {}
        snapshots: list[dict] = getattr(coordinator._acc, "monthly_snapshots", [])
        return _year_on_year(coordinator.data, snapshots)

    return handle


# ── export_energy_data ───────────────────────────────────────────────────────

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


def _export_rows(d, snapshots: list[dict]) -> list[str]:
    """Return the CSV header, the five period rows, then one row per stored month."""
    rows = [
        _CSV_HEADER,
        _acc_to_csv_row("today", d.today),
        _acc_to_csv_row("yesterday", d.yesterday),
        _acc_to_csv_row("this_week", d.week),
        _acc_to_csv_row("this_month", d.month),
        _acc_to_csv_row("this_year", d.year),
    ]
    rows += [_snapshot_to_csv_row(idx, snap) for idx, snap in enumerate(reversed(snapshots), 1)]
    return rows


def _export_message(file_path: str, n_rows: int, n_snapshots: int) -> str:
    """Return the notification text shown after the energy export is written."""
    months = f", and {n_snapshots} completed billing months." if n_snapshots else "."
    return (
        f"Exported {n_rows} rows to `{file_path}`.\n\n"
        f"Rows: today, yesterday, this_week, this_month, this_year{months}"
    )


def _make_export_handler(hass: HomeAssistant):
    """Return the export_energy_data service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Export energy history to /config/givenergy_energy_export.csv."""
        coordinator = primary_entry(hass).runtime_data
        if coordinator.data is None:
            return {"file": None, "rows_written": 0, "header": _CSV_HEADER, "rows": []}

        snapshots: list[dict] = getattr(coordinator._acc, "monthly_snapshots", [])
        rows = _export_rows(coordinator.data, snapshots)
        file_path = await _write_config_file(hass, _EXPORT_FILENAME, "\n".join(rows) + "\n")

        n_rows = len(rows) - 1
        _LOG.info("Energy data exported to %s (%d rows)", file_path, n_rows)
        await _notification(
            hass,
            "GivEnergy Energy Export Complete",
            _export_message(file_path, n_rows, len(snapshots)),
            "givenergy_energy_export",
        )
        return {
            "file": file_path,
            "rows_written": n_rows,
            "header": _CSV_HEADER,
            "rows": rows[1:],
        }

    return handle


# ── registration ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _ServiceSpec:
    """One service action: its name, handler factory and response support."""

    name: str
    make_handler: Callable[[HomeAssistant], Callable]
    response: SupportsResponse | None = None


_SERVICES = (
    _ServiceSpec(SERVICE_GET_DASHBOARD_YAML, _make_get_dashboard_yaml_handler),
    _ServiceSpec(SERVICE_SUGGEST_APPLIANCE, _make_suggest_appliance_handler),
    _ServiceSpec(SERVICE_GET_ROI_SUMMARY, _make_roi_summary_handler, SupportsResponse.OPTIONAL),
    _ServiceSpec(SERVICE_COMPARE_TARIFF, _make_compare_tariff_handler, SupportsResponse.OPTIONAL),
    _ServiceSpec(SERVICE_YEAR_ON_YEAR, _make_year_on_year_handler, SupportsResponse.OPTIONAL),
    _ServiceSpec(SERVICE_EXPORT_ENERGY_DATA, _make_export_handler, SupportsResponse.OPTIONAL),
)


def _register(hass: HomeAssistant, spec: _ServiceSpec) -> None:
    """Register one service action."""
    options = {} if spec.response is None else {"supports_response": spec.response}
    hass.services.async_register(DOMAIN, spec.name, spec.make_handler(hass), **options)
    _LOG.debug("Registered service %s.%s", DOMAIN, spec.name)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's service actions."""
    for spec in _SERVICES:
        _register(hass, spec)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister services when the integration is unloaded."""
    for spec in _SERVICES:
        hass.services.async_remove(DOMAIN, spec.name)
