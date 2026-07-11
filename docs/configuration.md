# Configuration

This page covers the full setup wizard and every option available in Settings → Devices & Services → GivEnergy Inverter Manager → Configure.

---

## Initial setup

### Step 1 — Inverter discovery

When you add the integration, it scans Home Assistant for GivTCP entities and tries to find your inverter automatically.

<!-- screenshot: inverter discovery step showing detected inverter -->

If your inverter is found, it will appear in a dropdown. Select it and the form pre-fills with the entities GivTCP is already publishing.

If nothing is found, check that GivTCP is running and publishing to MQTT before continuing. See [Troubleshooting](troubleshooting.md) if you're stuck.

**Battery capacity** and **max inverter output** are pre-filled from GivTCP where possible. Adjust them if they look wrong.

---

### Step 2 — Tariff

This is where you tell the integration what you pay for electricity. It uses this to calculate overnight charge costs, bill projections, and immersion divert savings.

<!-- screenshot: tariff configuration step -->

See [docs/tariff.md](tariff.md) for a full guide to filling this in, including an Electric Ireland Nightboost example.

---

### Step 3 — Solar forecast (optional)

Connect a forecast integration so the charge calculator knows what the sun is going to do tomorrow.

<!-- screenshot: forecast step -->

| Option | What to put |
|---|---|
| **Forecast provider** | Forecast.Solar or Solcast |
| **Tomorrow's forecast sensor** | The entity from your forecast integration that gives tomorrow's expected generation in kWh |

Leave this blank if you don't have a forecast integration. The system will use a seasonal estimate instead.

---

### Steps 4–6 — Immersion, EV charger, battery thresholds (optional)

These steps are optional. Skip any you don't need.

**Immersion heater** — if you have one connected to a smart switch, enter the switch entity here. The integration will turn it on and off based on solar surplus.

**EV charger** — if you have a Zappi, Wallbox, OCPP, Ohme, or Easee charger, enter its entities here. The integration will manage charging based on solar surplus and battery state.

**Battery thresholds** — sensible defaults are pre-filled. See the options reference below if you want to change them.

---

## Changing settings after setup

Go to **Settings → Devices & Services → GivEnergy Inverter Manager → Configure**.

<!-- screenshot: options flow showing three sections -->

The options page has three collapsible sections:

- **Tariff** — update your rates, rate periods, currency, and billing dates
- **Battery & charging thresholds** — adjust charge targets, protection thresholds, dry run mode, and verbose logging
- **Solar forecast** — change or add a forecast provider

Changes take effect on the next 30-second cycle. No restart needed.

---

## All options

### Tariff

| Option | Description |
|---|---|
| **Base rate** | Your standard daytime unit rate in EUR/kWh |
| **Base rate name** | Label for the base rate (e.g. "Day") |
| **Rate period 1–5** | Named time windows with their own unit rate, start time, and end time. See [tariff.md](tariff.md). |
| **Export / CEG rate** | What you receive per kWh exported to the grid |
| **Standing charge** | Daily standing charge in EUR |
| **PSO levy** | Monthly PSO levy in EUR (Ireland only — set to 0 if not applicable) |
| **VAT rate** | VAT percentage applied to your bill |
| **Supplier discount** | Percentage discount from your supplier |
| **Bill start day** | Day of the month your billing period starts |
| **Currency** | EUR, GBP, or USD |

### Battery & charging thresholds

| Option | Description |
|---|---|
| **Minimum battery SoC** | The integration will never recommend charging below this level. Default 10%. |
| **Default overnight charge target** | Target SoC used as a fallback if no forecast is available. Default 80%. |
| **Skip charge if SoC above** | If the battery is already above this level at the start of the cheap window, overnight charging is skipped. Default 80%. |
| **EV battery protection threshold** | During the day, the Zappi is paused if battery SoC falls below this level. Default 50%. During cheap rate periods, the Zappi is also paused if the battery is actively discharging (regardless of SoC) — grid is cheap, so the car should charge from grid, not battery. |
| **Dry run mode** | Calculates decisions and updates all sensors normally but sends no commands to GivTCP. Useful for testing before going live. |
| **Verbose logging** | Logs every sensor reading and decision on each 30-second cycle. Turn off for normal use. |

### Solar forecast

| Option | Description |
|---|---|
| **Forecast provider** | Forecast.Solar or Solcast |
| **Tomorrow's forecast sensor** | Entity from your forecast integration giving tomorrow's expected kWh |