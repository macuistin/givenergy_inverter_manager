# Configuration

Every setup step and every option, with ranges and defaults taken from the config flow.

- **Setup** is a six-step wizard: inverter, tariff, forecast, immersion, EV, battery.
- **Configure** opens a single options page with collapsible sections. Saving it reloads the integration.
- **Reconfigure** edits the tariff only.

Some fields are missing a label in the forms. They show their key name instead, for example `forecast_entity_p10`. The tables below give the key in that case.

## Setup

### Step 1: Inverter

The integration looks for a GivTCP inverter by its `sensor.givtcp_<id>_invertor_serial_number` entity. GivTCP spells "inverter" as "invertor". For each inverter found it looks for these entities, all with the same `givtcp_<id>_` prefix:

| Purpose | Entity suffix | Required |
|---|---|---|
| Solar power | `sensor..._pv_power` | yes |
| Battery SoC | `sensor..._soc` (GivTCP v3) or `sensor..._battery_soc` (v2) | yes |
| Battery power | `sensor..._battery_power` | yes |
| Grid power | `sensor..._grid_power` | yes |
| House load | `sensor..._load_power` | yes |
| Battery capacity | `sensor..._battery_capacity_kwh` | no, pre-fills the capacity |
| Inverter temperature | `sensor..._invertor_temperature` | no |
| Target SoC | `number..._target_soc` | no, needed to write charge targets |
| Enable charge target | `switch..._enable_charge_target` | no, needed to write charge targets |
| Enable charge schedule | `switch..._enable_charge_schedule` | no, needed to write charge targets |
| Charge start and end, slot 1 | `select..._charge_start_time_slot_1` and `..._charge_end_time_slot_1` | no, needed to write charge targets |

If the five required power sensors are found, the form shows only three fields and fills the entity IDs itself.

| Field | Default | Range |
|---|---|---|
| Detected inverter | The best match | A detected inverter, or Manual entry |
| Battery capacity (kWh) | From GivTCP, else 10 | 1 to 100 |
| Inverter max output (kW) | 5.0 | 1 to 20 |

If a required sensor is missing, or you pick Manual entry, the form also asks for the five power sensors. Leaving one empty shows the error "One or more required inverter entities are missing."

The charge control entities are never asked for. They come from discovery only. Without all of them the integration still calculates a target, but it cannot write it. The tariff step shows how many of the five were detected. An inverter is added once: its serial number is the unique ID.

### Step 2: Tariff

| Field | Default | Range |
|---|---|---|
| Base rate (daytime / standard) | 0.3334 | 0 to 5 per kWh |
| Base rate name | Day | text |
| Export / CEG rate | 0.195 | 0 to 1 per kWh |
| Standing charge per day | 0.8259 | 0 to 5 |
| PSO levy per month | 1.46 | 0 to 20 |
| VAT rate (%) | 9.0 | 0 to 30 |
| Supplier discount (%) | 5.5 | 0 to 20 |
| Bill start day of month | 1 | 1 to 28 |
| Currency | EUR | EUR, GBP, USD, SEK, NOK, DKK, AUD, CAD, NZD, ZAR |
| Rate period 1 to 5 | Night and Nightboost in slots 1 and 2 | name, rate, window start, window end |

The defaults are Electric Ireland Home Electric with Nightboost. Replace all of them. The rate fields say EUR/kWh whatever currency you pick. The currency only changes the symbol on money sensors. See [Tariff](tariff.md) for how periods and bill figures work.

### Step 3: Forecast and carbon (optional)

| Field | Key | Notes |
|---|---|---|
| Forecast provider | `forecast_provider` | Forecast.Solar or Solcast. Stored, but nothing reads it. The integration uses the sensors below |
| Tomorrow's forecast sensor | `forecast_entity` | A sensor giving tomorrow's expected energy in kWh |
| Solcast P10 sensor | `forecast_entity_p10` | Optional. A pessimistic forecast in kWh, blended in when conservatism is above 0 |
| Day-after-tomorrow sensor | `forecast_entity_d2` | Optional. Read each cycle but not used by the charge calculation in v0.3.0 |
| Grid carbon intensity sensor | `carbon_intensity_entity` | Optional. g CO2/kWh. Feeds the two carbon sensors |
| Forecast conservatism | `forecast_conservatism` | Slider 0 to 1 in steps of 0.05, default 0.35. 0 is the plain forecast, 1 is the P10 value |

With no forecast sensor, the charge calculation uses a seasonal estimate from your latitude.

### Step 4: Immersion (optional)

| Field | Default | Range |
|---|---|---|
| Immersion switch | none | a `switch` entity |
| Element wattage (W) | 3000 | 500 to 6000 |
| Water temperature sensor | none | a `sensor` entity |
| Target temperature (°C) | 55 | 40 to 75 |
| Minimum temperature (°C) | 50 | 30 to 60 |

The restart gap (default 5 °C) is not in the form. Change it with the Immersion Restart Gap number. See [Entities](entities.md).

### Step 5: EV charger (optional)

| Field | Default | Range |
|---|---|---|
| Detected charger | none | The chargers found, or None / Manual entry |
| Car efficiency (kWh/100km) | 15 | 5 to 40 |

The coordinator finds the charger itself, whatever you pick here. Car efficiency converts the energy delivered to the car into kilometres.

### Step 6: Battery

| Field | Key | Default | Range |
|---|---|---|---|
| Minimum battery SoC | `battery_min_soc_pct` | 10 | 5 to 30 |
| Cheap rate floor | `cheap_rate_floor_soc` | 40 | 0 to 80 in steps of 5. 0 turns it off |
| Default overnight charge target | `overnight_charge_target_pct` | 80 | 20 to 100 |
| Skip charge if SoC above | `skip_charge_soc_threshold_pct` | 75 | 20 to 100 |
| Immersion divert: minimum battery SoC | `surplus_divert_soc_pct` | 80 | 50 to 100 in steps of 5 |
| Immersion divert: minimum solar surplus (W) | `surplus_divert_min_power_w` | 500 | 100 to 2000 in steps of 100 |

The two immersion divert fields can only be set here. The options page does not have them. To change them later, remove and re-add the integration.

## Options

Open **Settings → Devices & Services → GivEnergy Inverter Manager → Configure**. Saving reloads the integration, so entities are unavailable for a few seconds. Saved options override the values entered at setup.

### Tariff

Same fields as setup step 2. Rate periods 1 to 5 sit in their own sections below the tariff section. See [Tariff](tariff.md).

### Battery & charging thresholds

| Field | Key | Default | Range |
|---|---|---|---|
| Minimum battery SoC | `battery_min_soc_pct` | 10 | 5 to 30 |
| Cheap rate floor (%) | `cheap_rate_floor_soc` | 40 | 0 to 80 in steps of 5. 0 turns it off |
| Default overnight charge target | `overnight_charge_target_pct` | 80 | 20 to 100. The calculated target is capped at this |
| Skip charge if SoC above | `skip_charge_soc_threshold_pct` | 75 | 20 to 100 |
| Battery cost | `battery_cost_eur` | 0 | 0 to 20000 in steps of 100. 0 turns the wear check off |
| Daily battery throughput budget (kWh) | `battery_throughput_budget_kwh` | 0 | 0 to 50 in steps of 0.5. 0 turns the budget sensors off |
| Dry run mode | `dry_run` | off | Decisions and sensors update, nothing is sent |
| Verbose logging | `verbose_logging` | off | Detailed per-cycle log lines |

- **Battery cost** sets a wear cost per kWh: cost divided by (2 x capacity x 6000 rated cycles). The immersion rule then refuses to divert when the export rate is lower than that wear cost. It also feeds Net Saving Today and Battery Cycle Cost per kWh.
- **Throughput budget** drives Battery Throughput Budget Used and Status. Status is OK below 80% of the budget, High from 80%, and Over budget above 100%.
- **Verbose logging** writes at debug level. Also enable debug logging for the integration, or the lines will not appear. See [Troubleshooting](troubleshooting.md#a-charge-decision-looks-wrong).
- A minimum SoC above 30 (possible only from older saved values) raises a repair issue, because on skip nights that value is written as the charge target.

### Hardware

| Field | Key | Default | Range |
|---|---|---|---|
| Battery capacity | `battery_capacity_kwh` | from setup | 1 to 100 kWh |
| Inverter max output | `inverter_max_output_kw` | from setup | 1 to 20 kW |
| Immersion element power | `immersion_wattage_w` | from setup | 500 to 6000 W |

Update these when you add battery modules, change the inverter, or replace the element.

### Solar forecast

| Field | Key |
|---|---|
| Forecast provider | `forecast_provider` |
| Tomorrow's forecast sensor | `forecast_entity` |
| Solcast P10 sensor | `forecast_entity_p10` |
| Day-after-tomorrow sensor | `forecast_entity_d2` |
| Grid carbon intensity sensor | `carbon_intensity_entity` |
| Forecast conservatism | `forecast_conservatism` |

Details as in setup step 3. Clear an entity field to remove the saved entity.

### Electric vehicle

| Field | Key | Default | Range |
|---|---|---|---|
| Car efficiency (kWh/100km) | `car_efficiency_kwh_per_100km` | 15 | 5 to 40 |

## Reconfigure

**Settings → Devices & Services → GivEnergy Inverter Manager → ⋮ → Reconfigure** shows the tariff form and saves it to the setup data. To change inverter entities, remove and re-add the integration.

Saved options override setup data. After you have saved the Configure page once, it holds a full copy of the tariff, so Reconfigure no longer changes the tariff. Use Configure instead.

## Things to know

- **Bill start day.** The month totals reset on the bill start day saved at setup or in Reconfigure. A different day saved on the options page changes the day counts in the bill sensors but not the month reset.
- **Immersion temperatures.** Target, minimum and restart gap are changed with number entities, not the options page. See [Entities](entities.md).
- **Forecast provider.** The choice is stored and not used. Set the sensors.
