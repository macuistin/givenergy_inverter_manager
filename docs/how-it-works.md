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

If the battery is already high enough to last the night with margin to spare, the charge is skipped entirely. The **Overnight Charge Reason** sensor tells you exactly what decision was made and why.

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

**Immersion Heater (Controlled)** reflects the current state — whether the integration has the immersion on right now. You can toggle it manually for a one-cycle override, but the integration will update it again on the next cycle if the master switch is on.

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

If an EV charger is configured, the integration manages it similarly. It starts charging when there's sufficient solar surplus and battery SoC is healthy, and pauses charging if the battery SoC falls below the EV battery protection threshold.

For Zappi chargers specifically, the integration can switch between Eco+ (charge from solar) and Stopped mode.

---

## Cost tracking

The integration tracks what everything costs across your tariff windows.

At any moment it knows the current rate period (Day, Night, Nightboost, etc.) and accumulates:

- **Import cost** — what you've spent on grid import today
- **Export earnings** — what you've earned from exports today
- **EV charging cost** — cost attributed to EV sessions today
- **Immersion cost** — cost attributed to immersion heater today
- **Rest-of-house cost** — everything else

These reset at midnight and also accumulate into weekly and monthly totals. Yesterday's figures are preserved for comparison.

---

## Bill prediction

Using your standing charge, PSO levy, VAT rate, and accrued daily costs, the integration projects what your bill will be at the end of the current billing period. The **Projected Bill** sensor updates every cycle.

---

## Dry run mode

When dry run mode is on, the integration calculates everything normally — sensors update, charge decisions are made — but no commands are sent to GivTCP. The **Last Skipped Action** sensor shows what would have been done.

This is useful when you first set up the integration and want to check its decisions before letting it actually control anything.
