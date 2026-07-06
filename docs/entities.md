# Entities

All entities are created under a single device — your GivEnergy inverter — and prefixed `givenergy_inverter_manager_`.

---

## Switches

| Entity | What it does |
|---|---|
| **Enable Solar Immersion Divert** | Master switch for the immersion divert logic. When on, the integration manages the immersion automatically based on solar surplus and water temperature. When off, the immersion is left entirely alone. |
| **Immersion Heater (Controlled)** | The current state of the managed immersion switch. Reflects whether the integration has turned the immersion on. Can be toggled manually for a one-cycle override. |
| **Enable Charge Target Override** | When on, uses the manual charge target from the number below instead of calculating one automatically. |
| **Force Skip Overnight Charge** | Tells GivTCP to skip tonight's charge entirely, regardless of forecast or battery level. |

---

## Numbers

| Entity | What it does |
|---|---|
| **Overnight Charge Target Override** | Manual charge target (10–100%, step 5). Only applied when Enable Charge Target Override is on. |

---

## Sensors — Live

| Entity | Description |
|---|---|
| `Solar Power` | Current solar generation in W |
| `Battery SoC` | Current battery state of charge in % |
| `Battery Power` | Current battery charge/discharge power in W. Positive = charging, negative = discharging. |
| `Immersion Heater Power` | Configured wattage when the managed switch is on, 0 otherwise. |
| `Grid Power` | Current grid import/export in W (positive = import) |
| `House Load` | Total house consumption in W |
| `Rest of House Load` | House load minus managed loads (EV, immersion) in W |
| `Current Rate` | Unit rate applying right now in EUR/kWh |
| `Current Rate Period` | Name of the rate window active right now (e.g. Nightboost) |
| `Inverter Clipping` | Whether the inverter is clipping solar output |

---

## Sensors — Today's energy

| Entity | Description |
|---|---|
| `Solar Generation Today` | Total solar generated today in kWh |
| `Grid Import Today` | Total imported from grid today in kWh |
| `Grid Export Today` | Total exported to grid today in kWh |
| `Battery Charge Today` | Total energy into battery today in kWh |
| `Battery Discharge Today` | Total energy out of battery today in kWh |
| `EV Charging Today` | Total energy used for EV charging today in kWh |
| `Immersion Heater Today` | Total energy used by immersion heater today in kWh |

---

## Sensors — Today's costs

| Entity | Description |
|---|---|
| `Import Cost Today` | Cost of grid imports today |
| `Export Earnings Today` | Earnings from grid exports today |
| `EV Charging Cost Today` | Cost attributed to EV charging today |
| `Immersion Cost Today` | Cost attributed to immersion heater today |
| `House Cost Today` | Cost attributed to rest-of-house consumption today |
| `Self Sufficiency` | % of today's consumption met by solar + battery |
| `Self Consumption` | % of today's solar generation used on-site |

---

## Sensors — Charge plan

| Entity | Description |
|---|---|
| `Recommended Overnight Charge Target` | Tonight's recommended charge target in % |
| `Overnight Charge Reason` | Plain-English explanation of tonight's charge decision |
| `Estimated Overnight Charge Cost` | Projected cost of tonight's charge at current rates |
| `Estimated SoC at Sunrise` | Predicted battery level when solar begins tomorrow |
| `Night Survival Status` | Whether the battery is expected to last through the night |

---

## Sensors — Bill prediction

| Entity | Description |
|---|---|
| `Accrued Bill This Period` | Running total of this billing period's costs |
| `Projected Bill This Period` | Predicted total bill at end of current period |
| `Days Remaining in Period` | Days left in the current billing period |

---

## Sensors — Battery health

| Entity | Description |
|---|---|
| `Battery Total Cycles` | Estimated lifetime charge cycles used |
| `Battery Remaining Life` | Estimated remaining battery life as a percentage |
| `Days Since Full Charge` | How many days since the battery reached 100% |

---

## Sensors — EV charger

| Entity | Description |
|---|---|
| `EV Charger State` | Current charger state (charging, connected, disconnected) |
| `EV Charging Power` | Current EV charge rate in W |
| `EV Session Energy` | Energy delivered in the current charging session |
| `EV Draining Battery` | Whether EV charging is drawing from the battery |
| `EV Battery Protection Status` | Current EV protection decision and reason |

---

## Sensors — Immersion

| Entity | Description |
|---|---|
| `Immersion Divert Reason` | Why the immersion is on or off right now |

---

## Sensors — Forecast accuracy (disabled by default)

| Entity | Description |
|---|---|
| `Forecast Accuracy Today` | Percentage error between today's forecast and actual solar |
| `Forecast Accuracy 7-day` | Rolling 7-day mean absolute error |
| `Forecast Accuracy 30-day` | Rolling 30-day mean absolute error |
| `Forecast Bias` | Systematic over/under-forecast tendency |

---

## Sensors — Yesterday comparisons (disabled by default)

Eight sensors mirroring today's figures but for yesterday: import cost, cheap import, peak import, solar generation, battery charge, battery discharge, immersion savings, and net cost.

Enable these in Settings → Devices & Services → your integration → entity list.

---

## Sensors — Weekly and monthly accumulations (disabled by default)

Nine sensors each for the current week and current month: the same set as yesterday comparisons plus a period total. The week resets on Monday; the month resets on your configured bill start day.

---

## Sensors — HTML reports (disabled by default)

These sensors expose HTML content you can render directly in a Markdown card.

| Entity | Description |
|---|---|
| `Today Summary` | Today's energy flows, costs, and savings |
| `Charge Plan` | Tonight's planned charge window, target, and cost breakdown |
| `Week Summary` | This week's energy and cost overview |

To display one, add a Markdown card with:

```yaml
type: markdown
content: "{{ state_attr('sensor.givenergy_inverter_manager_today_summary', 'html') }}"
```

---

## Energy Dashboard

These entities appear automatically in the Home Assistant Energy Dashboard entity picker:

| Dashboard slot | Entity |
|---|---|
| Solar production | `solar_generation_today` |
| Grid consumption | `grid_import_today` |
| Return to grid | `grid_export_today` |
| Battery in | `battery_charge_today` |
| Battery out | `battery_discharge_today` |
