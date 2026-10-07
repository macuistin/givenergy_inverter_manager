# Concepts

How the integration moves data, when it acts, and how it makes its decisions.

## Data flow

```
inverter --> GivTCP --> MQTT --> Home Assistant entities (sensor.givtcp_<serial>_*)
                                        |
                              coordinator (reads every 30 s)
                                        |
                       core engine (pure Python, no Home Assistant code)
                                        |
                  sensors, switches, numbers (this integration)
                                        |
                  service calls back to GivTCP, the EV charger and the immersion switch
```

- The integration reads Home Assistant entity states. It does not talk to GivTCP, your forecast service or your supplier directly.
- Decisions live in `core/` and do not import Home Assistant. The coordinator reads entities, passes plain numbers to the engine, and applies the result.
- Writes go out as ordinary Home Assistant service calls: `switch.turn_on`, `select.select_option` and `number.set_value`.
- Accumulated energy is saved with Home Assistant storage in `.storage/givenergy_inverter_manager.energy`.

## The 30-second cycle

Every 30 seconds the coordinator runs these steps in order.

1. Merge configuration. Saved options override the values entered at setup.
2. Raise or clear the repair issues: one for a minimum SoC above 30%, one for other charge slots with a window set, one for a battery cost of 0 after a week of battery tracking, one for GivTCP day, night or export rates that differ from the tariff.
3. Check GivTCP. If both the solar power sensor and the battery SoC sensor are `unavailable`, `unknown` or missing, the cycle fails and every entity of the integration becomes unavailable until GivTCP returns. See [Troubleshooting](troubleshooting.md#all-entities-are-unavailable).
4. Look for an EV charger. Until one is found with its power, session and charge mode entities, discovery repeats about every 5 minutes (every tenth cycle). Entities that appear later are added with no reload.
5. Read the sensors: solar power, battery SoC, battery power, grid power, house load, the optional immersion temperature, forecasts, carbon intensity and inverter temperature, the EV charger, and the GivTCP daily energy counters.
6. Run the engine. It finds the current rate, adds the time since the last cycle to the today, week, month and year totals, applies the GivTCP daily counters to today's totals, and works out the charge target, immersion decision, bill figures, night survival and EV signals.
7. Record the day's first forecast value, for the Solar forecast today (charge plan) sensor, and the latest forecast for tomorrow. At midnight that tomorrow forecast becomes today's provider forecast, which the Solar forecast today (provider) and Solar vs provider forecast sensors, the forecast accuracy sensors and the accuracy correction measure against.
8. Apply the cheap rate floor, if it is due.
9. Apply the EV mode change, if one was requested.
10. Apply the immersion decision to your real immersion switch. The first cycle after a start or reload skips this step, because the real switch may not be up yet. It runs even when the managed switch entity is disabled. The managed switch shows the decision and lets you override it.

Three things happen on a clock instead of in the cycle.

| When | What |
|---|---|
| 00:00:00 local time | Daily reset. Today moves to yesterday. Monday also resets the week. The bill start day also resets the month and saves a snapshot. 1 January also resets the year. |
| One minute before the cheapest timed rate period starts, once a day | Write the charge target and window to GivTCP |
| Every tenth cycle (about 5 minutes) and at midnight | Save accumulated energy and battery statistics |
| Entry unload and Home Assistant stop | Save accumulated energy and battery statistics |

Energy is added using the real time between cycles. The first cycle after a start or a midnight reset adds nothing, and a gap longer than one hour is skipped, so a restart does not create a spike.

Accumulated energy is saved when the integration unloads and when Home Assistant stops, so a restart or a reload after saving options keeps it. A crash can lose up to about 5 minutes. On start-up the integration applies any midnight, Monday, bill start day or 1 January reset that passed while Home Assistant was down.

### Write protection

GivTCP writes use registers with a limited lifetime. Each write helper:

- reads the entity first and skips the write when it already holds the value;
- skips the write when the same value was written to the same entity in the last 300 seconds (a different value is still written);
- reads the entity back after 2 seconds and retries up to 3 times;
- catches an error from the service call, logs it and carries on instead of stopping the task;
- counts each write in the GivTCP Register Write Count sensor, and logs a warning at 500,000 writes. The count is saved with the accumulated energy and survives restarts. It counts writes that were sent. A write skipped because the entity already holds the value is not counted, so a night where only the charge target changed adds 1. Each write is also listed, with its reason, in the sensor's `recent_writes` attribute. See [Find out what changed the charge target](troubleshooting.md#find-out-what-changed-the-charge-target).

If writing the target SoC fails, the charge target is not enabled, so the inverter is not limited to an old target. Charge targets are limited to 4 to 100%, the range GivTCP accepts.

The Zappi mode write skips when the Zappi is already in the target mode and when that select entity was written in the last 300 seconds. It is not read back or counted, because it is not an inverter register.

## GivTCP sign conventions

The integration is tested against GivTCP v3 on a GIV-HY-5.0.

| GivTCP entity | GivTCP sign | In this integration |
|---|---|---|
| Grid power | Positive is export, negative is import | The integration negates it. **Grid Power** is positive when importing and negative when exporting |
| Battery power | Positive is discharging, negative is charging | The integration negates it. **Battery Power** is positive when charging and negative when discharging |
| Solar power | Always positive | Unchanged. Readings under 10 W count as zero in the solar energy total |
| Load power | Inverter-side load | Unchanged. **House Load** |

To check your own setup, export to the grid on a sunny day and compare **Developer Tools → States** for the GivTCP grid power entity and **Grid Power**. They must have opposite signs. If they do not, grid import and export are swapped in every cost sensor. Do the same for battery power: the GivTCP entity and **Battery Power** must have opposite signs. If they do not, charge and discharge are swapped in the battery energy totals.

GivTCP measures at the inverter. A load wired directly to the consumer unit, bypassing the inverter, appears as grid import even while the sun is shining.

### GivTCP daily counters

When these entities exist, they replace the integration's own sum for today's physical energy:

`sensor.givtcp_<serial>_pv_energy_today_kwh`, `_import_energy_today_kwh`, `_export_energy_today_kwh`, `_charge_energy_today_kwh`, `_discharge_energy_today_kwh` and `_load_energy_today_kwh`.

A missing counter falls back to the integration's own sum, one counter at a time. Week, month and year totals always use the integration's own sum, with one exception: the AC charge counter below. Costs and earnings are always worked out by the integration, because GivTCP does not know your tariff.

`sensor.givtcp_<serial>_ac_charge_energy_today_kwh` is the part of today's import that charged the battery. It has no power-based stand-in. Without it, Grid to Battery Today is unavailable and Self-sufficiency counts all import, as it did before. The week, month and year each add the counter's rise since the last reading, so a midnight reset or a restart does not lose or repeat energy.

### Battery cycles

One cycle is the battery's full capacity discharged once (an equivalent full cycle), which is how the battery's own BMS counts. Charging does not add cycles.

- **From the BMS.** When GivTCP publishes `sensor.givtcp_<battery serial>_battery_cycles`, that counter is the lifetime count. The integration finds these entities by name every 5 minutes. With several battery packs it uses the highest value, not the sum, because each pack counts its own cycles.
- **From SoC.** Without a BMS counter, each fall in SoC between two updates adds the fall divided by 100. A missing reading, a reading of 0% after a healthy one, and a step of more than 10% between updates are treated as glitches and add nothing. If the BMS counter goes missing, the estimate carries on from the last BMS value.

Battery Total Cycles, Battery Remaining Life, Battery Years Remaining and Battery Usable Capacity all use this count. Earlier versions counted charge and discharge, which roughly doubled the figure. The saved count is halved once when the integration first loads the new storage format.

## How decisions are made

### Overnight charge target

The calculation runs every cycle. The result is written to GivTCP once a day. The rules, in order:

1. **Winter, December to February.** The target is 100%. The charge is skipped if SoC is already 95% or more. The forecast is not used.
2. **Shoulder months, March, April, October and November.** The minimum SoC is raised to at least 70% for the calculation.
3. **Forecast.** The tomorrow sensor is used when set, from 08:00 until midnight. Forecast sensors move on a day at midnight, so between midnight and 08:00 the integration uses the forecast it remembered just before midnight, which is the forecast for the day being charged for. In that window the tomorrow sensor is read as the day after. If nothing was remembered, for example on the first night after install, it uses the estimate below. Otherwise the integration estimates from your latitude: inverter maximum output in kW times 4 hours times a factor for the month, with 1.0 for the sunniest month. Once five usable days are stored (a new install reads them from the recorder), the sensor forecast is first multiplied by the median of actual solar divided by forecast over the last 14 days, limited to 0.6 to 1.2. Days that clipped, or where the forecast or the solar was under 0.5 kWh, are ignored, and the seasonal estimate is never scaled. The reason shows `x0.70 recent accuracy` when the factor applies, and the attributes of the Overnight Charge Reason sensor show the measured factor, the applied factor and the usable days (`Waiting for data: 3 of 5 days` until the fifth). If a P10 forecast is available (the P10 sensor you chose, or the `estimate10` attribute that Solcast puts on its forecast sensors) and the conservatism is above 0, the corrected forecast becomes `(1 - w) x forecast + w x P10`, where `w` is the conservatism. With no P10 value the blend is skipped and the reason says so. See [Forecast accuracy correction](configuration.md#forecast-accuracy-correction) and [Where the P10 comes from](configuration.md#where-the-p10-comes-from).
4. **Skip rule.** The charge is skipped, with a target of minimum SoC plus 10, when SoC is at or above the skip threshold, no EV is plugged in, and the forecast is more than 0.8 times the smaller of 60% of the forecast and the usable battery capacity.
5. **Simulation.** Otherwise the integration simulates one day in 48 half-hour slots. Solar follows a bell curve centred on 13:00 between 06:30 and 19:30. Load follows your own per-slot history once two complete days are stored (the same weekday when three or more are available), scaled to the average daily load. Before that it is the average daily load spread evenly. It finds the lowest starting SoC that keeps the battery above the minimum all day.
6. **Adjustments.** Add 10 points if an EV is plugged in. Never go below minimum SoC plus 5, or above 100.
7. **Cap.** The target is capped at **Default overnight charge target**, which is 80% unless you change it. The cap also applies to the winter target of 100%.
8. **Overrides.** Manual overrides replace the result and the cap does not apply to them. See [Entities](entities.md).

**Held recommendation.** The calculated target moves by a few points from cycle to cycle, most of all in the small hours, when the average daily load is extrapolated from very little data. The **Recommended Overnight Charge Target**, **Overnight Charge Reason** and **Estimated Overnight Charge Cost** sensors hold their last value until the calculated target is 5 points or more away from it, or the plan changes between charging and skipping. Overrides and the cap apply at once. The value written to the inverter is never held: it comes from the latest calculation at the moment of the write, and the sensors catch up on the next cycle.

**Forecast adjustments, in order.** Step 3 adjusts the forecast twice before the simulation uses it:

1. **Accuracy correction.** Multiply by the median of actual solar over forecast for the last 14 days, kept between 0.6 and 1.2. It needs 5 usable days. A new install fills them from the Home Assistant recorder when it first loads (the last value of the forecast sensor before each midnight against that day's GivTCP solar total, about 9 days with the default 10 days of history), so the correction can apply at once. A day with clipping, or with a forecast or solar yield under 0.5 kWh, is not usable, and seeded days are never marked as clipped. A forecast that runs about 30% high gives a factor near 0.7, so the battery charges for 70% of what the service promises.
2. **P10 blend.** If a P10 forecast is available (the P10 sensor, or the `estimate10` attribute of a Solcast forecast sensor) and conservatism is above 0, take `(1 - w) x forecast + w x P10`.

The factor raises the forecast, up to 1.2, when the service runs low. The charge reason names each step that applied. Setup details are in [Configuration](configuration.md#forecast-accuracy-correction).

The winter and shoulder month lists are fixed calendar months. They follow northern hemisphere seasons. The seasonal solar estimate does use your latitude.

The average daily load is today's house energy so far, scaled up to 24 hours. It is at least 5 kWh, and 15 kWh in the first 30 minutes after midnight.

**Writing the target.** One minute before the cheapest timed period starts, the integration sets, in order: enable charge schedule on, charge start time, charge end time, target SoC, then enable charge target (on for targets below 100, off for 100). The window starts with the cheapest timed period and is sized to the plan (see below). On a skip night it writes the minimum SoC as the target, so the battery can discharge instead of being held at an old target. Nothing is written when the target SoC entity was not detected, or when the tariff has no timed period. The integration owns charge slot 1 only. When another slot (2 to 10) has a window set, it raises the repair **Other charge slots are active**, because the inverter also charges in that slot. See [Troubleshooting](troubleshooting.md#other-charge-slots-are-active).

**Sizing the window.** The inverter charges from the window start and stops at the target, so the cheapest hours come first. The cheapest period alone can be too short for a deep charge: a two hour period at 3.6 kW adds about 7 kWh. When the plan needs more time, the integration moves the window end later. Hours needed = (target SoC minus current SoC) x battery capacity / battery charge rate, plus 15% for the slowdown near full, rounded up to 5 minutes. The end never goes past the end of the run of timed periods cheaper than the base rate that follows the cheapest period. For example, with Nightboost 02:00 to 04:00 inside Night 23:00 to 08:00, the end can reach 08:00. If the plan fits the cheapest period, nothing changes. The charge rate is read from `number..._battery_charge_rate` on the same inverter. Without it the window stays the cheapest period. A tariff with no cheaper-than-base period after the cheapest one is never extended. The planned window, the energy it should deliver and the expected finish are on the **Overnight Charge Window** sensor. In dry run mode the "would write" text shows the extended window.

**Cheap rate floor.** During a timed period cheaper than the base rate, the integration checks SoC against the floor (default 40%, 0 turns it off). In the cheapest period the full floor applies. In a cheaper-but-not-cheapest period it only acts when SoC is below the minimum SoC plus 5. When it acts, it writes the floor as the target SoC and turns enable charge target on, once per day.

### Immersion divert

The rule runs in this order. The first match wins.

0. No immersion switch set: do not heat. The reason reads `No immersion switch configured`.
1. Water below **Immersion Minimum Temperature**: heat, whatever the surplus.
2. Water at or above **Immersion Target Temperature**: do not heat.
3. Battery SoC below the divert threshold (default 80%): do not heat.
4. Surplus below the minimum (default 500 W) and no clipping: do not heat. Surplus is smoothed solar power minus house load minus battery charging power. Clipping means solar at 95% or more of the inverter maximum.
5. Battery cycle cost above the export rate: do not heat. Active only when a battery cost is set.
6. Currently off and water within the **Immersion Restart Gap** of the target: do not heat yet.
7. Otherwise heat.

Rules 1, 2 and 6 need a water temperature sensor. Without one, the immersion runs whenever there is surplus and the battery is above the threshold.

Solar power is smoothed with an average of the last smoothed value and the new reading, which stops the divert chasing a passing cloud.

The integration writes to your real immersion switch. After each automatic on or off it waits 10 minutes before the next automatic change. It turns off at once when the water is at or above the target.

When **Auto Immersion Divert** is off, the rule above is bypassed. The decision becomes off with the reason `Manual override`, and the managed switch asks for the real switch to be off. The minimum temperature rule does not run either.

Turning the managed switch on yourself starts a run to target. So does turning your real switch on from outside, once the integration has switched it at least once. The heater stays on until the water reaches the target. With no temperature reading, either because no sensor is set or because it is unavailable, the run lasts 5 minutes and then automatic control resumes. Turn it on again to extend it. Turning it off, here or outside, holds off automatic control for 10 minutes.

### EV charger

The integration finds Zappi (myenergi), Wallbox, OCPP, Ohme and Easee chargers by their entity names. It uses the first one found.

It does three things with the charger:

- **Signals.** EV Solar Surplus reads `Available` at 1380 W of net solar surplus or more. EV Charging Source reports Solar, Grid, Battery or Mixed. EV Draining Battery is `yes` when the charger is charging, is drawing power, and the battery discharges over 200 W. A charger that reports a charging status but draws no power, such as a Zappi waiting for the car, does not count.
- **Zappi mode.** For a Zappi with a charge mode entity, with a car plugged in and net surplus of at least 1380 W, the integration selects **Eco+** unless the Zappi is already in it. It never selects Stopped. In dry run it records the action and sends nothing.
- **Cost and distance.** EV energy, cost and kilometres use the car efficiency from the options.

Other brands get the signals only.

### Costs

Every cycle the grid import is priced at the current rate, after supplier discount and VAT, and split between the EV, the immersion and the rest of the house by their share of the house load. Export earns the export rate. See [Tariff](tariff.md#bill-line-items).

### Self-sufficiency, solar share and self-consumption

Three percentages answer three questions. **Self-sufficiency** is the share of what the house used that did not have to be drawn from the grid at the time. **Solar share** is the share of what the house used that your own solar covered: solar generated minus exported, over the house load. Grid import does not change it. **Self-consumption** is the share of your solar that you used on site rather than exported. The house load includes the EV charger and the immersion in all three.

Self-sufficiency takes the grid energy that went into the battery off the import before it compares the import with the house load. That energy is stored, not used. When the battery later supplies the house, the house is supplied from storage. So cheap overnight energy that the house uses the next day counts as supplied from storage, and the figure does not drop on the day the battery is charged. The grid energy that went to the house is the import minus the grid energy that went into the battery. EV and immersion energy bought from the grid is part of the house load, so it still counts as grid.

Example: the house uses 10 kWh, generates 8 kWh of solar, exports 2 kWh and imports 5 kWh (3 kWh of it into the battery overnight). The grid supplied the house with 2 kWh. Self-sufficiency is 80% (8 kWh of 10 kWh not drawn from the grid). Solar share is 60% (6 kWh of solar kept, over 10 kWh used). Self-consumption is 75% (6 kWh of 8 kWh kept). Use self-sufficiency to see how much of the load the grid did not have to supply, solar share to see how much your own solar covered, and self-consumption to see how much of your solar you used.

The Self-sufficiency sensors for today, yesterday, this week and this month show the working in their attributes:

| Attribute | Meaning |
|---|---|
| `house_load_kwh` | Everything the house used, EV and immersion included. |
| `from_grid_kwh` | Import that went to the house, not into the battery. |
| `grid_to_battery_kwh` | Import that went into the battery. |
| `from_solar_and_battery_kwh` | Load not drawn from the grid: `house_load_kwh` minus `from_grid_kwh`. |
| `basis` | `ac_charge_counter` when the AC charge counter was used. `import_only` when it is missing, so all import counts as grid. |

Example from a real day: 12.1 kWh imported, 7.5 kWh of it into the battery, and an 11.3 kWh load. The grid supplied the house with 4.6 kWh, so self-sufficiency reads 59%. Counting all the import as grid read 0%.

### Dry run

With dry run on, all decisions and sensors update. No charge target, floor, EV mode or immersion command is sent. The Last Skipped Action sensor shows the latest charge target, EV mode or automatic immersion command held back. The cheap rate floor reports through the Cheap Rate Floor sensor. The log carries a `DRY RUN` line for each one. A press of the managed immersion switch is recorded the same way and also leaves the real switch alone.
