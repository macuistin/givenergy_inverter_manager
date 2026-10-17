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
2. Raise or clear the repair issues: one for a minimum SoC above 30%, one for other charge slots with a window set, one for a battery cost of 0 after a week of battery tracking, one for a car charging from the grid at the base rate, and one while a charge setting reads back the old value after every write attempt (the repair clears when a later write or look finds the value).
3. Check GivTCP. If both the solar power sensor and the battery SoC sensor are `unavailable`, `unknown` or missing, the cycle fails and every entity of the integration becomes unavailable until GivTCP returns. See [Troubleshooting](troubleshooting.md#all-entities-are-unavailable). The cycle fails the same way when the entities still hold values but none has been reported for 10 minutes (a frozen GivTCP). It also records that, raises the repair **GivTCP has stopped updating**, and the charge target write-back at the start of the cheap window is skipped while it lasts. See [GivTCP data is frozen](troubleshooting.md#givtcp-data-is-frozen).
4. Look for an EV charger. Until one is found with its power, session and charge mode entities, discovery repeats about every 5 minutes (every tenth cycle). Entities that appear later are added with no reload.
5. Read the sensors: solar power, battery SoC, battery power, grid power, house load, the optional immersion temperature, forecasts, carbon intensity and inverter temperature, the EV charger, and the GivTCP daily energy counters.
6. Run the engine. It finds the current rate, adds the time since the last cycle to the today, week, month and year totals, applies the GivTCP daily counters to today's totals, and works out the charge target, immersion decision, bill figures, the battery overnight outlook and EV signals.
7. Record the day's first forecast value, for the Solar forecast today (charge plan) sensor, and the latest forecast for tomorrow. At midnight that tomorrow forecast becomes today's provider forecast, which the Solar forecast today (provider) and Solar vs provider forecast sensors, the forecast accuracy sensors and the accuracy correction measure against.
8. Apply the cheap rate floor, if it is due.
9. Apply the EV mode change, if one was requested.
10. Apply the immersion decision to your real immersion switch. The first cycle after a start or reload skips this step, because the real switch may not be up yet. It runs even when the managed switch entity is disabled. The managed switch shows the decision and lets you override it.

Three things happen on a clock instead of in the cycle.

| When | What |
|---|---|
| 00:00:00 local time | Daily reset. Today moves to yesterday. Monday also resets the week. The bill start day also resets the month and saves a snapshot. 1 January also resets the year. |
| One minute before the cheapest timed rate period starts, once a day | Write the charge target and window to GivTCP. A write that fails is tried again 2, 5, 10 and 20 minutes later |
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

When every attempt reads back the old value, the log has a `could not confirm` warning and the repair **The inverter did not take a charge setting** appears. It lists each setting and its entity, once, and clears when a later write is read back, when the entity is later seen at the value, and when the integration unloads. It is never raised in dry run, where nothing is sent. See [Writes to the inverter are not confirmed](troubleshooting.md#writes-to-the-inverter-are-not-confirmed).

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
3. **Forecast.** The tomorrow sensor is used when set, from 08:00 until midnight. Forecast sensors move on a day at midnight, so between midnight and 08:00 the integration uses the forecast it remembered just before midnight, which is the forecast for the day being charged for. In that window the tomorrow sensor is read as the day after, but only when a **Day after tomorrow forecast sensor** is set. Without one the plan has no day-after figure, in the evening or in the small hours, so the target does not step at midnight. If nothing was remembered, for example on the first night after install, it uses the estimate below. Otherwise the integration estimates from your latitude: inverter maximum output in kW times 4 hours times a factor for the month, with 1.0 for the sunniest month. Once five usable days are stored (a new install reads them from the recorder), the sensor forecast is first multiplied by the median of actual solar divided by forecast over the last 14 days, limited to 0.6 to 1.2. Days that clipped, or where the forecast or the solar was under 0.5 kWh, are ignored, and the seasonal estimate is never scaled. The reason shows `x0.70 recent accuracy` when the factor applies, and the attributes of the Overnight Charge Reason sensor show the measured factor, the applied factor and the usable days (`Waiting for data: 3 of 5 days` until the fifth). If a P10 forecast is available (the P10 sensor you chose, or the `estimate10` attribute that Solcast puts on its forecast sensors) and the conservatism is above 0, the corrected forecast becomes `(1 - w) x forecast + w x P10`, where `w` is the conservatism. With no P10 value the blend is skipped and the reason says so. See [Forecast accuracy correction](configuration.md#forecast-accuracy-correction) and [Where the P10 comes from](configuration.md#where-the-p10-comes-from).
4. **Skip rule.** The charge is skipped, with a target of minimum SoC plus 10, when SoC is at or above the skip threshold, no EV is plugged in, and the forecast is more than 0.8 times the smaller of 60% of the forecast and the usable battery capacity.
5. **Simulation.** Otherwise the integration simulates one day in 48 half-hour slots. Solar follows the shape of your forecast when its sensor gives one, and a bell curve centred on 13:00 between 06:30 and 19:30 when it does not. Solcast's forecast sensors carry their own half-hourly figures (the `detailedForecast` attribute, or `detailedHourly` when the half-hourly detail is switched off), so an east or west facing array, or a day that clouds over, is spread as the forecast says. Forecast.Solar's sensors carry totals only, so they keep the bell curve, and so does the seasonal estimate. The reason then ends `Solar follows your forecast's shape.`, and the **Solar forecast today (charge plan)** sensor has the attribute `solar_profile_source`, `forecast` or `standard curve`. The shape is remembered with the total, so from midnight to 08:00 the plan uses the shape of the day being charged for. Load follows your own per-slot history once two complete days are stored (the same weekday when three or more are available), scaled to the average daily load. Before that it is the average daily load spread evenly. It finds the lowest starting SoC that keeps the battery above the minimum all day.
6. **Adjustments.** Add 10 points if an EV is plugged in. Never go below minimum SoC plus 5, or above 100. A target below 25% is raised to 25%, so a very sunny forecast still leaves some charge if the sun does not arrive, and the reason ends `Raised to the 25% floor.` The shoulder months already plan from at least 70%, so they are unaffected. A skipped charge is not raised.
7. **Cap.** The target is capped at **Default overnight charge target**, which is 80% unless you change it. The cap also applies to the winter target of 100%.
8. **Overrides.** Manual overrides replace the result and the cap does not apply to them. See [Entities](entities.md).

**Held recommendation.** The calculated target moves by a few points from cycle to cycle, most of all in the small hours, when the average daily load rests on very little of today's data. The **Recommended Overnight Charge Target**, **Overnight Charge Reason** and **Estimated Overnight Charge Cost** sensors hold their last value until the calculated target is 5 points or more away from it, compared as the sensor shows it, after the cap. A published value then stands for at least an hour before the next step of that size shows, so a slow drift in the load estimate moves the sensor about once an hour, not every few minutes. A move of 15 points or more shows at once. A change between charging and skipping is measured by the charge it adds or removes, so skipping and charging 3 points are the same night and the sensors keep their value. This matters at dawn, when the solar reading flickers around the 10 W noise floor. The plan reads the settled solar state described under Battery overnight, and the hold covers what the flicker still moves. A skip is never shown while the battery is charging from the grid in the cheap-rate run: the charge itself lifts the SoC over the skip threshold, and the sensors keep the charge they showed. Overrides and the cap apply at once. The value written to the inverter is never held: it comes from the latest calculation at the moment of the write, and the sensors catch up on the next cycle.

**Forecast adjustments, in order.** Step 3 adjusts the forecast twice before the simulation uses it:

1. **Accuracy correction.** Multiply by the median of actual solar over forecast for the last 14 days, kept between 0.4 and 1.2. It needs 5 usable days. When the factor sits on a limit, the charge reason says so, for example `x0.40 recent accuracy (at the lower limit)`. A new install fills them from the Home Assistant recorder when it first loads (the last value of the forecast sensor before each midnight against that day's GivTCP solar total, about 9 days with the default 10 days of history), so the correction can apply at once. A day with clipping, or with a forecast or solar yield under 0.5 kWh, is not usable, and seeded days are never marked as clipped. A forecast that runs about 30% high gives a factor near 0.7, so the battery charges for 70% of what the service promises.
2. **P10 blend.** If a P10 forecast is available (the P10 sensor, or the `estimate10` attribute of a Solcast forecast sensor) and conservatism is above 0, take `(1 - w) x forecast + w x P10`.

The factor raises the forecast, up to 1.2, when the service runs low. The charge reason names each step that applied. Setup details are in [Configuration](configuration.md#forecast-accuracy-correction).

**A long reason.** Home Assistant keeps a state of at most 255 characters, and the reason can be longer when several steps applied. The **Overnight Charge Reason** state is then cut at the end of a sentence or clause and ends with `…`. While the state is cut, the whole reason is in the `full_text` attribute of the same sensor, and the Battery overnight card of the dashboard shows it. Every sensor with a text state works the same way, for example **Battery Overnight Outlook**, **Immersion Divert Reason** and **EV Mode Decision**.

The winter and shoulder months are settings under **Configure → Charge planning**. Until you change them they follow your latitude: in the north winter is December to February and the shoulder months are March, April, October and November, and in the south the same months move six months. A winter month charges to 100% whatever the forecast, and the cap still applies. A shoulder month raises the minimum to at least 70%. With **Plan winter charges from the forecast** on, a winter month runs the normal plan with that 70% floor instead of charging to 100%. An empty list turns its rule off. The seasonal solar estimate also uses your latitude.

The average daily load is today's house energy so far, less the EV charger's energy and the immersion heater's energy, scaled up to 24 hours. Early in the day that scaling rests on very little data, and the house counter moves in 0.1 kWh steps, so until 06:00 it is blended with yesterday's load, taken the same way. In the first 30 minutes after midnight it is all yesterday's, and by 06:00 it is all today's, so the total has no gap at midnight. With no yesterday on record, such as the first night, yesterday's load is taken as 15 kWh. It is at least 5 kWh. The car and the heater are left out because each is a separate, flexible load that runs for a few hours, not all day, and the per-slot load history leaves both out too. The only effect of a plugged-in car on the target is the 10 point buffer in step 6.

**Writing the target.** One minute before the cheapest timed period starts, the integration sets, in order: enable charge schedule on, charge start time, charge end time, target SoC, then enable charge target (on for targets below 100, off for 100). The window starts with the cheapest timed period and is sized to the plan (see below). On a skip night it writes the minimum SoC as the target, so the battery can discharge instead of being held at an old target. Nothing is written when the target SoC entity was not detected, or when the tariff has no timed period. The integration owns charge slot 1 only. When another slot (2 to 10) has a window set, it raises the repair **Other charge slots are active**, because the inverter also charges in that slot. See [Troubleshooting](troubleshooting.md#other-charge-slots-are-active).

**Sizing the window.** The inverter charges from the window start and stops at the target, so the cheapest hours come first. The cheapest period alone can be too short for a deep charge: a two hour period at 3.6 kW adds about 7 kWh. When the plan needs more time, the integration moves the window end later. Hours needed = (target SoC minus current SoC) x battery capacity / battery charge rate, plus 15% for the slowdown near full, rounded up to 5 minutes. The end never goes past the end of the run of timed periods cheaper than the base rate that follows the cheapest period. For example, with Nightboost 02:00 to 04:00 inside Night 23:00 to 08:00, the end can reach 08:00. If the plan fits the cheapest period, nothing changes. The charge rate is read from `number..._battery_charge_rate` on the same inverter. Without it the window stays the cheapest period. A tariff with no cheaper-than-base period after the cheapest one is never extended. The planned window, the energy it should deliver and the expected finish are on the **Overnight Charge Window** sensor. The sensor holds its end the way the target is held. As the battery runs down through the evening the planned end creeps later in 5 minute steps, so the sensor moves once the planned end is 15 minutes or more away and the shown end has stood for an hour, or at once when it is 45 minutes or more away. While a charge is running it stays as it was. The window written to the inverter is always the planned one, and the sensor catches up on the next cycle. In dry run mode the "would write" text shows the extended window.

**Cheap rate floor.** During a timed period cheaper than the base rate, the integration checks SoC against the floor (the Cheap rate floor SoC control, default 40%, 0 turns it off). In the cheapest period the full floor applies. In a cheaper-but-not-cheapest period it only acts when SoC is below the minimum SoC plus 5. When it acts, it writes the floor as the target SoC and turns enable charge target on, once per day.

#### Re-planning

The target is written once, a minute before the cheap window opens. The forecast, the load or a car can change after that, so with the **Re-plan overnight charge** switch on the plan is worked out again while the window is open, and a changed target is written. The switch is off by default, because nobody has yet confirmed that GivTCP applies a new target to a charge that is already running. Turn it on, watch one night with **Dry run** on, and look for `Would re-plan` in **Last Skipped Action (Dry Run)**.

A check starts when one of three things happens:

1. **The late check.** Once, at the later of 30 minutes after the first write and an hour before the window ends.
2. **The forecast moved.** The forecast the plan uses, or the day after's forecast, is at least 15% and at least 1 kWh away from the figure the last write used. Between midnight and 08:00 the plan uses the forecast remembered before midnight, which does not change, so only the day after's forecast, when a day after sensor is set, can start a check then.
3. **The car.** An EV charger was plugged in or unplugged since the last write.

A check writes only when the new target is at least 5 points from the last written one. At most three re-plans are written a night, so a night has at most four target writes. The window is never opened or moved: a re-plan sends the window that was written, and nothing is sent once less than 15 minutes of it remain or after it ends. A manual override (**Force Skip Overnight Charge** or a charge target override) ends re-planning for that night. A night written as a charge is not turned into a skip, because the charge itself lifts the battery over the skip threshold. A new target below the battery's charge is allowed, and the charge simply stops. The write goes through the same writer as the first one, so a value the inverter already holds is not sent again and the cooldown applies.

**Overnight Charge Reason** then starts with what happened, for example `Re-planned at 03:00: the forecast fell by 20%.`, and the write log shows a line with the reason `replan` that says `60% to 75%` and why. A restart inside the window ends re-planning for that night, except that the write log still counts the re-plans already made. Dry run records `Would re-plan the charge target from 60% to 75% (...)` once and sends nothing.

### Battery overnight

The overnight outlook asks whether the battery lasts until solar starts. It uses the current SoC, the usable capacity above the minimum SoC, the average daily load (see above, so without the EV charger and the immersion heater) spread evenly over 24 hours, and a window of hours:

- Before 08:00, the time left until 08:00.
- After 08:00 while solar is generating, from the time solar is expected to stop today until 08:00 tomorrow, from the current SoC. Once that time has passed and solar is still generating, from now.
- After 08:00 with no solar, from now until 08:00 tomorrow.

The window is counted to the minute, so the figure does not step as each hour starts. The time solar is expected to stop is the end of the last half hour with any solar in the shape of today's forecast (the half-hourly figures Solcast's sensors carry, see step 5 of [Overnight charge target](#overnight-charge-target)), or of tomorrow's when today's was not seen. Without a forecast shape it is 20:00, the end of the last half hour of the bell curve the charge plan uses. In daylight the window counts the evening, so a battery pause that starts late in the evening does not hide the load before it. For example, with a pause from 23:00 to 08:00 and solar expected to stop at 18:00, the midday figure counts 18:00 to 23:00. When solar stops at the time expected or later, the window already starts now, so the figure moves on smoothly at dusk. Solar that stops earlier than expected still makes the window longer at that point, by the time between the two.

Solar counts as generating once the reading has stayed at or above 10 W (the noise floor) for 5 minutes, and stops counting once it has stayed below 10 W for 5 minutes. A reading that crosses back restarts the count. At dawn and dusk the reading wanders across 10 W every few cycles. Without this, the window flipped between the night from the expected end of solar and the whole day with each crossing, and the status flipped between "Estimated shortfall" and "should last". The charge plan reads the same settled state. Only the solar state waits. The SoC, the load and the shortfall are read fresh every cycle, so a real shortfall shows at once. After a restart or a gap of an hour the first reading is taken as it is.

The charge plan skips a night only when this check passes, and it uses the same window and load. **Estimated SoC at Sunrise Without a Charge** is the SoC left at the end of the window, never below the minimum SoC. **Battery Overnight Outlook** and **Battery Overnight Confidence** read the same calculation. The confidence is Safe, Warning or Critical. The dashboard says it in words: Lasts the night, Only just lasts the night and May run low.

The estimate is a pessimistic one by design, in two ways. It spreads the day's average load evenly over the window, so a night that is quieter than the day reads worse than it will be: an evening that uses 0.5 kWh an hour is judged at the daily average, often twice that. And it counts only the charge the battery holds now. A cheap-rate charge planned for later tonight is not added, so a shortfall in the evening is a shortfall without that charge. A **Battery may run low** status in the evening, with a charge planned for the cheap period, does not mean the battery will run out. While a planned charge counts, the words say so: the summary reads, for example, `Lasts the night · 36% at sunrise without a charge, about 89% with tonight's charge`, and a Warning or May run low says whether tonight's charge covers it (`May run low without a charge · tonight's charge covers it, about 67% at sunrise`). The level itself is still judged without the charge. A charge counts when a timed window adds charge before 08:00. On a skipped night, with no timed window, or once the window is over, the words give the one figure. Check **Tonight's Charge Plan** next to it. The minimum SoC reading is the floor of the estimate, not a measurement.

The calculated figure steps when the day's energy total resets at midnight, when the window flips at 08:00 and when solar stops earlier than expected in the evening. The published **Estimated SoC at Sunrise Without a Charge** follows the calculated figure at no more than the pace the inverter can charge or discharge the battery (inverter maximum output over battery capacity, for example 5 kW over 19 kWh is about 26 points an hour). A step becomes a ramp of about half an hour. The status and the Critical level of the confidence sensor use the calculated figure, so a real shortfall shows at once. The words that quote a figure (**Battery Overnight Outlook**, and the `summary` and `explanation` of **Battery Overnight Confidence**) quote the published one, so they always agree with the sensor. After a restart or a gap of an hour the held value is dropped and the sensor starts from the calculated figure.

**Two sunrise figures.** The figure above leaves tonight's planned charge out on purpose, because it answers "will the battery last without a charge". In the evening that makes it sit on the minimum SoC for hours, even with a charge planned and the battery on course to finish the night well above the minimum. **Estimated SoC at Sunrise With the Planned Charge** projects the same night with the charge in it:

1. The battery runs down on the house load from now to the start of the charge window.
2. The window adds charge at the charge rate the plan uses, up to the target. The window is sized for the SoC the battery will have when it opens, which is what the plan writes then, so the evening figure does not wait for the window to grow.
3. The battery runs down on the house load from the end of the window to 08:00, never below the minimum SoC.

It reads the next 08:00 on the clock, so it stays steady through the day and does not step at midnight. A window that is running starts from the current SoC. A battery already at the target when the window opens adds nothing. With no charge rate known, the battery is assumed to reach the target. On a skipped night, with no timed charge window, or once the window is over, it equals the figure without a charge. The two figures use different loads on purpose. The figure without a charge, which night survival judges, spreads the daily average evenly over the hours. The figure with the charge uses the learned per-slot load profile that the charge plan simulation uses, scaled to the same daily average, so a quiet night reads as quiet. Until there is a usable profile (a new install, or too little history) it falls back to the flat average. The `basis` attribute ends with the load it used. Its attributes show what it is made of: `soc_at_charge_start`, `charge_added_pct`, `charge_window` and `basis`. It does not feed Battery Overnight Outlook or the level of Battery Overnight Confidence, and no decision reads it. The words of Battery Overnight Confidence (`summary` and `explanation`) quote it while a planned charge counts.

### Why the battery never sells stored charge back to the grid

The integration does not discharge the battery to the grid, and does not advise it either (see the
non-goals in `ROADMAP.md`). Write risk is one reason. The other is that the arithmetic rarely pays,
even for the most tempting case: a battery well above its minimum late in the evening, after the
day's load is mostly done.

**An example with round numbers.** A 20 kWh battery is at 60% at 23:00. You ask whether to export
half of it, 10 kWh, before the cheap window opens. The tariff has a night rate of 0.18, a boost
rate of 0.10 for two hours, and an export rate of 0.20. The charge rate is 3 kW.

1. **What it earns.** Discharging stored energy to export it loses about 6% in the battery and
   inverter, so 10 kWh earns about 10 x 0.94 x 0.20 = 1.88. Solar exported directly does not pay
   this loss.
2. **What it costs to refill.** The battery must return to 60% to be where it would have been.
   A 2 hour boost window at 3 kW adds about 6 kWh. Refilling that much costs 6 x 0.10 = 0.60. The
   other 4 kWh is refilled at the night rate, 4 x 0.18 = 0.72.
3. **The result.** The gain is 1.88 less 1.32, about 0.56, before battery wear. A few cents per
   kWh cycled takes most of that away. When the night rate is close to the export rate, the part
   refilled at the night rate earns nothing.

**Why it often does not pay even when the sums look close.** The example assumes the exported
energy would otherwise have been wasted. It usually is not:

- **If the next day is dull**, the energy exported tonight is energy the battery does not have
  tomorrow. It is replaced from the grid at the day rate, the dearest rate in the tariff.
- **If the next day is sunny**, the solar that refills the battery would have been exported at the
  same rate anyway. Exporting the stored energy earlier adds no sale. It moves one.
- **Until the cheap window opens**, the stored energy also covers house load that would otherwise
  be imported at the night rate. Exporting it moves that load onto the grid first.

Each of the three uses (this evening's load, tomorrow's load before solar, tomorrow's exportable
surplus) is worth as much as selling the energy tonight, or more. The one clear exception is solar
that would otherwise be clipped: the battery is full and the inverter is still generating. That is
a charge target and headroom question, not a reason to discharge the battery to the grid.

**The general form.** Before any battery-to-grid export, three things must hold at once. Export now
must beat the cost of refilling at the night rate, including round-trip loss and wear. The energy
must be otherwise wasted, not merely idle. And tomorrow's replacement for it must not come from
the day rate. A fixed export rate rarely clears that bar by more than a few cents a night, so
forced export stays a won't-have.

**Further reading.** The pattern (self-consumption usually beats export, arbitrage needs a real
spread) is described outside this project too:

- Palmetto, [Backup vs. Arbitrage Battery](https://palmetto.com/home-electrification/backup-vs-arbitrage-battery):
  on NEM 3.0, "individuals save more money storing and consuming solar power than exporting it
  to the grid for credits, except in a few rare cases."
- Kora, [Are Home Batteries Worth It in 2026?](https://korapower.com/blogs/education/are-home-batteries-worth-it-2026):
  "the math only works if the spread is real... if you are on a flat rate, it has almost none."
- Elovane, [TOU Arbitrage: When Battery Storage Actually Makes Financial Sense](https://smarttechinvest.com/elovane/blog/solar-battery-tou-arbitrage):
  the payback swings from "deeply negative to solidly positive" on the price spread alone, with
  worked examples at $0.10/kWh and $0.33/kWh spreads.
- Avepower, [Energy Arbitrage: How Battery Storage Saves Money](https://avebattery.com/blog/energy-arbitrage/):
  "for many residential systems, the primary benefit is not selling electricity back to the grid.
  It is reducing expensive grid imports during peak hours," and exporting stored energy depends on
  local tariff and export-credit rules.
- SurgePV, [Solar Battery Grid Arbitrage Strategy 2026](https://www.surgepv.com/blog/solar-battery-grid-arbitrage):
  describes where battery-to-grid export does pay, a variable export price that falls below the
  overnight import rate at some times and rises above it at others. A flat export rate does not
  have that.
- MGEVs forum, [Is it still worth exporting your home battery?](https://www.mgevs.com/threads/is-it-still-worth-exporting-your-home-battery.25439/):
  an argument for the opposite case, with a measured round-trip efficiency of about 85%, on a
  variable-export UK tariff.

### Battery pause

GivTCP can pause the battery for a time of day window. On an install that does, the battery serves nothing in the window: the house runs from the grid and the battery holds its charge. Charging can still happen. Before this was read, the night estimates ran the battery down on the house load for the whole night. With a pause from 23:00 to 08:00 and the battery at 60% in the evening, the sunrise figure could read near the minimum while the battery really held about 60% until morning, and the charge plan asked for a full charge on that wrong basis.

The integration reads three GivTCP entities on every cycle: `battery_pause_mode`, `battery_pause_start_time_slot` and `battery_pause_end_time_slot`. They are never part of the setup, so a pause that is set later, changed or removed is followed on the next cycle with no reload.

| Mode | Treated as |
| --- | --- |
| `PauseDischarge` | A pause. The battery does not discharge in the window |
| `PauseBoth` | A pause for discharge. It also stops charging, see below |
| `PauseCharge` | No discharge pause. The battery still serves the house, so the estimates are unchanged. It stops charging, see below |
| `Disabled` | No pause |

Any other text, a start or end that is not a time, a start equal to the end, and entities that are missing or unavailable all give no pause, and the install reads as it did before. A window may wrap midnight. The time can be read from the drop-down or from the time picker, whichever GivTCP publishes.

While a pause covers part of a span, that part adds no load to the battery:

- **Battery Overnight Outlook, its confidence and Estimated SoC at Sunrise Without a Charge** count only the hours outside the pause. The window is the same one as above, so only the part of the pause inside that window counts.
- **Estimated SoC at Sunrise With the Planned Charge** leaves the paused minutes out of the load before the charge window and after it. A pause that falls inside the charge window changes nothing, because the window adds no house load.
- **Tonight's charge plan** simulates the next day in 48 half-hour slots. A slot that is paused does not run the battery down when solar falls short of the house load. Solar above the load still charges the battery, paused or not. A slot that is only partly paused is paused for that share. The plan therefore asks for less charge on a paused night, and it can skip a night that the battery lasts only because of the pause.

The words say so once, where the figures are quoted. The sentence `The battery is paused from 23:00 to 08:00.` is in **Battery Overnight Outlook**, the explanation of **Battery Overnight Confidence**, the `basis` of **Estimated SoC at Sunrise With the Planned Charge** and **Overnight Charge Reason**, and the summary of Battery Overnight Confidence ends with `battery paused 23:00 to 08:00`. They say it only when the pause falls in the night being judged. A pause that falls wholly in the day, or no pause, leaves the text as it was.

The integration only reads the pause. It never writes it, with or without dry run. A temporary pause started from GivTCP's temporary pause controls is not read. The estimates do not model a stopped charge. Instead, when the mode is `PauseCharge` or `PauseBoth` and its window covers part of tonight's planned charge window, the inverter will not charge there, and the repair **The battery pause stops tonight's charge** says so (see [The battery pause stops the charge](troubleshooting.md#the-battery-pause-stops-the-charge)). To let the battery serve the house at night or charge in the cheap window, change the mode in GivTCP.

### Tomorrow's outlook

The **Tomorrow Outlook** sensor estimates what the solar day the charge plan is for should cost. That is the same day the plan uses: tomorrow until midnight, and today from midnight to 08:00.

It runs the plan's own simulation of that day in 48 half-hour slots, with the same forecast (after the accuracy correction and the P10 blend), solar shape, load and battery pause. The battery starts at the level tonight's charge leaves: the target, or the level now on a skipped night or when the battery is already above the target. In each slot:

- When solar and the battery cannot cover the load, the grid covers the rest. The battery stops at the minimum SoC, and in a paused slot the grid covers the whole shortfall.
- When the battery is full, the solar it cannot take goes to the grid.

Each slot's import is priced at the rate in force at the start of that half hour, after discount and VAT, with the tariff in force on that day, so a dated tariff change counts. Export earns the export rate. Tonight's charge is the **Estimated Overnight Charge Cost** figure.

The state is the import cost plus the charge cost, less the export credit. The attributes hold each line in kWh and money, the battery level at the end of the day and the lowest it reaches, the forecast used, a `basis` sentence that names the forecast source and the load, and a `table` for the dashboard. For example, 2.0 kWh from the grid for €0.60 and 10.0 kWh to the grid for €2.00, with no charge, is a day that earns €1.40. The state is then -1.40 and the table shows `‑€1.40`.

It is an estimate from the plan's model, not a bill:

- The battery starts the day at tonight's level, takes or gives any power the slot needs, and a charge pause is not modelled.
- The load is the plan's average daily load, without the EV charger and the immersion heater, so solar they would take counts as export. Early in the day the average is a rough guess.
- The standing charge and the levy are left out, and the charge cost is before discount and VAT, as on its own sensor.
- Without a forecast sensor it uses the seasonal estimate, and `basis` says so. Without a battery capacity the state is unknown.

### Immersion divert

The rule runs in this order. The first match wins.

0. No immersion switch set: do not heat. The reason reads `No immersion switch configured`.
1. Water below **Immersion Minimum Temperature**: heat, whatever the surplus.
2. Water at or above **Immersion Target Temperature**: do not heat.
2a. With **Immersion Scheduled Heating** on and a temperature sensor: heat while the cheapest window is open or a ready time needs the heater now. See [Scheduled immersion heating](#scheduled-immersion-heating).
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

### Scheduled immersion heating

By default the immersion runs only on solar surplus, plus the minimum temperature rule. **Immersion Scheduled Heating** adds two kinds of grid heating. It is a switch, off by default, and it keeps its state across a restart. It is created while an immersion switch and a water temperature sensor are both set. Nothing here runs without a temperature sensor, because without one the integration cannot know when the water reached its target. Surplus diversion carries on as before.

The scheduled rules sit after the temperature rules and before the surplus rules. The minimum temperature and target temperature rules above still come first, so the water is never heated above the target and never left below the minimum. **Auto Immersion Divert** off still stops everything.

**Cheapest window.** The window is the cheapest timed rate period, the one the battery charge starts in, for example 02:00 to 04:00. It counts only when its rate is below the base rate. While it is open the heater runs until the water reaches the target, then stops. The battery level and the solar sensors do not matter. At the window start the water must be at least the **Immersion Restart Gap** below the target, so warm water from the day before is left alone (with 55 °C and 5 °C, a start needs water below 50 °C). When the window ends the heater stops, with the water below target or not. It never runs on into a dearer band.

If the heater cuts itself off in the window with the water still below the target, for example a 60 minute auto-off on the device, the integration waits out the 10 minute switch hold and turns it on again. The run carries on to the target even when the water is inside the restart gap by then.

**Hot water ready by.** List the times of day the water has to be at its target in the immersion options, for example 07:00 and 19:00. For the next ready time the integration works out how long the heater has to run, then places those hours in the cheapest bands left before it:

1. The hours needed are the degrees short of the target divided by the heating rate, plus 15%.
2. The time until the ready time is cut at every rate change. The hours go into the cheapest bands first, and a partly used band is entered late. Where two bands cost the same, the later one fills first, which keeps the day free for solar surplus.
3. The heater is wanted when the current band is used up. If the hours cannot fit, it runs now and **Immersion Divert Reason** says `too late to be ready in full`.

For 07:00 with the cheapest window 02:00 to 04:00 inside a Night band to 08:00, the window comes first and any hours left go to the Night band after it, never the base rate. For 19:00 with only the base rate on offer, nothing runs until the last moment, so solar surplus gets the afternoon, and a cold tank at 17:00 starts about when the heating needed would just fit. The plan is recomputed every cycle from the live temperature. It follows solar that heated the water, a run cut short by the device, and hot water drawn.

The heating rate is in degrees per hour. The integration measures it from its own runs: a stretch with the heater on and the temperature readable, at least 20 minutes long and at least 2 °C of rise. It keeps the last 5 and plans with their median. Until a run has been measured it assumes the element heats a 300 litre cylinder, which is slow, so the first plans start early. The **Immersion Water Temperature** sensor shows `ready_by`, `expected_ready`, `heating_rate_c_per_h` and `heating_rate_source` (`learned` or `assumed`). The attributes are there only while ready times are set and Immersion Scheduled Heating is on.

The same sensor has a `planned_heating` attribute, a sentence that says what the immersion plans. It is there while Immersion Scheduled Heating is on and the water temperature is read, with or without ready times. It does not change what the immersion does. It reads the plan above and the cheapest window, and says one of these:

- `Heating planned for the 19:00 ready time: 17:10 to 18:30 at the Day rate.` The plan heats later. Heating in two bands lists both, in time order.
- `Heating now to be ready by 19:00 (water 42.0°C, target 55°C): until 18:30 at the Day rate.` The plan wants the heater on now. When the water cannot be ready in time it adds that.
- `No heating planned for the 19:00 ready time (water 54.4°C, ready). Next possible heating: 02:00 to 04:00 slot, only if the water is below 51°C by then.` The water is at or above the temperature the immersion restarts at (the target less the restart gap), or the run would be under 5 minutes, so it counts as ready. The immersion can still add a few minutes just before the ready time to reach the exact target. The next window is the cheapest rate window, and it heats only if the water has cooled below the restart temperature by then.
- `Heating now in the Night slot until 08:00 tomorrow (water 40.0°C, target 55°C).` The cheapest window is open and heating the water.
- With no ready time: `No ready time is set. Next possible heating: 23:00 to 08:00 slot, only if the water is below 51°C by then.` On a tariff with no window cheaper than the base rate it says `No heating planned: no ready time is set and the tariff has no cheaper slot.`

The rate band is the name of the tariff period the heating falls in. On a flat tariff there is no window to name.

Dry run records `Would turn_on immersion heater (reason: ...)` for the scheduled rules and sends nothing. The switch hold, the verified write and the manual overrides work as for surplus diversion.

**Moving from the device timers and home automations.** Switch the heater's own timers off, or leave only a long auto-off as a backup. Disable any automation that turns the heater on at set times or off at the target. Then turn **Immersion Scheduled Heating** on and enter the ready times. What the old automations did is covered:

- Heat below the minimum temperature at any hour: the minimum temperature rule, which runs all day and night.
- Switch off at the target, whatever turned the heater on: the target rule. A heater switched on by a timer or a person while the water is at or above the target is switched off at the next cycle or the one after. A run started outside below the target runs to the target and stops.
- A time limit on the day: the cheapest window and the ready times replace it, and the target rule keeps the heater off above the target at every hour.

A device auto-off during a run you started yourself ends that run, in the same way as pressing the switch off. The integration does not fight it. Scheduled heating restarts the heater after the hold if the window or a ready time still needs it.

### Alternative water heating advice

Some homes heat the same cylinder another way too: an oil or gas boiler, a heat pump or solid fuel, through a second coil. Turn on **Alternative water heating** under Configure and give its cost. With an immersion switch to compare with, the **Water Heating Cheapest Source** sensor then says which source is cheapest to heat the water. It is advice. The integration does not control the other system, and it never turns the immersion on or off because of it.

You name the alternative with a **label**, such as Oil, Gas or Heat pump (up to 20 characters, Oil by default). The sentences below use your label. Inside a sentence it is written in lower case, unless you typed it in capitals, so `LPG` stays `LPG`.

Each source is a cost per kWh of heat, in your currency:

- **The alternative**: the cost you set. Choose its unit. **The price of a litre of oil** is divided by the heat a litre gives. The integration assumes a boiler at 85% efficiency and 10.35 kWh of energy in a litre of kerosene heating oil, so a litre gives 8.8 kWh of heat. These two figures are fixed in the code and are not options. **The cost of a kWh of heat** is what one kWh delivered to the water costs, with the efficiency already in it: the gas price per kWh divided by the boiler efficiency, or the electricity rate for the heat pump divided by its coefficient of performance. An optional cost sensor overrides the cost while it reads a number above zero, in the same unit.
- **Electricity from the grid**: the unit rate in force now, after the supplier discount and VAT, as the cost sensors apply them. The immersion turns all its electricity into heat, so a kWh of electricity is a kWh of heat.
- **Solar surplus**: the export rate, because heating the water with surplus gives up what the surplus would have earned. It counts as a source only while the immersion rule would divert the surplus: the battery is at the divert level and the surplus is at least the minimum surplus.

The state is the cheapest source now: `electricity`, `solar` or `alternative`. A tie goes to solar, then the grid, so the alternative needs a real saving. The `suggestion` attribute is a sentence, for example `Oil is cheaper than electricity until 23:00 (saves about 0.16 per kWh of heat). Heat the water with the oil system now.` When electricity is cheapest, it says when the alternative becomes cheaper. When the alternative is cheapest, it adds when electricity is cheapest if the water can wait. The `alt_label` attribute holds your label.

The other attributes are the alternative's cost (`alt_cost_per_kwh`), the grid cost now, the cheapest grid cost up to the horizon, the saving of the alternative per kWh against the cheapest electric source now (`alt_saving_per_kwh`, negative when it is dearer), the hours in the next 24 when it beats the grid (`best_hours_for_alt`, or `all day` on a flat tariff), the horizon and the cheapest source over it. The horizon is the next hot water ready time when the immersion options list one, whether or not Immersion Scheduled Heating is on, and the next 24 hours otherwise. Solar counts over the horizon only while there is surplus now, because the integration does not forecast surplus by the hour.

The grid hours come from the tariff in force today, cut at every rate boundary, so a tariff with a cheap night window gives hours for the alternative by day and none at night. A tariff change dated inside the next 24 hours is not looked ahead to.

**When to start it.** The integration does not switch the alternative system, so the advice says when you should. With a water temperature sensor, Immersion Scheduled Heating on and a ready time set, the suggestion names a start time for the next ready time, for example `For the 19:00 ready time: turn the oil water heating on at 16:30 (about 90 minutes). The immersion will only top up. Saves about 0.22 per kWh of heat.` It is worked out like this:

1. The immersion plan for the ready time is placed as for [Scheduled immersion heating](#scheduled-immersion-heating): as late as possible, in the cheapest bands. Its start is the time the immersion would have to start, and its cost is the hours-weighted grid rate of the bands it uses (after discount and VAT).
2. The alternative is suggested only when a kWh of heat from it costs less than that, and less than the export rate while solar surplus is being diverted. A ready time that the cheap night band covers, for example 07:00 asked at 01:00, gets no start, and the suggestion says electricity is cheaper.
3. The run lasts as long as the immersion would need to lift the water to the target, using the same heating rate (learned or assumed) and the same margin. A boiler coil usually heats faster than the element, so this is a long run: the start is early, never late.
4. The start is that run before the time the immersion would start, rounded down to the minute. If the alternative switches on at that time, the water is at the target before the immersion needs to start, and the immersion does nothing. If it is not switched on, the immersion plan still has the water ready. The immersion plan is not changed by the advice.
5. When it is already too late for the alternative to finish before the immersion starts, the suggestion says to start it now and that the immersion will also run.

When the water is already at the target, no start is suggested and the suggestion says there is nothing to heat.

No start is suggested either when the water is at or above the temperature the immersion restarts at (the target less the restart gap, 51 with a target of 55 and a gap of 4), or when the run would be shorter than 5 minutes. The water is as good as ready, and the suggestion says so: `For the 19:00 ready time: the water is expected to be ready with no heating needed.`

The attributes `alt_start_by` (a local time), `alt_run_minutes` and `alt_for_ready_time` are present only while a start is suggested. Use them in your own automations or notifications, for example a notification at `alt_start_by`. The suggestion reads the water temperature now, so once the alternative is heating the start moves later and then disappears when the water reaches the target.

**Keeping the water warm.** Hot water drawn through the day can cool until the immersion's minimum temperature rule tops it up at whatever the rate is. When the water is at or below the lower of the minimum temperature plus the restart gap and the target less the restart gap (50 with a minimum of 45, a gap of 5 and a target of 55), solar surplus is not already heating it and the alternative is cheaper than the grid rate in force now, the `alt_keep_warm` attribute says to run it for about N minutes now, for example `Water is at 49.5°C, close to the 45°C minimum. Oil is cheaper than the grid now (0.16 against 0.38 per kWh of heat): run the oil water heating for about 40 minutes to avoid an electric top-up.` N is the time to lift the water to the target at the immersion's heating rate with the margin, rounded up to 5 minutes. Inside a cheap slot, where the alternative is not cheaper than the grid, there is no keep-warm suggestion. It needs no ready time and works with Immersion Scheduled Heating on or off. With the default minimum of 50, gap of 5 and target of 55, the limit is 50, because the minimum plus the gap would be the target itself.

**Which sentence you get.** The `suggestion` says one thing, in this order: the start for the next ready time, then the keep-warm run, then that electricity or solar is cheaper for the ready time, then the plain sentence for the cheapest source now. When both a start and a keep-warm run apply, the suggestion gives the start and `alt_keep_warm` still holds the keep-warm sentence. With no water temperature reading the plain sentence is unchanged. The recurring schedule is never part of the `suggestion`: it has its own attributes and its own line on the dashboard.

**A recurring schedule.** Over time the integration learns when the immersion heats the water from the grid at a rate above the alternative, and suggests running the alternative at those times. It needs Alternative water heating on with a cost, and an immersion switch, like the rest of the advice. It needs no water temperature sensor and no ready time. The integration does not switch the alternative system: the suggestion is advice, and the attributes below are there for your own automations.

For each hour of the last 14 complete days and the day in progress, the integration keeps the grid energy the immersion used and what it cost, at the rate in force then after discount and VAT. Energy that solar surplus covered is not counted. The alternative's cost is not kept: it is read when the suggestion is worked out, so a change to the cost applies to the whole record at once. The record is a few hundred numbers in the integration's stored data. It survives restarts, and nothing is recorded while there is no cost set.

The suggestion is made like this:

1. Nothing is suggested until the record holds 7 complete days, a week, so each weekday has been seen once. Today is left out until it ends.
2. An hour of the day counts as a habit when, on at least a third of the days, the immersion used at least 0.25 kWh from the grid in it at a cost per kWh above the alternative. A third is two or three days a week, which catches a daily or weekday routine and ignores a one-off. 0.25 kWh is about five minutes of a 3 kW element, so a trickle of grid energy that surplus did not quite cover is not a heating run.
3. Adjacent habit hours join into one block. The window ends at the start of the block's first hour, where the immersion usually started, so the alternative runs just before it and the immersion finds the water at the target. The window lasts as long as the immersion took on the days it ran, at the immersion's heating rate, rounded up to 5 minutes. A boiler coil usually heats faster, so this is long enough. A window never starts before the heating ahead of it ended.
4. The saving of a window is what the dearer-than-alternative grid heat in its hours cost, less what the same heat would have cost from the alternative, over the record. A window that saves less than 0.25 a week (about 13 a year) is dropped, and the three biggest savings stay, in time order.

For example: `Over the last 14 days the immersion used about 14 kWh of grid electricity that cost more than oil, mostly around 13:00 and 19:00. Running the oil from 12:30 to 13:00 and 18:00 to 19:00 would have saved about 6.00 over those days.` Heating in a cheap slot, where electricity is cheaper than the alternative, never makes a suggestion, and neither does an alternative that is dearer than what the immersion paid.

The Water Heating Cheapest Source sensor carries the result in four attributes, kept apart from `suggestion`:

- `alt_schedule`: a list of windows as `HH:MM to HH:MM` in local time, empty when nothing is worth suggesting.
- `alt_schedule_saving`: the total saved over the record, in your currency, as a plain number.
- `alt_schedule_days`: how many complete days the suggestion read, up to 14.
- `alt_schedule_suggestion`: the sentence. Present only while there is a schedule.

All four are absent until the record holds 7 days. The hours are read at hour resolution, so a window ends on the hour even when the immersion usually started part way through it. The saving counts only the days the immersion heated, and an alternative that runs on a day the water needed no heating is not counted in it.

**Which attributes are recorded.** The costs, the hours, the start and keep-warm attributes and the four schedule attributes change often or hold lists, so Home Assistant keeps them live but does not write them to the history database. The `suggestion` and `alt_label` are recorded.

**An oil price from 0.17 or earlier.** Version 0.18 replaces the two oil price options with this setting. On the first start after the upgrade an install that had an oil price or an oil price sensor gets Alternative water heating switched on, the label Oil, the unit litre and the same price or sensor, and the old options are removed. The advice reads as it did, and nothing needs doing. The attributes that began `oil_` begin `alt_` now, `best_hours_for_oil` is `best_hours_for_alt`, and the state `oil` is `alternative`: update any automation or card that reads them.

### EV charger

The integration finds Zappi (myenergi), GivEnergy (through GivTCP), Wallbox, OCPP, Ohme and Easee chargers by their entity names. It uses the first one found.

It does four things with the charger:

- **Signals.** EV Solar Surplus reads `Available` at 1380 W of net solar surplus or more. EV Charging Source reports Solar, Grid, Battery or Mixed. EV Draining Battery is `yes` when the charger is charging, is drawing power, and the battery discharges over 200 W. A charger that reports a charging status but draws no power, such as a Zappi waiting for the car, does not count.
- **Surplus mode.** For a Zappi or a GivEnergy charger with a charge mode entity, with a car plugged in and net surplus of at least 1380 W, the integration selects the mode that means "use surplus only" unless the charger is already in it: **Eco+** on a Zappi, **Solar** on a GivEnergy charger. It reads the options the select offers and picks that one by name. A mode with `stop`, `off`, `pause`, `fast`, `boost`, `grid`, `max` or `hybrid` in its name is never selected, so it never selects Stopped or Fast, never Grid, and never Hybrid, which draws a constant 6 A from the grid. A charger whose select offers no surplus-only mode is left alone and the EV Protection Reason says so. In dry run it records the action and sends nothing, and the write skips when the charger is already in the mode and honours the same 300 second cooldown.
- **GivEnergy charger.** GivTCP publishes it as a device called GivEVC when its EVC setting is on. The integration reads Connection Status and Charging State for the plug and charging state, Active Power and Charge Session Energy, and Charging Mode. It never writes Charge Control, so it never starts or stops a session, and never writes Plug and Go. If you set Grid yourself and surplus appears, the integration moves the charger to Solar, as it does for a Zappi in Fast. **It has not been tested against a real GivEnergy charger.** The entity names are from GivTCP's datapoint reference and the state strings are from its source.
- **Base-rate alert.** When the car draws at least 1380 W, the grid supplies at least 1380 W, the rate in force is the base rate and the tariff has a cheaper timed band, the repair **EV is charging at the base rate** appears after 5 minutes. It is raised once and clears when the session ends or the rate drops. A flat tariff never raises it, and an install with no charger evaluates nothing. See [Troubleshooting](troubleshooting.md#ev-is-charging-at-the-base-rate).
- **Cost and distance.** EV energy, cost and kilometres use the car efficiency from the options.

Other brands get the signals and the base-rate alert only.

### Costs

Every cycle the grid import is priced at the current rate, after supplier discount and VAT, and split between the EV, the immersion and the rest of the house by their share of the house load. Import above the load went into the battery and stays in the rest of the house. Export earns the export rate. See [Tariff](tariff.md#bill-line-items).

### Bill audit and the cost without solar or battery

The **Bill audit** sensor lays the running bill period out like a supplier bill. Its `html` attribute holds two tables. The Bill & tariff view of the dashboard shows the same figures as smaller tables from the `bill_table` and `days_table` attributes:

- **The days.** One row for each finished day, and one for today so far. Each row lists the kWh imported in each rate period, what that cost at the billed rates, the kWh exported and the credit, the kWh the house used, and the **Without** cost, which is what that use would have cost from the grid.
- **The bill.** Energy at the rates, supplier discount, standing charge, PSO levy, VAT, export credit and the total, in three columns: as billed, with no solar or battery, and the saving.

The total is the Bill sensors' total, because both come from the same period accumulator and the same bill sums. A day that was not recorded, such as one before this was added, shows as one "Earlier, not itemised" row that makes the rows add up to the period.

Home Assistant's markdown card drops the styles the `html` attribute uses, so the same figures are also published as markdown tables, which the card draws as plain tables:

- `bill_table` on **Bill audit**: the bill line by line, in three columns: **You paid**, **Would have paid** (the same use with no solar or battery) and **Saved**. The export credit has no **Would have paid** figure, because with no solar there is nothing to export. The total is in bold.
- `days_table` on **Bill audit**: one row a day, newest first, with today marked "(today)". The columns are the kWh imported, **You paid** (the import cost less the export credit), **Would have paid** (the day's use priced from the grid) and **Saved**. Days before daily records began are one row, "Before daily records". Before any day is recorded it is one sentence instead of a table.
- `summary_table` on **Previous bill audit**: what you paid, what you would have paid and the saving for the last bill period. `period` holds its dates as text, such as `16 Sep to 15 Oct`. With no archived period the table is one sentence and `period` is empty.

Money has two decimal places and the currency symbol from the options. A negative amount, such as a credit, starts with a non-breaking hyphen, so a narrow card never wraps the sign away from the number. To show a table, put `{{ state_attr('sensor.givenergy_inverter_manager_bill_audit', 'bill_table') }}` in a markdown card.

**Without solar or battery** is the house's whole use, priced as it was used. It is not a guess. Every cycle the integration prices the house load at the rate in force at that moment, with the supplier discount and VAT, the way it prices what you import. The sensors **Cost Without Solar or Battery** (today, this week, this month) show that energy cost. **Bill Without Solar or Battery** adds the standing charge, PSO levy and VAT, takes off no export credit, and sits beside **Accrued Bill**.

**How days are stored.** At midnight the day that ended is added to a list for the bill period. When the period ends, the list goes into that period's saved snapshot and the next period starts empty. The first day of a period also stores the tariff in force, and a later day stores it only when it changed, so a tariff that changes mid-bill is recorded on the day it changed and an old period keeps the rates it was billed at. The **Previous bill audit** sensor shows the last archived period. The integration keeps 12 periods.

**What it does not do.** Each day's cost uses the rates in force that day. The standing charge, PSO levy, VAT and discount in the bill use the tariff in force now, as the Bill sensors do. When the tariff changed during a period, the audit says so.

### Saving and the energy in the battery

**Saving vs Grid Today** is what the house load would have cost from the grid at the time it ran, minus what you paid (import cost minus export earnings). Energy bought to fill the battery is part of what you paid, but it only earns its keep when the battery gives it back. Counted alone, the saving reads negative after a cheap overnight charge and recovers through the day. So the saving also counts the energy the battery holds:

saving = load priced at the grid rate at the time, minus net import cost, plus stored energy value

- **Stored energy change.** (SoC now minus SoC at the start of the day) times the battery capacity from the options. The start of the day is the first SoC the integration reads after midnight, and it is saved with today's totals, so a restart keeps it. A fall in SoC makes the change negative.
- **Value of each kWh.** The average cost of the grid energy that went into the battery today, after discount and VAT. That energy is the AC charge counter's rise, priced at the rate in force when it rose. When none went in, it is the cheapest rate in the tariff, after discount and VAT.
- **Stored energy value.** The change times the value of each kWh. It is added to Saving vs Grid Today, and so to Net Saving Today. Both sensors show it in the `stored_energy_value` attribute, with the change in kWh in `stored_energy_change_kwh`. Divide one by the other for the value of each kWh.

Why this rule. The grid energy stored today is the only energy the battery was bought with, so its average cost is what a stored kWh cost. Solar stored has no purchase price, and counting it at 0 would pull the average down, so it is left out. With no grid charge there is nothing to average, and the cheapest rate is the lowest price the battery could have been filled at. A fall in stored energy uses the same value, so a day that charges and a day that discharges the same energy cancel when the charge was bought at the cheapest rate.

Example, a 10 kWh battery on a tariff whose cheapest rate is 0.10 after discount and VAT. The battery starts the day at 40% and 4 kWh are bought overnight at 0.10, which costs 0.40. By 11:00 solar has covered 1 kWh of load that would have cost 0.30 from the grid, and the battery stands at 80%. Without the stored energy the saving is 0.30 minus 0.40, which is -0.10. The battery holds 4 kWh more than at midnight, worth 4 times 0.10, which is 0.40. The saving is -0.10 plus 0.40, which is 0.30. When the battery later supplies the evening load, the stored energy value falls by what that energy cost and the load saving rises by what the grid would have charged for it. The saving ends the day higher than it stood at 11:00.

What to expect:

- The stored energy value follows the SoC. The saving rises as the battery charges and falls as it drains, by the value of the energy that moved.
- Days add up. Each day starts at 0 and carries its own stored energy value. A week that ends at the SoC it began at adds nothing overall when the energy was bought at the cheapest rate. Energy bought at a dearer rate and later valued at the cheapest rate leaves the difference in the week, and that difference is a real cost.
- With no battery capacity set, or while the SoC reading is unavailable, the stored energy value is 0 and the saving is the load minus net import cost. Without the AC charge counter every kWh is valued at the cheapest rate.
- On the day you update, the start of the day SoC is the first reading after the update, so that day's stored energy value starts at 0.

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

Dry run is the **Dry run** switch. A new install starts with it on, and a `.givenergy_test_instance` file in the configuration folder forces it on (see [Configuration](configuration.md#dry-run)). With dry run on, all decisions and sensors update. No charge target, floor, EV mode or immersion command is sent. The Last Skipped Action sensor shows the latest charge target, EV mode or automatic immersion command held back. The cheap rate floor reports through the Cheap Rate Floor sensor. The log carries a `DRY RUN` line for each one. A press of the managed immersion switch is recorded the same way and also leaves the real switch alone.
