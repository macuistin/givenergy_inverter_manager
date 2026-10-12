# GivEnergy Inverter Manager: Goals and Requirements

This document captures the goals, design constraints, and known limitations of the integration. It exists to keep future development focused and to prevent features or refactors from drifting away from its purpose.

---

## Scope and tested setup

The integration must work for any GivTCP user: any supplier, any tariff (timed rates or flat), any country, any battery size, with or without an EV charger or an immersion heater.

It has been tested on this setup:

- **Inverter:** GivEnergy GIV-HY-5.0 (5 kW hybrid) with a GivEnergy battery
- **GivTCP:** 3.6.3, running as a Home Assistant add-on. It provides all inverter entity states and write access. 3.6.2 is the oldest 3.6 release that is safe: 3.6 and 3.6.1 reset entity ids (3.6 also mishandled charge slot 2 and PV-only inverters, which 3.6.1 fixed). A repair appears on 3.6 and 3.6.1
- **EV charger:** Zappi (myenergi integration), controlled through its charge mode select entity
- **Immersion:** a WiFi-enabled immersion heater with a Home Assistant switch entity and an optional temperature sensor
- **Tariff:** a base rate plus a night period and a shorter, cheaper boost period inside it (Electric Ireland Home Electric with Nightboost)

The integration also recognises AC-coupled, All-In-One, three-phase, Gateway and EMS systems, and a GivEnergy EV charger. Those are tested against entity lists built from GivTCP's published datapoint reference and source, not against real hardware, and the setup screen and the README say so. Other setups are expected to work. Report any that do not.

---

## Primary goals

**1. Automate overnight battery charging**
Decide how much to charge the battery from the grid each night, during the cheapest available rate window of your tariff. The decision should account for tomorrow's solar forecast (if available), today's consumption, whether the car is plugged in, and the current battery SoC. The target is written to the GivTCP inverter entities once per night, one minute before the cheap window opens.

**2. Divert solar surplus to the immersion heater**
When solar output exceeds house load and the battery is sufficiently charged, turn on the immersion heater rather than exporting at the export rate. Turn it off when surplus drops. Never activate if water is already at target temperature.

**3. Move the Zappi to Eco+ and signal solar surplus availability for EV charging**
The Zappi (myenergi) and GivEnergy inverter are separate systems, so the integration cannot control battery discharge. It switches a Zappi with a charge mode select to Eco+ when a car is plugged in and surplus is at least 1,380W, and never stops it. It also surfaces `ev_solar_surplus_available` (Available when surplus >= 1,380W) so users can build automations for chargers it cannot control. Also surface `ev_charging_source` (Solar/Grid/Battery/Mixed) and `ev_draining_battery` for monitoring.

**4. Surface useful energy information as HA sensors**
Expose real-time and accumulated energy data as first-class HA sensors so users can build dashboards, automations, and energy-cost tracking without any additional configuration.

**5. Predict the electricity bill**
Track daily import cost, export earnings, and standing charges. Project the current billing period to end-of-period. Surface accrued and projected bill as sensors.

---

## Non-goals

- **Not a GivTCP replacement.** This integration reads and writes GivTCP entities; it does not communicate directly with the inverter.
- **Not a real-time energy monitor.** The update cycle is 30 seconds. This is appropriate for overnight charge planning; it is not a substitute for a dedicated energy monitor at sub-second resolution.
- **Not a general home energy management system.** It does not control HVAC, manage time-of-use tariff switching, or integrate with smart meters directly. Those are separate concerns.
- **Not a cloud integration.** The `iot_class` is `local_push` (GivTCP pushes state via MQTT; HA reads the pushed state). No cloud API calls are made. GivEnergy entered administration in April 2026. The local GivTCP path remains fully functional.

---

## Design constraints

**Pure logic layer must stay pure.** Nothing in `core/` or `discovery/` may import from `homeassistant`. This boundary keeps all decision-making unit-testable without a running HA instance. `tests/test_metadata.py` fails if a module in `core/` imports it. The coordinator and the platform files (`sensor.py`, `switch.py`, `number.py`, `button.py`) are the HA-dependent layer.

**One update interval.** Everything runs on a single 30-second coordinator cycle. There is no separate faster loop for immersion or EV control. This simplifies the architecture at the cost of some latency; 30 seconds is acceptable for all current use cases.

**Write-back happens once per day, and a failed write is retried.** The overnight charge target is written to GivTCP via a time listener registered at startup, not on every 30-second cycle. If that write fails, it is tried again at +2, +5, +10 and +20 minutes after the trigger, while at least 15 minutes of the window remain. This avoids unnecessary writes and matches how GivTCP expects to be driven (same approach as batpred and givenergy-local). Each write is read back and skipped when the value is already set. See [Write protection](docs/concepts.md#write-protection).

**The target can be worked out again inside the window, and that is off by default.** With the Re-plan overnight charge switch on, a check runs once late in the window, when the forecast moves by 15% and 1 kWh, and when an EV charger is plugged in or unplugged. It writes only when the new target is at least 5 points from the last one, at most three times a night, never outside the window, never with a manual override on, and never turns a charge into a skip while one is running. It sends the same plan through the same writer, so the window is never opened or moved. It is off until GivTCP is confirmed to apply a changed target to a charge that is already running. See [Re-planning](docs/concepts.md#re-planning).

**One inverter is managed, chosen by rules.** GivTCP shows each hybrid, All-In-One, Gateway or EMS as its own device, and a prefix may be changed. A Gateway over parallel All-In-Ones is managed and its units are read-only, because a write to a child unit can read back correctly and change nothing. With two or more other inverters the user is asked, and two inverters are never added together. An EMS gets no writes. The integration keeps what it last saw (kind, managed inverter, battery modules) and raises a repair when that changes, and never switches inverter silently.

**GivTCP write sequence is fixed.** The five-step write sequence (enable schedule → set start time → set end time → set target SoC → enable/disable charge target) must not be changed without testing against real hardware. Step 5 (enable_charge_target switch) is particularly subtle: it must be OFF at 100% to avoid the charge-bounce bug documented by givenergy-local.

**Flat-rate tariffs must work.** `rate_periods` may be an empty list. In that case, no write-back listener is registered (there is no timed cheap window to target), and the base rate applies at all times. All tariff methods handle the empty-periods case correctly.

---

## Tariff model

```
TariffConfig
├── base_rate: float          # currency per kWh, applies when no timed period is active
├── base_rate_name: str       # display name (e.g. "Day")
├── rate_periods: list        # timed overrides, cheapest active wins
│   ├── RatePeriod(name, rate, start, end)
│   └── ...
├── export_rate: float        # currency per kWh paid for export
├── standing_charge: float    # currency per day
├── pso_levy: float           # flat charge per bill period (any flat per-period charge, or 0)
├── vat_rate: float           # %, 0 for none
├── discount_rate: float      # % applied before VAT, 0 for none
└── bill_start_day: int       # day of month billing starts
```

Precedence: among all timed periods active at the current time, the cheapest wins. If none are active, the base rate applies. This means a boost period (for example 02:00–04:00) automatically overrides a night period (for example 23:00–08:00) without any special-casing.

---

## Entities

- **Sensors:** 144, of which 85 are enabled by default. Every sensor, with unit, state class and description, is in [docs/sensors.md](docs/sensors.md). That page is generated from `sensor.py` and a test fails when it is out of date.
- **Switches (5):** `auto_immersion`, `immersion_managed`, `immersion_schedule`, `skip_charge_override` and `charge_target_override_enabled`.
- **Numbers (4):** `charge_target_override`, and the immersion target temperature, minimum temperature and restart gap.

What each switch and number does is in [docs/entities.md](docs/entities.md).

---

## Charge decision

The overnight charge target is worked out every cycle and written to GivTCP once a day. The rules, the forward simulation and the write sequence are described in [docs/concepts.md](docs/concepts.md#overnight-charge-target). The code is `calculate_overnight_charge_target` in `core/rules.py`.

Requirements the algorithm must keep:

- Winter months charge to 100% and shoulder months raise the minimum SoC.
- A strong forecast and a high SoC skip the charge. On a skip night the minimum SoC is written as the target, so the battery can discharge.
- The result never goes below minimum SoC plus 5 or above 100, and the configured cap applies to automatic targets only.
- Manual overrides (the skip switch and the charge target override) win over the algorithm.

---

## EV charger logic

The Zappi (myenergi) and GivEnergy inverter are separate systems with no integration between them. The Zappi uses its own CT clamp; stopping it does not protect the GivEnergy battery (the inverter covers house load from the battery regardless of what the Zappi does). For this reason the integration does not pause or stop the EV charger. It only selects the mode that means use surplus only, Eco+ on a Zappi and Solar on a GivEnergy charger, never Stopped, Fast, Grid or Hybrid, and never writes the charger's Charge Control or Plug and Go. It does so on a charger with a charge mode entity, when a car is plugged in and solar_surplus_w >= EV_CHARGER_MIN_POWER_W, subject to the write cooldown.

The integration also surfaces signals for the user to act on via HA automations:

- `ev_solar_surplus_available` reads `Available` when `solar_surplus_w >= EV_CHARGER_MIN_POWER_W` (1,380 W).
- `ev_charging_source` is Solar, Grid, Battery or Mixed, a classification of the live source.
- `ev_draining_battery` is `yes` when the charger is charging and the battery discharges over 200 W.

A user automation (see `docs/automations.md`) can watch `ev_solar_surplus_available` to start chargers the integration cannot control.

Supported charger brands for monitoring: Zappi (myenergi), Wallbox, OCPP, Ohme, Easee. Only Zappi is supported for mode control, through its select entity.

---

## Known limitations

**Average daily consumption is estimated from today's partial data until history builds up.** Before 30 minutes of data have accumulated after midnight a fallback of 15 kWh/day is used, which makes the first decision of a day conservative. Once two complete days of per-slot history are stored, the forward simulation uses that history instead. Accumulated energy and the per-slot profile are saved with Home Assistant storage and survive restarts. A crash can lose up to about 5 minutes.

**Only one EV charger is supported.** Homes with several chargers are not handled. The coordinator takes the first discovered charger.

**Solcast multi-array is not supported.** The integration reads a single `forecast_entity` sensor, plus the optional P10 and day-after-tomorrow sensors. Users with separate forecasts for several arrays need to sum them (for example with a template sensor) and point the integration at the combined sensor.

**The write-back fires once per day, then retries.** The trigger is one minute before the cheapest period starts. The write has failed when GivTCP is not publishing, when the inverter integration is silent, frozen or paused, or when a setting was sent and the inverter still shows the old value after the writer's own read-backs. A failed write is tried again at +2, +5, +10 and +20 minutes after the trigger. A retry is dropped when less than 15 minutes of the window would remain, so a short window gets fewer. One retry is pending at a time, and each retry uses the plan as it stands then, so a manual override set in between is what is written. If every attempt fails the log says so, and the previous night's target stays set in the inverter. After a restart inside the window, if the write log shows no write to the target since the trigger (or a failed attempt after the last write), the write is made once on start-up. Nothing is stored for this. A flat-rate tariff has no trigger, no retry and no catch-up. In dry run one "Would write" line is kept per night and nothing is sent.

**Flat-rate tariff users get no write-back.** If `rate_periods` is empty, no overnight charge listener is registered. The integration still calculates a charge decision and surfaces it as a sensor, but it cannot write it to the inverter without a time window to target. Users with flat-rate tariffs can write an HA automation that reads the `overnight_charge_target` sensor.

**The season rules use northern hemisphere months.** Winter is December to February, and the shoulder months are March, April, October and November. These are fixed calendar months. The seasonal solar estimate uses your latitude.

---

## Versions

The current release is 0.18.2. What each release shipped is in [CHANGELOG.md](CHANGELOG.md). Planned work is in the same file, ranked as Must, Should, Could and Nice.

---

## Repository

`github.com/macuistin/givenergy_inverter_manager`

Requires: Home Assistant ≥ 2026.5.0, HACS ≥ 1.32.0, GivTCP running as a HA add-on.

