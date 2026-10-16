"""
services.py — service actions for GivEnergy Inverter Manager.

Registers the appliance, tariff, ROI, year-on-year, export and the two dashboard actions. The
dashboard YAML action returns the generated dashboard as text, to paste into a dashboard's raw
configuration editor. The update dashboard action writes it into a storage dashboard the user
picked, and remembers that dashboard so the out-of-date repair (stored_dashboard_repair.py) can
offer the same update later. Nothing is written to a dashboard without one of those two clicks.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

import yaml
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError

from .const import (
    CONF_STORED_DASHBOARD_URL_PATH,
    DOMAIN,
    SERVICE_COMPARE_TARIFF,
    SERVICE_EXPORT_ENERGY_DATA,
    SERVICE_GET_DASHBOARD_YAML,
    SERVICE_GET_ROI_SUMMARY,
    SERVICE_SUGGEST_APPLIANCE,
    SERVICE_UPDATE_DASHBOARD,
    SERVICE_YEAR_ON_YEAR,
)
from .controls import async_set_option
from .core.rules import ApplianceRequest, RateContext, SiteReadings, suggest_appliance_run
from .core.stored_dashboard import (
    DashboardFacts,
    DashboardRefused,
    as_stored,
    choose_url_path,
    ensure_writable,
)
from .core.tariff import BillBreakdown, TariffConfig, build_tariff
from .dashboard import async_host_facts, build_dashboard
from .logging import get_logger
from .repairs import async_delete_dashboard_out_of_date_issue

_LOG = get_logger(__name__)

_EXPORT_FILENAME = "givenergy_energy_export.csv"
DASHBOARD_FILENAME = "givenergy_dashboard.yaml"
DASHBOARD_BACKUP_FILENAME = "givenergy_dashboard_backup.yaml"
# Lovelace's default dashboard. Newer releases list it under this URL path, older ones under None.
_DEFAULT_DASHBOARD = "lovelace"


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

    The dashboard strategy uses the same entry.
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
            translation_key="config_file_write_failed",
        ) from err
    return file_path


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
    last_year = _same_month_last_year(snapshots[-_MONTHS_NEEDED])
    return {
        "snapshots_available": len(snapshots),
        "no_data": False,
        "current_month": current,
        "last_year_same_month": last_year,
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


# ── get_dashboard_yaml ───────────────────────────────────────────────────────


async def _caller_is_admin(hass: HomeAssistant, call: ServiceCall) -> bool:
    """True when a Home Assistant administrator ran the action.

    A call with no user, such as an automation, gets the dashboard without Settings.
    """
    user_id = call.context.user_id
    user = await hass.auth.async_get_user(user_id) if user_id else None
    return bool(user and user.is_admin)


def _make_dashboard_yaml_handler(hass: HomeAssistant):
    """Return the get_dashboard_yaml service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Return the dashboard the strategy builds, as YAML text.

        The file is written only when the call asks for it with write_file.
        """
        entry = primary_entry(hass)
        facts = await async_host_facts(hass, is_admin=await _caller_is_admin(hass, call))
        config = build_dashboard(hass, entry, facts)
        text = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
        response: dict = {"yaml": text, "views": len(config.get("views", []))}
        if call.data.get("write_file"):
            response["file"] = await _write_config_file(hass, DASHBOARD_FILENAME, text)
        return response

    return handle


# ── update_dashboard ─────────────────────────────────────────────────────────


def _lovelace_dashboards(hass: HomeAssistant) -> Mapping[str | None, Any]:
    """The dashboards Lovelace holds, by URL path. Empty while Lovelace is not loaded."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA  # noqa: PLC0415

    data = hass.data.get(LOVELACE_DATA)
    return {} if data is None else data.dashboards


def lovelace_is_loaded(hass: HomeAssistant) -> bool:
    """True once Lovelace has read its dashboards, so a missing one is really missing."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA  # noqa: PLC0415

    return hass.data.get(LOVELACE_DATA) is not None


def _find_dashboard(hass: HomeAssistant, url_path: str) -> Any | None:
    """The Lovelace dashboard at *url_path*, looked up the way the frontend does."""
    dashboards = _lovelace_dashboards(hass)
    if url_path == _DEFAULT_DASHBOARD:
        return dashboards.get(_DEFAULT_DASHBOARD) or dashboards.get(None)
    return dashboards.get(url_path)


async def _saved_config(dashboard: Any) -> dict | None:
    """The dashboard's saved configuration, or None while it has none."""
    from homeassistant.components.lovelace.const import ConfigNotFound  # noqa: PLC0415

    try:
        return await dashboard.async_load(False)
    except ConfigNotFound:
        return None


async def async_dashboard_facts(hass: HomeAssistant, url_path: str) -> DashboardFacts:
    """Whether a dashboard exists at *url_path*, its mode and, in storage mode, its config."""
    from homeassistant.components.lovelace.const import MODE_STORAGE  # noqa: PLC0415

    dashboard = _find_dashboard(hass, url_path)
    if dashboard is None:
        return DashboardFacts(exists=False)
    if dashboard.mode != MODE_STORAGE:
        return DashboardFacts(exists=True)
    return DashboardFacts(exists=True, storage_mode=True, config=await _saved_config(dashboard))


async def async_admin_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """The dashboard get_dashboard_yaml returns to an administrator, as storage would hold it."""
    facts = await async_host_facts(hass, is_admin=True)
    return as_stored(build_dashboard(hass, entry, facts))


def stored_dashboard_url_path(entry: ConfigEntry) -> str:
    """The URL path of the dashboard kept current, or an empty string when there is none."""
    return entry.options.get(CONF_STORED_DASHBOARD_URL_PATH) or ""


def _refused(err: DashboardRefused) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=err.refusal.value,
        translation_placeholders={"url_path": err.url_path},
    )


async def _writable_target(hass: HomeAssistant, entry: ConfigEntry, url_path: str | None):
    """The URL path to write and what it holds now, or a translated refusal."""
    try:
        target = choose_url_path(url_path, stored_dashboard_url_path(entry))
        facts = await async_dashboard_facts(hass, target)
        ensure_writable(target, facts, recovery_mode=hass.config.recovery_mode)
    except DashboardRefused as err:
        raise _refused(err) from err
    return target, facts


async def _back_up(hass: HomeAssistant, config: Mapping | None) -> str | None:
    """Write the config being replaced to the backup file and return its path."""
    if config is None:
        return None
    text = yaml.safe_dump(as_stored(config), sort_keys=False, allow_unicode=True)
    return await _write_config_file(hass, DASHBOARD_BACKUP_FILENAME, text)


def _remember(hass: HomeAssistant, entry: ConfigEntry, url_path: str) -> None:
    if stored_dashboard_url_path(entry) != url_path:
        async_set_option(hass, entry, CONF_STORED_DASHBOARD_URL_PATH, url_path)


def forget_stored_dashboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Stop keeping a dashboard current."""
    async_set_option(hass, entry, CONF_STORED_DASHBOARD_URL_PATH, "")


async def async_update_stored_dashboard(hass: HomeAssistant, url_path: str | None) -> dict:
    """Write the generated dashboard into a storage dashboard, and keep that one current.

    The dashboard is the one *url_path* names, else the one written last time. Its current
    config is first saved to the backup file. The action and the repair's fix both come here.
    """
    entry = primary_entry(hass)
    target, facts = await _writable_target(hass, entry, url_path)
    config = await async_admin_dashboard(hass, entry)
    backup = await _back_up(hass, facts.config)
    await _find_dashboard(hass, target).async_save(config)
    _remember(hass, entry, target)
    async_delete_dashboard_out_of_date_issue(hass)
    _LOG.info("Wrote the GivEnergy dashboard to /%s", target)
    return {"url_path": target, "views": len(config["views"]), "backup_file": backup}


def _make_update_dashboard_handler(hass: HomeAssistant):
    """Return the update_dashboard service handler bound to *hass*."""

    async def handle(call: ServiceCall) -> dict:
        """Write the generated dashboard into the storage dashboard the call names."""
        require_loaded_entries(hass)
        if not await _caller_is_admin(hass, call):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="dashboard_update_needs_admin",
            )
        return await async_update_stored_dashboard(hass, call.data.get("url_path"))

    return handle


# ── registration ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _ServiceSpec:
    """One service action: its name, handler factory and response support."""

    name: str
    make_handler: Callable[[HomeAssistant], Callable]
    response: SupportsResponse | None = None


_SERVICES = (
    _ServiceSpec(SERVICE_SUGGEST_APPLIANCE, _make_suggest_appliance_handler),
    _ServiceSpec(SERVICE_GET_ROI_SUMMARY, _make_roi_summary_handler, SupportsResponse.OPTIONAL),
    _ServiceSpec(SERVICE_COMPARE_TARIFF, _make_compare_tariff_handler, SupportsResponse.OPTIONAL),
    _ServiceSpec(SERVICE_YEAR_ON_YEAR, _make_year_on_year_handler, SupportsResponse.OPTIONAL),
    _ServiceSpec(SERVICE_EXPORT_ENERGY_DATA, _make_export_handler, SupportsResponse.OPTIONAL),
    _ServiceSpec(SERVICE_GET_DASHBOARD_YAML, _make_dashboard_yaml_handler, SupportsResponse.ONLY),
    _ServiceSpec(
        SERVICE_UPDATE_DASHBOARD, _make_update_dashboard_handler, SupportsResponse.OPTIONAL
    ),
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
