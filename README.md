# GivEnergy Inverter Manager

[![GitHub Release](https://img.shields.io/github/release/macuistin/givenergy_inverter_manager.svg?style=for-the-badge)](https://github.com/macuistin/givenergy_inverter_manager/releases)
[![GitHub Activity](https://img.shields.io/github/commit-activity/y/macuistin/givenergy_inverter_manager.svg?style=for-the-badge)](https://github.com/macuistin/givenergy_inverter_manager/commits/main)
[![License](https://img.shields.io/github/license/macuistin/givenergy_inverter_manager.svg?style=for-the-badge)](LICENSE)
[![hacs](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
[![Tests](https://img.shields.io/github/actions/workflow/status/macuistin/givenergy_inverter_manager/tests.yml?style=for-the-badge&label=Tests)](https://github.com/macuistin/givenergy_inverter_manager/actions/workflows/tests.yml)

A Home Assistant custom integration for GivEnergy inverters — smart overnight charge optimisation, solar surplus diversion to immersion and EV, and multi-period energy cost tracking. Communicates locally via GivTCP over MQTT. No cloud account required.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=macuistin&repository=givenergy_inverter_manager&category=integration)

---

## What it does

- **Overnight charge optimisation** — calculates the minimum charge target needed to survive the next day based on solar forecast and usage history, avoiding unnecessary cheap-rate imports
- **Solar surplus diversion** — automatically diverts excess solar to an immersion heater and/or EV charger instead of exporting at low rates
- **Cost tracking** — tracks energy costs across cheap/peak rate periods, with daily, weekly, and monthly accumulations and yesterday comparisons
- **Charge plan reporting** — generates HTML reports showing tonight's charge plan, today's energy summary, and weekly overview, renderable directly in a Markdown card
- **Forecast accuracy tracking** — measures how accurate solar forecasts were vs actuals over time

Tested on a GivEnergy GIV-HY-5.0 inverter with a 19kWh battery on the Electric Ireland Nightboost tariff.

---

## Prerequisites

- Home Assistant 2024.1.0 or later
- [GivTCP](https://github.com/britkat1980/giv_tcp) v3 running as a Home Assistant add-on, publishing inverter data over MQTT
- A GivEnergy hybrid inverter with battery storage

---

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=macuistin&repository=givenergy_inverter_manager&category=integration)

Or manually:

1. In HACS, go to **Integrations → Custom repositories**
2. Add `https://github.com/macuistin/givenergy_inverter_manager` and select category **Integration**
3. Install **GivEnergy Inverter Manager** and restart Home Assistant

### Manual

1. Download the latest release zip from [Releases](https://github.com/macuistin/givenergy_inverter_manager/releases)
2. Extract `givenergy_inverter_manager/` into your `config/custom_components/` folder
3. Restart Home Assistant

---

## Configuration

[![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=givenergy_inverter_manager)

Or go to **Settings → Devices & Services → Add Integration** and search for **GivEnergy Inverter Manager**.

The setup wizard walks through 7 steps:

| Step | What you configure |
|---|---|
| 1. GivTCP discovery | Auto-discovers your inverter serial from MQTT; confirm or enter manually |
| 2. Battery | Usable capacity (kWh), minimum safe SOC (%), and charge power (W) |
| 3. Tariff | Cheap rate window (start/end times) and peak/cheap unit rates (€/kWh) |
| 4. Solar forecast | Solcast API key and site ID for tomorrow's solar forecast |
| 5. Immersion heater | Optional — entity ID of your immersion heater switch and rated power (W) |
| 6. EV charger | Optional — entity ID of your EV charger switch and charge rate (W) |
| 7. Bill start day | Day of month your electricity bill period starts, for monthly cost tracking |

---

## Entities

### Switches

| Entity | Default | Description |
|---|---|---|
| `Auto Immersion Divert` | On | Master toggle for solar surplus diversion to immersion |
| `Immersion Heater (Managed)` | Off | Applies the coordinator's divert decision to the physical switch |
| `Force Skip Overnight Charge` | Off | Forces tonight's charge to be skipped regardless of forecast |
| `Enable Charge Target Override` | Off | Activates the manual charge target; off = automatic mode |

### Number

| Entity | Range | Default | Description |
|---|---|---|---|
| `Overnight Charge Target Override` | 10–100% | 80% | Manual charge target, applied only when the override switch is on |

### Sensors — Live

| Entity | Unit | Description |
|---|---|---|
| `Solar Power` | W | Current solar generation |
| `Battery Power` | W | Battery charge/discharge (positive = charging) |
| `Grid Power` | W | Grid import/export (positive = importing) |
| `House Load` | W | Current household consumption |
| `Battery SOC` | % | Current battery state of charge |
| `Battery Health` | % | Battery capacity vs design capacity |
| `Tariff Rate` | €/kWh | Current electricity rate (cheap or peak) |
| `Today Import Cost` | € | Running cost of grid imports today |
| `Tonight Charge Cost` | € | Projected cost of tonight's planned charge |
| `Bill Projection` | € | Projected monthly bill at current usage rate |
| `Night Survival SOC` | % | Minimum SOC needed to reach end of cheap window |
| `Charge Decision` | — | Today's charge decision (charge / skip / override) |
| `Charge Target` | % | Tonight's calculated (or overridden) charge target |

### Sensors — Immersion & EV

| Entity | Description |
|---|---|
| `Immersion Divert Active` | Whether surplus is currently being diverted |
| `Immersion Solar Savings Today` | Estimated cost saved by diverting to immersion vs grid heating |
| `EV Charger Active` | Whether EV charging is active under surplus control |
| `EV Charger Power` | Current EV charge rate |

### Sensors — Cost intelligence

| Entity | Description |
|---|---|
| `Cheap Rate Import Today` | kWh imported during cheap rate window today |
| `Peak Rate Import Today` | kWh imported during peak rate today |
| `Battery Throughput Today` | Total kWh cycled through battery today |

### Sensors — Accumulations (disabled by default)

Yesterday, weekly, and monthly variants are available for import cost, cheap/peak import, solar generation, battery throughput, and immersion savings. These are disabled by default to avoid cluttering your dashboard — enable them individually under **Settings → Devices & Services → [device] → entities**.

| Group | Entities |
|---|---|
| Yesterday (8) | Import cost, cheap import, peak import, solar, battery charge, battery discharge, immersion savings, net cost |
| Weekly (9) | Same set + week-to-date total |
| Monthly (9) | Same set + month-to-date total |

### Sensors — Forecast accuracy (disabled by default)

| Entity | Description |
|---|---|
| `Forecast Accuracy Today` | % difference between today's forecast and actual solar |
| `Forecast Accuracy 7-day` | Rolling 7-day mean absolute error |
| `Forecast Accuracy 30-day` | Rolling 30-day mean absolute error |
| `Forecast Bias` | Systematic over/under-forecast tendency |

### Sensors — HTML Reports

These sensors expose HTML strings renderable in a Markdown card with no additional dependencies.

| Entity | Description |
|---|---|
| `Today Summary` | Today's energy flows, costs, and savings in a formatted report |
| `Charge Plan` | Tonight's planned charge window, target, and cost breakdown |
| `Week Summary` | This week's energy and cost overview |

To display a report, add a **Markdown card** with:
```yaml
type: markdown
content: "{{ state_attr('sensor.givenergy_inverter_manager_today_summary', 'html') }}"
```

---

## Energy Dashboard

All cumulative energy sensors use `state_class: total_increasing` and appear automatically in the Energy dashboard entity picker.

| Dashboard slot | Entity |
|---|---|
| Solar production | `sensor.givenergy_inverter_manager_solar_energy_today` |
| Grid consumption | `sensor.givenergy_inverter_manager_grid_import_today` |
| Return to grid | `sensor.givenergy_inverter_manager_grid_export_today` |
| Battery — energy in | `sensor.givenergy_inverter_manager_battery_charge_today` |
| Battery — energy out | `sensor.givenergy_inverter_manager_battery_discharge_today` |

---

## How overnight charging works

Each 30-second cycle the coordinator:

1. Fetches tomorrow's solar forecast from Solcast
2. Estimates overnight consumption based on recent history
3. Calculates the minimum SOC needed at the end of the cheap window to reach the next cheap window
4. Adds a configurable buffer for forecast uncertainty
5. Writes the charge target to GivTCP via MQTT

If `Enable Charge Target Override` is on, the manual target from `Overnight Charge Target Override` is used instead. Turning the switch off returns to automatic mode on the next cycle.

The `Force Skip Overnight Charge` switch bypasses the calculation entirely and instructs GivTCP to skip tonight's charge regardless of forecast — useful when the battery is already full from solar.

---

## Troubleshooting

**Integration not appearing after install** — restart Home Assistant after copying the files.

**GivTCP auto-discovery fails** — ensure GivTCP is running and publishing to MQTT before setting up this integration. The inverter serial number appears in MQTT topics under `GivEnergy/<serial>/`; you can confirm this in the MQTT integration's Listen panel.

**Charge target not being applied** — check that `Enable Charge Target Override` is off (if you want automatic mode) and that GivTCP has write access to the inverter. The `Charge Decision` sensor shows the current intent; the coordinator logs at DEBUG level if you need more detail.

**Solar forecast not updating** — verify your Solcast API key and site ID in the integration options. Solcast free tier allows 10 API calls/day; the integration caches the last result and only fetches when needed.

**HTML report cards showing unstyled text** — ensure you are using `type: markdown` (not `type: custom:markdown-mod` or similar). The reports use inline styles only and require no HACS card dependencies.

**Sensors stuck at `unavailable`** — the coordinator marks entities unavailable if GivTCP stops publishing. Check GivTCP is running and the MQTT broker is reachable. The `Last Successful Refresh` diagnostic sensor shows the last successful data update.

---

## Roadmap

**v0.2.0**
- `entity-unavailable` handling (Silver quality scale)
- Reconfigure flow
- 95% test coverage
- `icons.json` for entity icons
- Automation examples
- Extended troubleshooting docs

**v1.0 (stable sensor names)**
After v1.0, four companion HACS repositories are planned:
- Power Flow Card
- Energy History Card
- Charge Plan Timeline Card
- HTML Report Templates

---

## Development

```bash
# Install dependencies
pip install -r requirements-test.txt

# Run tests
python -m pytest tests/ -q

# Lint
ruff check custom_components/givenergy_inverter_manager/ tests/

# Check quality scale
cat quality_scale.yaml
```

---

## Acknowledgements

- [GivTCP](https://github.com/britkat1980/giv_tcp) — the GivEnergy MQTT bridge this integration builds on
- [Predbat](https://github.com/springfall2008/batpred) — inspiration for accumulation tracking and forecast accuracy patterns
- [Octopus Energy integration](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy) — reference for HA quality scale patterns
- [cdpuk/givenergy-local](https://github.com/cdpuk/givenergy-local) — structural reference for GivEnergy HA integrations