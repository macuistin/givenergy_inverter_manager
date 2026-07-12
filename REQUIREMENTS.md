# GivEnergy Inverter Manager — Goals & Requirements

This document captures the goals, design constraints, and known limitations of the integration. It exists to keep future development focused and to prevent features or refactors from drifting away from the actual use case.

---

## The system this was built for

- **Inverter:** GivEnergy GIV-HY-5.0 (5kW hybrid), serial via GivTCP
- **Solar:** 8.4kWp — 20 × 420W JA Solar panels, east (92°) and west (272°) facing arrays
- **Battery:** 19kWh usable, GivEnergy battery stack
- **GivTCP:** Running as a Home Assistant add-on; provides all inverter entity states and write access
- **EV charger:** Zappi (myenergi integration), controlled via select entity for charge mode
- **Immersion:** WiFi-enabled immersion heater with a HA switch entity and optional temperature sensor
- **Tariff:** Electric Ireland Home Electric + Nightboost
  - Day (base): €0.3334/kWh
  - Night: €0.1644/kWh (23:00–08:00)
  - Nightboost: €0.0965/kWh (02:00–04:00) — cheapest active timed period wins
  - Export (CEG): €0.195/kWh
  - Standing charge: €0.8259/day
  - PSO levy: €1.46/month
  - VAT: 9%
  - Direct debit discount: 5.5%
  - Billing period: starts 16th of each month
- **Location:** Ireland (~52°N)

The integration must work correctly for this specific setup. It must also be general enough to work for any GivTCP user with a different tariff, battery size, or without a Zappi or immersion.

---

## Primary goals

**1. Automate overnight battery charging**
Decide how much to charge the battery from the grid each night, during the cheapest available rate window. The decision should account for tomorrow's solar forecast (if available), today's consumption, whether the car is plugged in, and the current battery SoC. The target is written to the GivTCP inverter entities once per night, one minute before the cheap window opens.

**2. Divert solar surplus to the immersion heater**
When solar output exceeds house load and the battery is sufficiently charged, turn on the immersion heater rather than exporting at a lower rate. Turn it off when surplus drops. Never activate if water is already at target temperature.

**3. Signal solar surplus availability for EV charging**
The Zappi (myenergi) and GivEnergy inverter are separate systems — the integration cannot directly control Zappi mode or battery discharge. Instead, surface `ev_solar_surplus_available` (True when surplus > 1,400W) so users can build a HA automation to switch the Zappi to Eco+ themselves. Also surface `ev_charging_source` (Solar/Grid/Battery/Mixed) and `ev_draining_battery` for monitoring.

**4. Surface useful energy information as HA sensors**
Expose real-time and accumulated energy data as first-class HA sensors so users can build dashboards, automations, and energy-cost tracking without any additional configuration.

**5. Predict the electricity bill**
Track daily import cost, export earnings, and standing charges. Project the current billing period to end-of-period. Surface accrued and projected bill as sensors.

---

## Non-goals

- **Not a GivTCP replacement.** This integration reads and writes GivTCP entities; it does not communicate directly with the inverter.
- **Not a real-time energy monitor.** The update cycle is 30 seconds. This is appropriate for overnight charge planning; it is not a substitute for a dedicated energy monitor at sub-second resolution.
- **Not a general home energy management system.** It does not control HVAC, manage time-of-use tariff switching, or integrate with smart meters directly. Those are separate concerns.
- **Not a cloud integration.** The `iot_class` is `local_push` (GivTCP pushes state via MQTT; HA reads the pushed state). No cloud API calls are made. GivEnergy entered administration in April 2026; the local GivTCP path remains fully functional.

---

## Design constraints

**Pure logic layer must stay pure.** `engine.py`, `optimizer.py`, `tariff.py`, `battery.py`, and `discovery/` must never import from `homeassistant`. This boundary keeps all decision-making unit-testable without a running HA instance. The coordinator is the only HA-dependent layer.

**One update interval.** Everything runs on a single 30-second coordinator cycle. There is no separate faster loop for immersion or EV control. This simplifies the architecture at the cost of some latency; 30 seconds is acceptable for all current use cases.

**Write-back happens once per day.** The overnight charge target is written to GivTCP via a time listener registered at startup, not on every 30-second cycle. This avoids unnecessary writes and matches how GivTCP expects to be driven (same approach as batpred and givenergy-local).

**GivTCP write sequence is fixed.** The five-step write sequence (enable schedule → set start time → set end time → set target SoC → enable/disable charge target) must not be changed without testing against real hardware. Step 5 (enable_charge_target switch) is particularly subtle: it must be OFF at 100% to avoid the charge-bounce bug documented by givenergy-local.

**Flat-rate tariffs must work.** `rate_periods` may be an empty list. In that case, no write-back listener is registered (there is no timed cheap window to target), and the base rate applies at all times. All tariff methods handle the empty-periods case correctly.

---

## Tariff model

```
TariffConfig
├── base_rate: float          # €/kWh — applies when no timed period is active
├── base_rate_name: str       # display name (e.g. "Day")
├── rate_periods: list        # timed overrides — cheapest active wins
│   ├── RatePeriod(name, rate, start, end)
│   └── ...
├── export_rate: float        # €/kWh CEG
├── standing_charge: float    # €/day
├── pso_levy: float           # €/month
├── vat_rate: float           # %
├── discount_rate: float      # % applied before VAT
└── bill_start_day: int       # day of month billing starts
```

Precedence: among all timed periods active at the current time, the cheapest wins. If none are active, the base rate applies. This means Nightboost (02:00–04:00) automatically overrides Night (23:00–08:00) without any special-casing.

---

## Sensors (39 total)

| Group | Sensors |
|---|---|
| Real-time power | `solar_power`, `grid_power`, `house_load`, `rest_of_house_load` |
| Battery | `battery_soc`, `estimated_soc_at_sunrise`, `battery_cycles`, `battery_remaining_life`, `days_since_full_charge` |
| Tariff | `current_rate`, `current_rate_period` |
| Energy today | `solar_today`, `import_today`, `export_today`, `zappi_today`, `immersion_today` |
| Cost today | `import_cost_today`, `export_earnings_today`, `zappi_cost_today`, `immersion_cost_today`, `house_cost_today` |
| Efficiency | `self_sufficiency`, `self_consumption`, `is_clipping` |
| Bill | `accrued_bill`, `projected_bill`, `days_remaining_in_period` |
| Charge plan | `overnight_charge_target`, `overnight_charge_reason`, `overnight_charge_cost` |
| Immersion | `immersion_divert_reason` |
| Night survival | `night_survival_reason` |
| EV | `ev_charger_state`, `ev_power`, `ev_session_energy`, `ev_draining_battery`, `ev_protection_reason` |
| Operations | `dry_run_active`, `dry_run_last_skipped` |

## Switches (3)

- `auto_immersion` — master enable/disable for automatic immersion divert
- `immersion_managed` — applies coordinator decision to the real immersion switch each cycle; also accepts manual on/off overrides
- `skip_charge_override` — force-skip overnight charging regardless of forecast

## Number (1)

- `charge_target_override` — manual charge target (0 = let the algorithm decide)

---

## Charge decision algorithm

```
inputs:  current_soc, battery_capacity, forecast_kwh (or None), inverter_max_kw,
         car_plugged_in, min_soc, skip_threshold, avg_daily_consumption_kwh

1. If forecast_kwh is None:
     forecast_kwh = inverter_max_kw × CHARGE_PEAK_SOLAR_HOURS × solar_fractions[month]
     (solar_fractions computed from hass.config.latitude via monthly_solar_fractions();
      works for any latitude, not just Ireland)
     avg daily consumption falls back to 15 kWh/day until enough data accumulates

2. If current_soc ≥ skip_threshold AND car not plugged in:
     If forecast_kwh > expected_solar_fill × 0.8:
       → skip_charge = True, target = min_soc + 10%

3. Calculate morning_load = avg_daily_kwh × 0.25
   If car plugged in: morning_load += 5 kWh
   gap_soc = max(0, morning_load - current_kwh) / capacity × 100

4. Forecast quality:
     ≥ 80% of capacity  → target = max(min_soc + gap + 10, 50)
     50–79%             → target = max(min_soc + gap + 20, 70)
     < 50%              → target = 90

5. If car plugged in: target += 10 (capped at 100)
6. Clamp: max(target, min_soc + 5), min(target, 100)
7. Apply configured max cap (CONF_OVERNIGHT_CHARGE_TARGET)
8. Apply manual overrides (skip switch, number entity)
```

---

## EV charger logic

The Zappi (myenergi) and GivEnergy inverter are separate systems with no integration between them. The Zappi uses its own CT clamp; stopping it does not protect the GivEnergy battery (the inverter covers house load from the battery regardless of what the Zappi does). For this reason the integration does not pause or stop the EV charger.

The integration surfaces signals for the user to act on via HA automations:

```
if ev_plugged_in:
    if solar_surplus_w > EV_SURPLUS_DIVERT_W:
        ev_solar_surplus_available = True  (signal for Zappi Eco+ automation)
    else:
        ev_solar_surplus_available = False

ev_charging_source = Solar | Grid | Battery | Mixed  (classification of live source)
ev_draining_battery = battery_power_w < 0 and ev_power_w > 0
```

The user automation (see `docs/automations.md`) watches `ev_solar_surplus_available` and calls the myenergi service to switch the Zappi to Eco+ when surplus is available.

Supported charger brands for monitoring: Zappi (myenergi), Wallbox, OCPP, Ohme, Easee. Only Zappi is supported for mode control via the myenergi integration.

---

## Known limitations

**Average daily consumption is estimated from today's partial data.** There is no historical average stored across HA restarts. Before 30 minutes of data have accumulated after midnight (or after an HA restart), a fallback of 15 kWh/day is used. This makes the charge decision conservative on the first cycle of a new day. Persistence is planned for v0.2.0.

**Battery cycle count resets on HA restart.** `BatteryStats.average_daily_cycles` returns 0.0 until persistence is implemented (v0.2.0). The cycle count itself increments correctly during a running session.

**EV session energy is not persisted.** `ev_session_energy` accumulates from when the session was first detected. If HA restarts mid-session the count resets. This is a display issue only; it does not affect charge control.

**Monthly export tracking is not implemented.** The billing model tracks accrued import cost and daily export earnings, but does not total monthly export kWh against a feed-in tariff cap. Planned for v0.2.0.

**Only one EV charger is supported.** Multi-charger households are not handled. The coordinator takes the first discovered charger. Planned for v0.3.0.

**Solcast multi-array not supported.** The forecast integration reads a single `forecast_entity` sensor. Solcast users with separate east/west array forecasts need to sum them externally and point the integration at the combined sensor. Planned for v0.2.0.

**The write-back fires once per day.** If GivTCP or the inverter is unavailable at 01:59, the write-back is missed for that night. There is no retry. This is acceptable for a first release; the previous night's target remains set in the inverter.

**Flat-rate tariff users get no write-back.** If `rate_periods` is empty, no overnight charge listener is registered. The integration still calculates a charge decision and surfaces it as a sensor, but it cannot write it to the inverter without a time window to target. Users with flat-rate tariffs should use the `charge_target_override` number entity to set a manual target, or write an HA automation using the `overnight_charge_target` sensor.

---

## Versioning plan

### v0.1.0 — current
- Core charge optimisation, immersion divert, EV solar surplus signalling
- 39 sensors, 3 switches, 1 number
- HACS-compatible, 7-step setup wizard
- Dry run mode, verbose logging toggle
- 366 passing tests, ruff clean

### v0.2.0 — persistence
- Persist `EnergyAccumulator` across HA restarts (daily kWh totals survive)
- Persist battery cycle history for a real `average_daily_cycles`
- Monthly export kWh tracking for feed-in cap monitoring
- Solcast multi-array support (east + west summed automatically)

### v0.3.0 — multi-device
- Multiple EV charger support
- Multiple battery string support (some larger GivEnergy systems)
- Per-appliance cost attribution beyond Zappi and immersion

---

## Repository

`github.com/macuistin/givenergy_inverter_manager`

Requires: Home Assistant ≥ 2024.1.0, HACS ≥ 1.32.0, GivTCP running as a HA add-on.

