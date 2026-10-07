# Actions

The integration registers six actions under `givenergy_inverter_manager`. Run them from **Developer Tools → Actions**, or from scripts and automations.

- All six use the first loaded entry, and `compare_tariff` also lists every loaded entry. They stay registered while at least one entry is loaded. With no loaded entry, each one fails with the error "not configured".
- Four of them return data. Read it with `response_variable`.
- The examples use `action:`. Home Assistant releases before 2024.8 call it `service:`.

| Action | Fields | Returns |
|---|---|---|
| [`get_dashboard_yaml`](#get_dashboard_yaml) | none | nothing |
| [`suggest_appliance_run`](#suggest_appliance_run) | `appliance_name`, `appliance_power_w` | nothing |
| [`get_roi_summary`](#get_roi_summary) | none | ROI figures |
| [`compare_tariff`](#compare_tariff) | `rate`, optional `standing_charge`, `export_rate`, `discount_rate`, `vat_rate`, `pso_levy` | cost comparison |
| [`year_on_year_summary`](#year_on_year_summary) | none | month against last year |
| [`export_energy_data`](#export_energy_data) | none | file path and rows written |

## get_dashboard_yaml

Writes the Lovelace dashboard to `givenergy_dashboard.yaml` in the Home Assistant config folder, then shows the persistent notification **GivEnergy Dashboard Ready** with setup steps. The **Refresh Dashboard** button calls this action. See [Dashboard](dashboard.md).

- Entity IDs come from the entity registry, so renamed entities are picked up.
- It fails with "GivEnergy Inverter Manager is not configured" when no entry exists, and with a write error when the config folder is read-only.

```yaml
action: givenergy_inverter_manager.get_dashboard_yaml
```

## suggest_appliance_run

Checks whether now is a good time to run a large appliance. It creates a persistent notification with the verdict and the reason. It returns nothing.

| Field | Required | Notes |
|---|---|---|
| `appliance_name` | yes | Shown in the notification. Also sets the notification ID, so each appliance keeps its own |
| `appliance_power_w` | yes | Rated power in watts |

The rules, in order:

1. Net solar surplus (solar minus house load minus battery charging power) is at least the appliance power: good time.
2. Battery SoC is 80% or more and the current rate is no more than 1.5 times the export rate: acceptable time.
3. The current rate is more than 1.5 times the export rate: not recommended.
4. Anything else: no strong reason.

Nothing happens until the first update has completed.

```yaml
action: givenergy_inverter_manager.suggest_appliance_run
data:
  appliance_name: Dishwasher
  appliance_power_w: 1800
```

## get_roi_summary

Returns return-on-investment figures. The response is empty until the first update has completed. Values are rounded.

```yaml
action: givenergy_inverter_manager.get_roi_summary
response_variable: roi
```

Template example: `{{ roi.today.self_consumption_saving }}`.

| Block | Keys |
|---|---|
| `today` | `solar_kwh`, `export_kwh`, `import_kwh`, `self_consumed_kwh`, `self_consumption_saving`, `import_cost`, `export_earnings`, `net_position`, `battery_throughput_kwh`, `self_sufficiency_pct` |
| `week` and `month` | `solar_kwh`, `export_kwh`, `import_kwh`, `import_cost`, `export_earnings`, `net_position` |
| `year` | `solar_kwh`, `export_kwh`, `import_kwh`, `export_earnings` |
| `battery` | `total_cycles`, `remaining_life_pct`, `throughput_today_kwh` |

`self_consumed_kwh` is solar generated minus exported, floored at 0. `self_consumption_saving` is that energy times the difference between today's average import rate and today's average export rate, floored at 0. With nothing imported yet, the import rate is the current rate. With no export yet, the export rate is taken as 0. `net_position` is export earnings minus import cost.

The `year` block is saved over a restart and resets on 1 January.

## compare_tariff

Compares this bill period against a flat-rate alternative, using the kWh imported and exported since the bill period started. Both tariffs are billed the same way: energy, supplier saving, standing charge, PSO levy, VAT, then the export credit. See [Tariff](tariff.md#bill-sensors).

| Field | Required | Default | Notes |
|---|---|---|---|
| `rate` | yes | none | Import rate per kWh of the alternative, before discount and VAT |
| `standing_charge` | no | 0 | Daily standing charge of the alternative |
| `export_rate` | no | 0 | Export rate per kWh of the alternative |
| `discount_rate` | no | your tariff's | Supplier discount of the alternative, in percent |
| `vat_rate` | no | your tariff's | VAT of the alternative, in percent |
| `pso_levy` | no | your tariff's | Flat levy (the PSO levy field) of the alternative for a whole bill period |

The values below are examples. Use the rates of the tariff you want to compare.

```yaml
action: givenergy_inverter_manager.compare_tariff
data:
  rate: 0.28
  standing_charge: 0.65
  export_rate: 0.15
response_variable: comparison
```

Response keys: `period_days`, `period_length_days`, `import_kwh`, `export_kwh`, `current_tariff`, `comparison_tariff`, `saving`, `entry_id`, `title` and `entries`.

`current_tariff` and `comparison_tariff` both have `import_cost`, `standing_charges`, `export_earnings`, `net_cost`, `discount_rate`, `vat_rate` and `bill`. `bill` lists the line items: `energy`, `supplier_saving`, `standing_charge`, `pso_levy`, `vat`, `export_credit` and `total`. The alternative also has `rate`, `standing_charge_per_day`, `export_rate` and `pso_levy_per_period`.

How to read it:

- `import_cost` is energy less the supplier saving, with VAT. `standing_charges` is standing charge plus PSO levy, with VAT. `net_cost` is `import_cost + standing_charges - export_earnings`, which equals `bill.total`.
- The alternative uses your tariff's discount, VAT and PSO levy unless you set them in the call.
- `saving` is the current net cost minus the alternative's net cost. A positive number means the alternative is cheaper.
- `period_days` is the day of the bill period (1 on the bill start day). `period_length_days` is the whole period.
- The top level of the response is the first loaded entry. `entries` lists every loaded entry with its own `entry_id` and `title`, each compared against its own tariff.

## year_on_year_summary

Compares this bill period with the same period one year ago. It needs 12 completed bill periods. A snapshot is stored each time the month resets on the bill start day.

```yaml
action: givenergy_inverter_manager.year_on_year_summary
response_variable: yoy
```

While fewer than 12 snapshots exist, the response has `no_data: true`, `snapshots_available`, `snapshots_needed` (12), a `message`, and `current_month`.

With 12 or more, the response has `no_data: false`, `snapshots_available`, `current_month`, `last_year_same_month`, `delta` and `delta_pct`.

- `current_month` and `last_year_same_month` hold `solar_kwh`, `import_kwh`, `export_kwh`, `import_cost`, `export_earnings` and `self_sufficiency_pct`.
- `delta` and `delta_pct` cover the first five of those. `delta_pct` is empty where last year's value was 0.
- For the current month, `self_sufficiency_pct` is the share of house kWh that was not drawn from the grid, with grid energy stored in the battery left out of the import. For last year it is solar kWh divided by house kWh, a simpler measure, so the two are not directly comparable.

## export_energy_data

Writes `givenergy_energy_export.csv` to the Home Assistant config folder and shows the notification **GivEnergy Energy Export Complete**. The file is replaced each time.

```yaml
action: givenergy_inverter_manager.export_energy_data
response_variable: export
```

The response, when you ask for one, holds `file` (the path written), `rows_written`, `header` and `rows` (the data rows as CSV lines).

Columns: `period`, `solar_kwh`, `import_kwh`, `export_kwh`, `battery_throughput_kwh`, `import_cost`, `export_earnings`, `net_position`, `self_sufficiency_pct`.

Rows: `today`, `yesterday`, `this_week`, `this_month`, `this_year`, then one `month_snapshot_NN` row per completed bill period. `month_snapshot_01` is the most recent.

In snapshot rows, `self_sufficiency_pct` is solar divided by house energy, capped at 100.
