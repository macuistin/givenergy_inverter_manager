# GivEnergy Inverter Manager

[![Tests](https://github.com/macuistin/givenergy-inverter-manager/actions/workflows/tests.yml/badge.svg)](https://github.com/macuistin/givenergy-inverter-manager/actions/workflows/tests.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)

A Home Assistant custom integration for intelligent management of GivEnergy solar and battery systems. Works alongside [GivTCP](https://github.com/britkat1980/giv_tcp) to provide automated charge optimisation, solar surplus diversion, and detailed financial tracking.

> **Note:** GivEnergy entered administration in April 2026. This integration uses local control via GivTCP and does not depend on GivEnergy's cloud services.

---

## Features

### Automation
- **Smart overnight charging** — adjusts battery charge target based on solar forecast, season, and whether your EV is plugged in
- **Skip overnight charge** — if the battery is already high and tomorrow looks sunny, skip the charge entirely
- **Solar surplus diversion** — automatically turns on your immersion heater when the battery is full and solar is generating surplus
- **Appliance suggestions** — tells you the best time to run high-load appliances based on current solar and tariff
- **Manual overrides** — take control when you need to

### Financial Tracking
- Full energy P&L: import cost (per rate period), export earnings, self-consumption value
- Per-load cost tracking: EV charging, immersion heater, rest of house
- Bill prediction with standing charge, PSO levy, VAT, and supplier discounts

### Battery Health
- Cycle counting and remaining life estimate
- Days since last full charge
- "Will I make it to morning?" night survival prediction

---

## Requirements

- Home Assistant 2024.1+
- [GivTCP](https://github.com/britkat1980/giv_tcp) installed and configured
- [HACS](https://hacs.xyz) for installation

### Optional integrations
- [Forecast.Solar](https://www.home-assistant.io/integrations/forecast_solar/) or [Solcast](https://github.com/BJReplay/ha-solcast-solar) — enables smart overnight charge decisions
- [myenergi](https://github.com/CJNE/ha-myenergi) — Zappi EV charger integration

---

## Installation

### Via HACS (recommended)
1. Open HACS → Integrations → Custom Repositories
2. Add `https://github.com/macuistin/givenergy-inverter-manager` as an Integration
3. Search for "GivEnergy Inverter Manager" and install
4. Restart Home Assistant

### Manual
Copy `custom_components/givenergy_inverter_manager` to your HA `custom_components` directory and restart.

---


## Removal

1. Go to **Settings → Devices & Services**
2. Find "GivEnergy Inverter Manager" and click it
3. Click the three-dot menu → **Delete**
4. Restart Home Assistant (optional, but recommended to fully release all entities)

All sensors, switches, and automations that reference this integration's entities should be reviewed after removal.

---
## Configuration

Go to **Settings → Devices & Services → Add Integration** and search for "GivEnergy Inverter Manager".

The setup wizard has 7 steps:

| Step | What it configures |
|------|--------------------|
| 1. Inverter | GivTCP sensor entities (auto-detected), battery capacity, inverter max output |
| 2. Charge Scheduling | GivTCP control entities for automatic overnight charge write-back (auto-detected) |
| 3. Tariff | Rate periods, export rate, standing charge, PSO levy, VAT, billing cycle |
| 4. Solar Forecast | Optional Forecast.Solar or Solcast integration |
| 5. Immersion | Optional immersion heater switch and temperature targets |
| 6. EV Charger | Optional Zappi / Wallbox / OCPP / Ohme / Easee charger |
| 7. Battery | Overnight charge thresholds, immersion divert thresholds |

All optional steps can be skipped.

### Location-aware solar estimates

If no solar forecast integration is configured, the charge decision uses a **latitude-based seasonal estimate** derived from your HA location (Settings → System → General). The estimate uses the Liu & Jordan extraterrestrial radiation formula, giving appropriate seasonal variation for any latitude — a user in Ireland, Spain, or Scotland all get correct seasonal behaviour automatically. No manual configuration required.

### Configurable thresholds (Settings → Integrations → Configure)

All algorithm thresholds are exposed in the UI. Nothing is buried in code:

| Setting | Default | Description |
|---------|---------|-------------|
| Minimum battery SoC | 10% | Battery never discharged below this |
| Max overnight charge target | 80% | Upper bound on auto charge target |
| Skip charge threshold | 75% | Skip overnight charge if above this with good forecast |
| EV battery protection | 20% | Pause EV charger below this SoC |
| Immersion divert SoC | 80% | Enable immersion divert above this SoC |
| Immersion divert min surplus | 500W | Minimum solar surplus to trigger immersion |

### Algorithm parameters

The algorithm constants (CHARGE_*, SOLAR_*, BATTERY_* in const.py) are named, documented, and in one place. They are not exposed in the UI because they are algorithm tuning parameters rather than user preferences, but they are clearly labelled and a developer can change them without searching through business logic. See `const.py` for the full list with descriptions.

---

## Tariff Configuration

Supports any number of rate periods. Example for Electric Ireland Home Electric + Nightboost:

| Period | Rate | Hours |
|--------|------|-------|
| Day | €0.3334/kWh | 08:00–23:00 |
| Night | €0.1644/kWh | 23:00–08:00 |
| Nightboost | €0.0965/kWh | 02:00–04:00 |

Enter as one line per period in the tariff step:
```
Night, 0.1644, 23:00, 08:00
Nightboost, 0.0965, 02:00, 04:00
```

---

## Architecture

The integration is split into two clean layers:

**HA layer** (`coordinator.py`, `sensor.py`, `switch.py`, `number.py`, `config_flow.py`, `dashboard.py`) — handles all HA interaction. Contains no business logic.

**Pure logic layer** (`rules.py`, `engine.py`, `tariff.py`, `battery.py`, `discovery/`) — all decision-making. Zero HA imports. Fully unit-testable without a running HA instance.

```
coordinator.py  ←  reads HA state, calls engine, applies HA service calls
    ↓
engine.py       ←  orchestrates: feeds RawSensorValues into rules, assembles CoordinatorData
    ↓
rules.py        ←  all decisions: charge target, immersion divert, EV action, solar fractions
tariff.py       ←  rate period logic, energy accumulation
battery.py      ←  cycle counting, night survival
discovery/      ←  GivTCP entity discovery, EV charger discovery
```

See `docs/architecture.mermaid` for the full module dependency diagram.

---

## Running Tests

```bash
pip install -r requirements-test.txt
python -m pytest tests/ -v
```

372 tests. All pure-logic tests run without a HA instance.

---

## Contributing

Pull requests welcome. Please ensure all tests pass and add tests for any new logic in `rules.py`, `engine.py`, `tariff.py`, or `battery.py`.

```bash
python -m pytest tests/ -v --cov=custom_components/givenergy_inverter_manager
```

---

## Acknowledgements

This integration would not exist without the work of the following projects and their maintainers. Several of them solved hard problems first — the five-step GivTCP write sequence, the charge-bounce bug, the Zappi entity naming conventions — and documented their findings in code and issues.

### [GivTCP](https://github.com/britkat1980/giv_tcp) — britkat1980
The HA add-on that exposes GivEnergy inverter sensors and control entities. The five-step charge write sequence (enable schedule → set start time → set end time → set target SoC → toggle enable_charge_target) is the sequence GivTCP expects.

### [Predbat](https://github.com/springfall2008/batpred) — Trefor Southwell
The most complete battery prediction tool for HA. Two things came from Predbat: the `enable_charge_target` switch requirement (silently ignored by the inverter otherwise) and the write-and-verify pattern (read back each entity after writing to confirm the inverter accepted it).

### [givenergy-local](https://github.com/cdpuk/givenergy-local) — cdpuk
Direct Modbus TCP integration. The charge-bounce bug fix: setting `enable_charge_target` OFF when the target is 100% prevents the battery oscillating between 99–100%.

### [ha-myenergi](https://github.com/CJNE/ha-myenergi) — CJNE
The entity naming conventions for Zappi auto-discovery (`myenergi_zappi_{SERIAL}_plug_status`, `_charge_mode`, etc.) come from this integration.

### [Forecast.Solar](https://forecast.solar) and [ha-solcast-solar](https://github.com/BJReplay/ha-solcast-solar) — BJReplay
The two supported solar forecast providers.

---

## Licence

MIT
