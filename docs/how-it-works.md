# How it works

The integration runs a 30-second update cycle. Each cycle it reads the current state of your inverter, battery, solar, and house load from GivTCP, then makes decisions about charging and diversion.

---

## Overnight charge optimisation

Every cycle the integration calculates whether to charge tonight and, if so, how much.

<!-- screenshot: battery view showing tonight's charge plan -->

The calculation works like this:

1. **Get tomorrow's solar forecast** — from Solcast, Forecast.Solar, or a seasonal fallback if no forecast integration is configured.
2. **Estimate overnight consumption** — based on recent usage history.
3. **Work out the minimum charge needed** — enough to get through the night and into the morning solar window without running out.
4. **Write the charge target to GivTCP** — via MQTT, so your inverter acts on it during the cheap rate window.

If the battery is already high enough to last the night with margin to spare, the charge is skipped entirely. When a charge is skipped, the integration writes the **minimum SoC** as the GivTCP target so the battery can discharge freely overnight — without this, the inverter would hold the battery at the old target (e.g. 80%) and import from the grid instead of discharging.

The **Overnight Charge Reason** sensor tells you exactly what decision was made and why.

### Manual override

If you want to set a specific charge target yourself, turn on the **Enable Charge Target Override** switch and set the **Overnight Charge Target Override** number. The integration will use your target instead of calculating one. Turn the switch off to return to automatic mode.

The **Force Skip Overnight Charge** switch bypasses the calculation entirely and tells GivTCP not to charge tonight at all — useful when the battery is already full from solar.

---

## Solar surplus diversion

When the battery is full and solar is generating more than the house is using, there's no point exporting it at a low rate. The integration diverts that surplus to useful loads instead.

### Immersion heater

The integration checks whether to run the immersion on every 30-second cycle. It turns the immersion on when:

- Solar surplus is above the minimum threshold (default 500W)
- Battery SoC is above the divert threshold (default 80%)
- Water temperature is below the target temperature
- The water has cooled enough since the last time it was at target (see "Restart gap" below)

It turns the immersion off when water reaches the target temperature.

**Enable Solar Immersion Divert** is the master switch. When it's on, the integration manages the immersion automatically. When it's off, the integration leaves the immersion completely alone — it won't turn it on or off regardless of conditions.

**Immersion Heater (Controlled)** reflects the current state — whether the integration has the immersion on right now.

**Turning it on manually** (from the dashboard, an automation, or a physical button) activates **run-to-target mode**: the heater stays on until the water reaches the target temperature, then releases back to auto. This prevents the integration from overriding a deliberate manual action on the next 30-second cycle.

**Turning it off manually** turns the heater off immediately and applies a **10-minute cooldown** before the integration can turn it on again automatically. This also applies to external automations and physical switches — if anything outside the integration changes the switch state, the cooldown kicks in to prevent immediate re-override.

The cooldown also applies between **automatic** on/off decisions to prevent rapid cycling caused by brief solar surplus fluctuations (e.g. a cloud passing). The cooldown is bypassed if the water is at or above the target temperature — the heater must shut off immediately in that case.

<!-- screenshot: controls view showing immersion section with divert reason -->

The **Immersion Divert Reason** sensor explains the current decision — for example "Water already at 55°C (target 55°C)" or "Insufficient surplus (320W, need 500W)".

#### Temperature controls

Three number entities appear in the Entities list for this integration. All three are sliders that can be adjusted from the dashboard without going into Settings.

**Target temperature** (default 55°C) — the integration turns the immersion off when the water reaches this temperature. 55°C is the standard safe storage temperature for a domestic hot water cylinder.

**Minimum temperature** (default 50°C) — if the water drops below this, the integration will turn the immersion on regardless of solar surplus. This is the legionella protection floor: Legionella bacteria can grow in water between 20–45°C; keeping stored water above 50°C prevents this. The integration will force the immersion on at this point even on a cloudy day or at night.

**Restart gap** (default 5°C) — after the immersion turns off at the target temperature, it will not restart until the water has cooled by this many degrees. With the defaults (target 55°C, gap 5°C), the immersion won't restart until water drops below 50°C.

Without this gap, the immersion would turn on and off many times in quick succession whenever there is solar surplus — the water reaches 55°C, turns off, cools to 54.9°C, turns on again, reaches 55°C again, and so on. Each switching operation wears the relay in the smart plug. The restart gap means it goes off at 55°C, runs a longer uninterrupted heating cycle only once the water has genuinely cooled, and the switch operates far less often.

The restart gap is only checked when there is actually sufficient solar surplus to run the immersion. At 21:16 with 34W solar, the reason shown will be "Insufficient surplus" not the restart gap — the gap only matters when it is the actual reason heating is blocked.

*This mechanism has a formal name in engineering — "hysteresis" — but it's not a word you need to know or remember. The controls use plain English labels.*

### EV charger

The Zappi (myenergi) and GivEnergy inverter are separate systems — the Zappi uses its own CT clamp and the integration cannot directly control battery discharge. For this reason the integration does not pause or stop the EV charger.

Instead it provides two automation signals:

**`ev_solar_surplus_available`** — becomes `Available` when solar surplus exceeds 1,400W. Use this in a HA automation to switch the Zappi to Eco+ mode so it charges from surplus solar rather than the grid. See `docs/automations.md` for a ready-to-use example.

**`ev_charging_source`** — reports the live charging source: Solar, Grid, Battery, or Mixed. Useful for monitoring and dashboards.

**`ev_draining_battery`** — becomes `True` when the EV charger is drawing from the battery rather than solar or grid. Useful for automations that want to act when the car is using stored energy.

---

## Cost tracking

The integration tracks what everything costs across your tariff windows.

At any moment it knows the current rate period (Day, Night, Nightboost, etc.) and accumulates:

- **Import cost** — what you've spent on grid import today
- **Export earnings** — what you've earned from exports today
- **EV charging cost** — cost attributed to EV sessions today
- **Immersion cost** — cost attributed to immersion heater today
- **Rest-of-house cost** — everything else

These reset at midnight and also accumulate into weekly, monthly, and yearly totals. Yesterday's figures are preserved for comparison.

Where GivTCP publishes its own daily energy counters (`pv_energy_today_kwh`, `import_energy_today_kwh`, etc.), the integration uses those in preference to its own 30-second integration. GivTCP reads directly from the inverter's metering, which is more accurate than accumulating power readings. The integration falls back to its own accumulation silently if these entities are absent.

---

## Bill prediction

Using your standing charge, PSO levy, VAT rate, and accrued daily costs, the integration projects what your bill will be at the end of the current billing period. The **Projected Bill** sensor updates every cycle.

---

## Dry run mode

When dry run mode is on, the integration calculates everything normally — sensors update, charge decisions are made — but no commands are sent to GivTCP. The **Last Skipped Action** sensor shows what would have been done.

This is useful when you first set up the integration and want to check its decisions before letting it actually control anything.
