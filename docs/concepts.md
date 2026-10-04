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
2. Raise or clear the repair issue for a minimum SoC above 30%.
3. Check GivTCP. If both the solar power sensor and the battery SoC sensor are `unavailable`, `unknown` or missing, the cycle fails and every entity of the integration becomes unavailable until GivTCP returns. See [Troubleshooting](troubleshooting.md#all-entities-are-unavailable).
4. Look for an EV charger. While none is found, discovery repeats about every 5 minutes (every tenth cycle).
5. Read the sensors: solar power, battery SoC, battery power, grid power, house load, the optional immersion temperature, forecasts, carbon intensity and inverter temperature, the EV charger, and the GivTCP daily energy counters.
6. Run the engine. It finds the current rate, adds the time since the last cycle to the today, week, month and year totals, applies the GivTCP daily counters to today's totals, and works out the charge target, immersion decision, bill figures, night survival and EV signals.
7. Record the day's first forecast value, for the forecast accuracy sensors.
8. Apply the cheap rate floor, if it is due.
9. Apply the EV mode change, if one was requested.

The managed immersion switch applies the immersion decision each time the coordinator publishes new data.

Three things happen on a clock instead of in the cycle.

| When | What |
|---|---|
| 00:00:00 local time | Daily reset. Today moves to yesterday. Monday also resets the week. The bill start day also resets the month and saves a snapshot. 1 January also resets the year. |
| One minute before the cheapest timed rate period starts, once a day | Write the charge target and window to GivTCP |
| Every tenth cycle (about 5 minutes) and at midnight | Save accumulated energy and battery statistics |

Energy is added using the real time between cycles. The first cycle after a start or a midnight reset adds nothing, and a gap longer than one hour is skipped, so a restart does not create a spike.

Accumulated energy is not saved when Home Assistant stops. A restart, or a reload after saving options, loses up to about 5 minutes of energy. The year totals, Missed Solar Today and Inverter Derating Today are not saved at all and restart from zero.

### Write protection

GivTCP writes use registers with a limited lifetime. Each write helper:

- reads the entity first and skips the write when it already holds the value;
- skips the write when the same entity was written in the last 300 seconds;
- reads the entity back after 2 seconds and retries up to 3 times;
- counts each write in the GivTCP Register Write Count sensor, and logs a warning at 500,000 writes.

## GivTCP sign conventions

The integration was written against GivTCP v3 on a GIV-HY-5.0.

| GivTCP entity | GivTCP sign | In this integration |
|---|---|---|
| Grid power | Positive is export, negative is import | The integration negates it. **Grid Power** is positive when importing and negative when exporting |
| Battery power | Positive is charging, negative is discharging (confirmed on a GIV-HY-5.0) | Unchanged. **Battery Power** is positive when charging |
| Solar power | Always positive | Unchanged. Readings under 10 W count as zero in the solar energy total |
| Load power | Inverter-side load | Unchanged. **House Load** |

To check your own setup, export to the grid on a sunny day and compare **Developer Tools → States** for the GivTCP grid power entity and **Grid Power**. They must have opposite signs. If they do not, grid import and export are swapped in every cost sensor. Battery power is not negated, so a model that reports charging as negative would be accumulated the wrong way round.

GivTCP measures at the inverter. A load wired directly to the consumer unit, bypassing the inverter, appears as grid import even while the sun is shining.

### GivTCP daily counters

When these entities exist, they replace the integration's own sum for today's physical energy:

`sensor.givtcp_<serial>_pv_energy_today_kwh`, `_import_energy_today_kwh`, `_export_energy_today_kwh`, `_charge_energy_today_kwh`, `_discharge_energy_today_kwh` and `_load_energy_today_kwh`.

A missing counter falls back to the integration's own sum, one counter at a time. Week, month and year totals always use the integration's own sum. Costs and earnings are always worked out by the integration, because GivTCP does not know your tariff.

## How decisions are made

### Overnight charge target

The calculation runs every cycle. The result is written to GivTCP once a day. The rules, in order:

1. **Winter, December to February.** The target is 100%. The charge is skipped if SoC is already 95% or more. The forecast is not used.
2. **Shoulder months, March, April, October and November.** The minimum SoC is raised to at least 70% for the calculation.
3. **Forecast.** The tomorrow sensor is used when set. Otherwise the integration estimates from your latitude: inverter maximum output in kW times 4 hours times a factor for the month, with 1.0 for the sunniest month. If a Solcast P10 sensor is set and the conservatism is above 0, the forecast becomes `(1 - w) x forecast + w x P10`, where `w` is the conservatism.
4. **Skip rule.** The charge is skipped, with a target of minimum SoC plus 10, when SoC is at or above the skip threshold, no EV is plugged in, and the forecast is more than 0.8 times the smaller of 60% of the forecast and the usable battery capacity.
5. **Simulation.** Otherwise the integration simulates one day in 48 half-hour slots. Solar follows a bell curve centred on 13:00 between 06:30 and 19:30. Load is the average daily load spread evenly. It finds the lowest starting SoC that keeps the battery above the minimum all day.
6. **Adjustments.** Add 10 points if an EV is plugged in. Never go below minimum SoC plus 5, or above 100.
7. **Cap.** The target is capped at **Default overnight charge target**, which is 80% unless you change it. The cap also applies to the winter target of 100%.
8. **Overrides.** Manual overrides replace the result and the cap does not apply to them. See [Entities](entities.md).

The average daily load is today's house energy so far, scaled up to 24 hours. It is at least 5 kWh, and 15 kWh in the first 30 minutes after midnight.

**Writing the target.** One minute before the cheapest timed period starts, the integration sets, in order: enable charge schedule on, charge start time, charge end time, target SoC, then enable charge target (on for targets below 100, off for 100). The window is the cheapest timed period. On a skip night it writes the minimum SoC as the target, so the battery can discharge instead of being held at an old target. Nothing is written when the target SoC entity was not detected, or when the tariff has no timed period.

**Cheap rate floor.** During a timed period cheaper than the base rate, the integration checks SoC against the floor (default 40%, 0 turns it off). In the cheapest period the full floor applies. In a cheaper-but-not-cheapest period it only acts when SoC is below the minimum SoC plus 5. When it acts, it writes the floor as the target SoC and turns enable charge target on, once per day.

### Immersion divert

The rule runs in this order. The first match wins.

1. Water below **Immersion Minimum Temperature**: heat, whatever the surplus.
2. Water at or above **Immersion Target Temperature**: do not heat.
3. Battery SoC below the divert threshold (default 80%): do not heat.
4. Surplus below the minimum (default 500 W) and no clipping: do not heat. Surplus is smoothed solar power minus house load minus battery charging power. Clipping means solar at 95% or more of the inverter maximum.
5. Battery cycle cost above the export rate: do not heat. Active only when a battery cost is set.
6. Currently off and water within the **Immersion Restart Gap** of the target: do not heat yet.
7. Otherwise heat.

Rules 1, 2 and 6 need a water temperature sensor. Without one, the immersion runs whenever there is surplus and the battery is above the threshold.

Solar power is smoothed with an average of the last smoothed value and the new reading, which stops the divert chasing a passing cloud.

The managed switch writes to your real immersion switch. After each automatic on or off it waits 10 minutes before the next automatic change. It turns off at once when the water is at or above the target.

When **Auto Immersion Divert** is off, the rule above is bypassed. The decision becomes off with the reason `Manual override`, and the managed switch asks for the real switch to be off. The minimum temperature rule does not run either.

Turning the managed switch on yourself starts a run to target. So does turning your real switch on from outside, once the integration has switched it at least once. The heater stays on until the water reaches the target. With no temperature sensor it stays on until you turn it off. Turning it off, here or outside, holds off automatic control for 10 minutes.

### EV charger

The integration finds Zappi (myenergi), Wallbox, OCPP, Ohme and Easee chargers by their entity names. It uses the first one found.

It does three things with the charger:

- **Signals.** EV Solar Surplus reads `Available` at 1400 W of net solar surplus or more. EV Charging Source reports Solar, Grid, Battery or Mixed. EV Draining Battery is `yes` when the charger is charging and the battery discharges over 200 W.
- **Zappi mode.** For a Zappi with a charge mode entity, with a car plugged in and net surplus of at least 1380 W, the integration selects **Eco+** unless the Zappi is already in it. It never selects Stopped. In dry run it records the action and sends nothing.
- **Cost and distance.** EV energy, cost and kilometres use the car efficiency from the options.

Other brands get the signals only.

### Costs

Every cycle the grid import is priced at the current rate, after supplier discount and VAT, and split between the EV, the immersion and the rest of the house by their share of the house load. Export earns the export rate. See [Tariff](tariff.md#bill-line-items).

### Dry run

With dry run on, all decisions and sensors update. No charge target, floor, EV mode or immersion command is sent. The Last Skipped Action sensor shows the latest charge target, EV mode or automatic immersion command held back. The cheap rate floor reports through the Cheap Rate Floor sensor. The log carries a `DRY RUN` line for each one. Manual presses of the managed immersion switch also skip the real switch.
