# Configuration

Every setup screen and every option, with ranges and defaults taken from the wizards.

- **Setup** is a short wizard. It shows what it found and a checklist of what to set up now, then only the pages you ticked, then a confirm screen. A flat-rate home with nothing else is three screens.
- **Configure** is the same pages as a wizard: "What would you like to change?" You tick the pages to change and only those are shown. The last screen lists every change before and after and says whether it applies now or reloads the integration.
- **Reconfigure** is the inverter connection: which GivTCP entities the integration reads. The tariff is in Configure.

Every field has a label and a one-line help text in the form. [Field meanings](#field-meanings) explains the ones that caused mistakes. A wizard has no Back button, so every page works with its optional fields empty, and nothing is saved until the last screen. Close the dialog at any point to leave without saving.

## Setup

### Screen: Your system

The first screen is always shown. It lists what was found and will be used, then asks for what is missing.

The integration looks for a GivTCP inverter by its `sensor.givtcp_<id>_invertor_serial_number` entity. GivTCP spells "inverter" as "invertor". For each inverter found it looks for these entities, all with the same `givtcp_<id>_` prefix:

| Purpose | Entity suffix | Required |
|---|---|---|
| Solar power | `sensor..._pv_power` | yes |
| Battery SoC | `sensor..._soc` (GivTCP v3) or `sensor..._battery_soc` (v2) | yes |
| Battery power | `sensor..._battery_power` | yes |
| Grid power | `sensor..._grid_power` | yes |
| House load | `sensor..._load_power` | yes |
| Battery capacity | `sensor..._battery_capacity_kwh` | no, supplies the capacity |
| Inverter temperature | `sensor..._invertor_temperature` | no |
| Target SoC | `number..._target_soc` | no, needed to write charge targets |
| Enable charge target | `switch..._enable_charge_target` | no, needed to write charge targets |
| Enable charge schedule | `switch..._enable_charge_schedule` | no, needed to write charge targets |
| Charge start and end, slot 1 | `select..._charge_start_time_slot_1` and `..._charge_end_time_slot_1` | no, needed to write charge targets |
| Day, night and export rate | `sensor..._day_rate`, `..._night_rate` and `..._export_rate` | no, offered as starting values on the setup tariff screen only. See [Screen: Tariff](#screen-tariff) |
| Battery charge rate | `number..._battery_charge_rate` | no, read at the pre-window write to size the charge window. Not stored in the configuration. Without it the window is the cheapest period |

When the five required power sensors are found, the inverter is used with no page of its own. The same screen also finds, uses and announces:

- **An EV charger** (Zappi, Wallbox, OCPP, Ohme or Easee). It needs no screen and no choice. The integration keeps looking for one after setup, so a charger added later is picked up.
- **A solar forecast sensor** from Solcast PV Forecast or Forecast.Solar. When one is found it is used, and the forecast page is not offered. When none is found you can tick the forecast page.
- **Your currency**, from the Home Assistant configuration.

| Field | Shown when | Default | Range |
|---|---|---|---|
| Inverter | more than one inverter is found | the best match | the inverters found |
| Battery capacity (kWh) | GivTCP did not report it | 10 | 1 to 100 |
| Inverter maximum output (kW) | always, GivTCP does not report it | 5.0 | 1 to 20 |
| What would you like to set up now? | always | Electricity tariff ticked | Electricity tariff, Solar forecast (only when none was found), Hot water |

Only the inverter is mandatory. Untick the tariff to set it later. The integration then uses a placeholder rate for costs and the overnight plan until you set the tariff under Configure, and the confirm screen says so.

An inverter is added once: its serial number is the unique ID. Starting a second setup for the same inverter is refused. The EV car efficiency, the battery limits and the carbon sensor have no setup screen, because the defaults apply. Each is one tick away in Configure.

### Screen: Inverter entities (only without a complete inverter)

If no inverter is found, or the one found has sensors missing, the next screen asks for the five power sensors. A sensor the inverter was found with is filled in for you. Leaving one empty shows the error "A required inverter entity is missing or unavailable." If you chose by hand and no serial is known, the entry's unique ID is `manual`. The charge control entities are never asked for in setup. They come from discovery only. Without all of them the integration still calculates a target, but it cannot write it.

### Screen: Tariff

| Field | Default | Range |
|---|---|---|
| Base rate | none, required. Starts at GivTCP's day rate when you set one | 0 to 5 per kWh |
| Export rate | none, required. Starts at GivTCP's export rate when you set one | 0 to 1 per kWh |
| Time-of-day rates besides the base rate | None, one rate all day | 0 to 5 |

**Starting values from GivTCP.** If GivTCP holds a day, night or export rate that you set on its own configuration page, this screen starts from it and says "Taken from GivTCP. Check them against your bill." The day rate starts the base rate, the export rate starts the export rate, and the night rate starts the rate of the first time-of-day row on the next screen. The row's window is never taken from GivTCP. A rate is offered only when GivTCP shows a value above zero that is not one of the values it ships with (0.395 day, 0.155 night, 0.04 export), because a shipped value means the rate was never set. Everything else stays empty. The values are used as they are, per kWh in the currency GivTCP uses, so check them against your bill. Nothing is saved until the confirm screen. The Configure tariff page never reads GivTCP's rates.

The Bill details section is collapsed. Open it when you have your bill to hand. Every field in it has a default that charges nothing, so skipping it is safe.

| Bill field | Default | Range |
|---|---|---|
| Currency | from Home Assistant, else EUR | EUR, GBP, USD, SEK, NOK, DKK, AUD, CAD, NZD, ZAR |
| Base rate name | Day | text, different from every time-of-day rate name |
| First day of your billing period | 1 | 1 to 28 |
| Standing charge per day | 0 | 0 to 5 |
| Fixed levy per billing period | 0 | 0 to 20 |
| VAT rate (%) | 0 | 0 to 30 |
| Supplier discount (%) | 0 | 0 to 20 |

The base rate has to be above 0 unless a time-of-day rate covers the whole day. Take every value from your bill or tariff sheet, whatever your supplier or country. The currency sets the symbol on money sensors and the unit shown beside the rate fields. It does not convert any amounts. See [Tariff](tariff.md) for how rates and bill figures work, and where to find each value.

### Screen: Time-of-day rates (only when the count is above 0)

One row for each rate you chose, each with a name, a rate, a start and an end. A new row is called Night, Peak, Rate 3 and so on, and the first row starts from the usual night window for your country (23:00 to 08:00 for Ireland, 00:30 to 07:30 for Great Britain, 23:00 to 07:00 elsewhere). These are hints to edit, not a statement of your tariff. Every rate has to be typed in. A row cannot start and end at the same time, names have to be different from each other and from the base rate name, and at most five rows are supported.

### Screen: Solar forecast (only when none was found)

The same sensors as the [Solar forecast](#solar-forecast) page of Configure, all optional.

### Screen: Hot water

An immersion switch, a water temperature sensor, the element power, the ready-by times and the alternative water heating, as in the [Hot water](#hot-water) page of Configure. All optional. Switches with "immersion" in their name are listed as a hint, and none is chosen for you.

### Screen: Confirm

A read-only summary lists the inverter, the cheapest rate, the billing period (for example "Your bill runs from the 16th to the 15th."), the base rate and time-of-day rates, the battery and inverter sizes, the EV charger, the forecast sensor, the hot water setup and that dry run is on. A new install starts with dry run on, so nothing is sent to the inverter, the immersion or the EV charger until you turn off the Dry run switch. Submit to create the entry. Nothing is saved before this screen.

| Your home | Screens |
|---|---|
| One rate all day, nothing else | 3 (your system, tariff, confirm) |
| Day and night rates | 4 (plus time-of-day rates) |
| Day and night, with an immersion | 5 (plus hot water) |
| Tariff set up later | 2 (your system, confirm) |

The step count at the top of each screen ("Step 2 of about 4.") is recomputed after every screen.

## Configure

Open **Settings → Devices & Services → GivEnergy Inverter Manager → Configure**. The first screen is a checklist, "What would you like to change?", with nothing ticked. Each line shows what is set now. Tick the pages to go through. Saved options override the values entered at setup.

The pages run in a fixed order whatever order they were ticked in: Tariff, Battery and charging, Solar forecast, Hot water, EV charger. The last screen lists every change before and after in plain words, then says either "Applies now" or "Reloads the integration because you changed ...". That screen is skipped when exactly one page was ticked and its change applies at once, so a one-field edit is two screens. A page that was not ticked is never rewritten, and a value you leave as it was is not written at all. The wizard saves the options as they are at the end, so a control you moved while it was open keeps its new value.

Most changes apply on the next 30-second cycle with no reload: the tariff, battery and charging settings, the forecast and carbon sensors other than the main forecast sensor, element power, ready-by times and the car efficiency. Changing a time-of-day rate also moves the time the charge target is written. The integration reloads, and entities are unavailable for a few seconds, when you change the main forecast sensor, the currency, the immersion switch or the water temperature sensor, or when alternative water heating appears or goes (you turn it on with a cost or a cost sensor set, or off, or clear the last cost). Changing the label, the unit or a cost that is already set does not reload.

A warning, such as ready-by times with no temperature sensor, shows once at the bottom of the page and never stops you saving. Submit the page again to go on.

### Tariff

The first screen has the base rate, the export rate and a select for the number of time-of-day rates, filled in with what is saved (the rates in force today, if a dated change has started). The first line states the cheapest rate in the saved tariff and the billing period, so a wrong rate or bill start day shows before you save. Four tick boxes choose what comes next:

| Tick box | Opens |
|---|---|
| Edit the time-of-day rates | one screen with a row for each rate. It opens by itself when you change the count |
| Edit bill details | currency, base rate name, bill start day, standing charge, levy, VAT and discount |
| Schedule a rate change | the date the rates you entered start, and a switch to cancel the changes already scheduled |
| Confirm the tariff is current | nothing, it records today as the day you checked the tariff |

Raising the count adds blank rows after the saved ones. Lowering it drops the last rows. A count of 0 clears the time-of-day rates and needs no rows screen. Change the rates against your latest bill whenever your supplier changes its prices. See [Tariff](tariff.md). The integration uses only the rates entered here. It does not read the rates GivTCP holds.

**Schedule a rate change.** Sets the date the rates on the Tariff and rows screens start. Leave the date empty to apply them now. Only the base rate and its name, the time-of-day rates and the export rate follow the date. The bill details apply when you save. See [Tariff](tariff.md#change-the-rates-from-a-date). Saving the tariff without a date ends any dated change that has started and keeps the ones that have not.

### Battery and charging

| Field | Key | Default | Range |
|---|---|---|---|
| Battery capacity | `battery_capacity_kwh` | from setup | 1 to 100 kWh |
| Inverter maximum output | `inverter_max_output_kw` | from setup, else 5 | 1 to 20 kW |
| Battery minimum charge | `battery_min_soc_pct` | 10 | 5 to 30 |
| Overnight charge cap | `overnight_charge_target_pct` | 80 | 20 to 100. The calculated target is capped at this |
| Battery cost | `battery_cost_eur` | 0 | 0 to 20000 in steps of 100. 0 turns the wear check off |
| Daily battery throughput budget | `battery_throughput_budget_kwh` | 0 | 0 to 50 in steps of 0.5. 0 turns the budget sensors off |

Update capacity and output when you add battery modules or change the inverter. Dry run, verbose logging, the cheap rate floor and the skip-charge threshold are not here. They are [controls](#controls). The page warns when the Cheap rate floor SoC control is set below the battery minimum charge you enter.

- **Battery cost** sets a wear cost per kWh: cost divided by (2 x capacity x 6000 rated cycles). The immersion rule then refuses to divert when the export rate is lower than that wear cost. It also feeds Net Saving Today and Battery Cycle Cost per kWh.
- A battery cost of 0 means wear is not counted, so Net Saving Today equals Saving vs Grid Today. After 7 days of battery tracking the repair **Battery cost is not set** asks for the value. See [Troubleshooting](troubleshooting.md#battery-cost-is-not-set).
- **Throughput budget** drives Battery Throughput Budget Used and Status. Status is OK below 80% of the budget, High from 80%, and Over budget above 100%.
- A minimum SoC above 30 (possible only from older saved values) raises a repair issue, because on skip nights that value is written as the charge target.

### Solar forecast

| Field | Key | Notes |
|---|---|---|
| Solar forecast sensor | `forecast_entity` | A sensor giving tomorrow's expected energy in kWh or Wh |
| Pessimistic (P10) forecast sensor | `forecast_entity_p10` | Optional. Leave empty with Solcast, which is read automatically. For another service, a sensor whose state is a pessimistic forecast for tomorrow in kWh, blended in when conservatism is above 0. [Where the P10 comes from](#where-the-p10-comes-from) |
| Day after tomorrow forecast sensor | `forecast_entity_d2` | Optional. When it exceeds the battery capacity, tonight's target is lowered to leave room for that day's solar |
| Carbon intensity sensor | `carbon_intensity_entity` | Optional. g CO2/kWh. Feeds the two carbon sensors |

The page says which forecast integration was found and what each chosen sensor reads right now, as a read-only test. It warns when a forecast sensor does not read a number in kWh or Wh. Clear a field to remove the saved entity. Forecast conservatism is a [control](#controls). With no forecast sensor the charge calculation uses a seasonal estimate from your latitude.

#### Forecast accuracy correction

The integration measures how far your forecast service is off and scales it. No setting is needed.

- At midnight it stores the tomorrow forecast it last saw and the solar your inverter then produced that day. The ratio of the two is one data point. The last 14 days are kept. On a new install the first days come from the recorder, see below.
- With **5 usable days**, the forecast is multiplied by the median ratio. The factor is limited to **0.4 to 1.2**. A median of 0.7 means the forecast is multiplied by 0.7. A median below 0.4 is treated as 0.4, so a long run of cloudy days can cut the forecast by more than half. A single day cannot move the median much, so one very poor or very good day does not swing the factor.
- A day is ignored when the inverter clipped at any point that day, or when the forecast or the solar produced was under 0.5 kWh. A clipped day understates what the panels could make, and a near-zero day gives an unstable ratio.
- Until 5 usable days exist, the forecast is used as given. The charge reason then shows no accuracy factor. Once the correction is active, the reason reads, for example, `forecast integration, x0.70 recent accuracy`. When the factor sits on a limit, the reason says so, for example `x0.40 recent accuracy (at the lower limit)`. The charge target rises as the factor falls, because the plan then trusts the forecast less.
- To see where it stands, open the attributes of **Overnight Charge Reason**. `accuracy_status` reads `Waiting for data: 3 of 5 days` until 5 usable days exist, then `Applied: x0.70 from 7 usable days`. `accuracy_measured_factor` is the median ratio so far, `accuracy_applied_factor` is the factor after the 0.4 to 1.2 limit (empty while waiting), and `accuracy_usable_days`, `accuracy_days_needed` and `accuracy_days_stored` give the counts. A day stored but not usable, for example one that clipped, adds to `accuracy_days_stored` only. The correction has no switch. It is either waiting for data or applied.
- The seasonal estimate, used when no forecast sensor is set, is never scaled.
- A run of cloudy or clipped days delays the correction.
- **A new install does not start empty.** The first time it loads with no stored history, the integration reads the Home Assistant recorder in the background. For each of the last 14 days it pairs the last value the tomorrow forecast sensor held before that midnight with the largest value of the GivTCP daily solar counter (`pv_energy_today_kwh`) that day. Home Assistant keeps states for 10 days by default (`purge_keep_days` of the recorder), so expect about 9 days, and the correction applies at once when at least 5 are usable. The recorder cannot say whether the inverter clipped, so seeded days count as not clipped. A day with no recorded forecast or solar value is skipped. Without the recorder, or with no history for the forecast sensor, the integration waits for 5 nights as before. Nothing needs setting up, and a history that is already stored is never replaced.

The correction applies to the main forecast sensor only. The P10 sensor is read as given.

#### The P10 blend

When a P10 forecast is available and `forecast_conservatism` is above 0, the forecast used for the charge target is:

```
forecast = (1 - w) x corrected forecast + w x P10
```

`w` is the conservatism. The corrected forecast is the main forecast after the accuracy factor above. For example, a main forecast of 30 kWh, an accuracy factor of 0.7, a P10 of 15 kWh and a conservatism of 0.35 give `0.65 x 21 + 0.35 x 15 = 18.9` kWh.

When the blend is applied, the charge reason says so in plain words, for example `(cautious forecast, 35% of the way from the typical to the low estimate)`. The percentage is the conservatism.

Both adjustments pull the forecast down. If your forecast runs high and the accuracy factor is active, a lower conservatism avoids charging the battery more than the day needs.

Without a P10 sensor, or while it reads unavailable or unknown, the blend is skipped and the charge reason says `no low estimate available, so the forecast is used as it is`. With conservatism at 0 the blend is off whatever the sensor says. The note only shows when a forecast sensor is set.

#### Where the P10 comes from

The integration looks for a P10 in this order:

1. **The P10 sensor you chose**, if it has a number in kWh as its state.
2. **The `estimate10` attribute of the tomorrow forecast sensor.** The Solcast PV Forecast integration puts the P10 total in this attribute, in kWh for the whole day, next to `estimate` (the P50, the same as the sensor state) and `estimate90`. With Solcast there is nothing to set up. If you have several sites, `estimate10` is already the total.

If neither is found, the blend is skipped.

**Another service.** `forecast_entity_p10` takes a sensor whose **state** is a number of kWh and cannot read an attribute. If your service keeps its pessimistic total in an attribute with another name, make a Template Helper (**Settings > Devices & services > Helpers > Create helper > Template > Template a sensor**) with a state template such as `{{ state_attr('sensor.your_forecast', 'your_attribute') | float }}`, unit `kWh`, device class `Energy`, and pick it as the P10 sensor. Leave the filter without a default, so a missing attribute reads unavailable and the blend is skipped, not read as a P10 of zero.

**Forecast.Solar.** The Home Assistant integration publishes a single estimate and no P10 or other range. Forecast conservatism then does nothing, and the accuracy correction is the way this integration adjusts a forecast that runs high or low.

Do not use Solcast's **Use Forecast Field** select to reach the P10. It changes the field every Solcast sensor reports, including the main forecast, so you would lose the P50.

### Hot water

| Field | Key | Default | Range |
|---|---|---|---|
| Immersion switch | `immersion_switch_entity` | from setup, else none | a `switch` entity |
| Hot water temperature sensor | `immersion_temp_sensor_entity` | from setup, else none | a `sensor` entity |
| Immersion element power | `immersion_wattage_w` | from setup, else 3000 | 500 to 6000 W |
| Hot water ready-by times | `immersion_ready_times` | none | times as `HH:MM`, for example `07:00` and `19:00` |

Both devices are optional and can be added, changed or cleared at any time, without a restart. Changing either one reloads the integration. The Immersion Heater (Managed) switch is created while an immersion switch is set and removed when it is cleared. The Immersion view and tiles of the dashboard follow the same two fields. A heater with no temperature sensor is switched on and off by solar surplus alone, and the target and minimum temperatures have no effect without a sensor. The page lists switches with "immersion" in their name as a hint and shows what the chosen sensors read now.

**Hot water ready-by times** list the times the water has to be at its target temperature. They take effect only while **Immersion Scheduled Heating** is on and a water temperature sensor is set. With no temperature sensor the ready times are ignored, because the integration cannot tell when the target is reached, and the page warns about it. An entry that is not `HH:MM` is refused, and the times are saved in order. The planning is described in [Concepts](concepts.md#scheduled-immersion-heating), which also covers moving from the heater's own timers and from home automations: switch the other timers off, turn **Immersion Scheduled Heating** on and enter the times here. Leave the field empty for the cheapest window alone.

Leave a field empty to clear it. The values saved here override the ones entered at setup. The target, minimum and restart gap temperatures are not in the wizards. Change them with the Immersion number entities, see [Entities](entities.md).

#### Alternative water heating

| Field | Key | Default | Range |
|---|---|---|---|
| I have another way to heat the water | `alt_heat_enabled` | off | on or off |
| Name | `alt_heat_label` | Oil | 1 to 20 characters, for example Oil, Gas or Heat pump |
| The cost is | `alt_heat_cost_unit` | the price of a litre of oil | the price of a litre of oil, or the cost of a kWh of heat |
| Cost | `alt_heat_cost` | none | 0.001 to 5, in your currency |
| Cost sensor | `alt_heat_cost_entity` | none | a `sensor` or `input_number` entity |

Optional, in the **Another way to heat the water** section of the Hot water page. Turn it on when something other than the immersion also heats the hot water cylinder, through a second coil: an oil or gas boiler, a heat pump or solid fuel. The Water Heating Cheapest Source sensor then says whether electricity, solar surplus or the alternative is the cheapest way to heat the water, and when the alternative is worth using. It is advice only. The integration never switches the other system.

**Name.** Your word for the alternative. The advice sentences use it, for example `Gas is cheaper than electricity until 23:00` and `Heat the water with the gas system now`. The page refuses an empty name and one over 20 characters.

**The cost is.** Choose **the price of a litre of oil** and the integration turns it into heat: the price divided by 8.8 kWh of heat per litre (a boiler at 85% efficiency and 10.35 kWh of energy in a litre of kerosene). Those two figures are fixed assumptions in the integration, not options. 85% leans low on purpose, so oil is not suggested on an efficiency the boiler does not reach. Choose **the cost of a kWh of heat** for anything else, and enter what one kWh delivered to the water costs, with the efficiency already in it. For a gas boiler at 90% with gas at 0.09 per kWh that is 0.10. For a heat pump with a coefficient of performance of 3 and electricity at 0.30 per kWh it is 0.10.

**Cost sensor.** Pick a sensor or number that holds the cost in the same unit, for example one fed by your supplier or a helper you update by hand. While it reads a number above zero it is used instead of the cost. When it is unavailable or not a number, the saved cost is used. With no saved cost as well, the advice stops until the cost can be read.

The advice needs the setting on, a cost or a cost sensor, and an immersion switch, because it compares the alternative with the immersion. Missing one of them creates no sensor and writes a warning to the log once at start: `no advice until a cost is set`, or `no advice until an immersion switch is set`. Set them at any time, without a restart. The sensor appears and goes with the setting, so turning it on with a cost set, or clearing the last cost, reloads the integration. Changing the name, the unit or a cost that is already set does not. The wizard warns when the setting is on and one of them is missing, and still saves. The Immersion view of the dashboard shows or hides its Cheapest way to heat the water section to match.

**Upgrading from an oil price.** Up to 0.17 this was Oil water heating, with an oil price per litre and an oil price sensor. On the first start of 0.18 an install with either one set is converted once: the setting is on, the name is Oil, the unit is the price of a litre of oil, the price and the sensor are carried over, and the old options are removed. The advice reads as before.

### EV charger

| Field | Key | Default | Range |
|---|---|---|---|
| Car efficiency (kWh per 100 km) | `car_efficiency_kwh_per_100km` | 15 | 5 to 40 |

The page says which charger was found. The charger is found automatically and there is nothing to choose. Car efficiency converts the energy delivered to the car into kilometres.

## Controls

A control is a setting you try, watch and adjust. It is an entity on the device page, not a form field, and it takes effect on the next 30-second cycle with no reload. Each one shows the value in force, so a change made anywhere shows on the next refresh. The controls are in the **Configuration** section of **Settings → Devices & Services → GivEnergy Inverter Manager**, and on the administrators' **Settings** view of the dashboard.

| Control | Kind | Key | Default | Range | What it does |
|---|---|---|---|---|---|
| Dry run | switch | `dry_run` | off, on for a new install | on or off | On: decisions and sensors update and nothing is sent to the inverter, the immersion or the EV charger. See [Dry run](#dry-run) |
| Verbose logging | switch | `verbose_logging` | off | on or off | Writes per-cycle detail at debug level. Also enable debug logging for the integration, or the lines will not appear. See [Troubleshooting](troubleshooting.md#a-charge-decision-looks-wrong) |
| Immersion divert minimum SoC | number | `surplus_divert_soc_pct` | 80 | 50 to 100 in steps of 5 | Solar surplus only goes to the immersion once the battery is above this percentage. Needs an immersion switch |
| Immersion divert minimum surplus | number | `surplus_divert_min_power_w` | 500 | 100 to 2000 W in steps of 100 | The smallest solar surplus that starts diverting power to the immersion. Needs an immersion switch |
| Cheap rate floor SoC | number | `cheap_rate_floor_soc` | 40 | 0 to 80 in steps of 5 | During the cheapest rate window the battery is topped up if it falls below this percentage. 0 turns the top-up off |
| Skip-charge SoC threshold | number | `skip_charge_soc_threshold_pct` | 75 | 20 to 100 | If the battery is above this percentage and tomorrow's forecast is good, the overnight grid charge is skipped |
| Forecast conservatism | number | `forecast_conservatism` | 0.35 | 0 to 1 in steps of 0.05 | How far to lean on the pessimistic (P10) forecast. 0 uses the plain forecast, 1 the P10 value. Does nothing without a P10 forecast |

- **Upgrading keeps your values.** Each control reads the value the install already had, whether it was saved at setup or on the Configure page, and writes the same saved setting. Nothing is copied or reset on upgrade. A control with nothing saved shows its default, which is the value the integration used.
- **The two divert controls follow the immersion switch.** They exist while an immersion switch is set, like the other immersion entities. Clear the switch and they go. Set one again and they return with the value you had.
- **Not in the form.** The Configure page no longer has these fields. Saving it never changes a control, even when you moved one while the page was open.
- **Not for voice assistants.** The controls are configuration entities, which Home Assistant keeps out of Assist unless you expose them.

### Dry run

A new install starts with dry run on. Turn it off with the **Dry run** switch when the decisions look right. The dashboard shows a banner while it is on.

**Test instance.** Create an empty file named `.givenergy_test_instance` in the Home Assistant configuration folder, next to `configuration.yaml`, and restart Home Assistant. While the file exists, dry run is on whatever the switch or the saved setting says, the **Dry run** switch reads on and cannot be turned off, and the dashboard banner says it is a test instance. Use it on a copy of your configuration that must never write to your inverter, immersion or EV charger. The file is read once at start-up. To go live, delete the file and restart Home Assistant. There is no setting or action that creates or removes it, so a stray click cannot leave test mode.

## Reconfigure

**Settings → Devices & Services → GivEnergy Inverter Manager → ⋮ → Reconfigure** is the inverter connection. It shows the entities in use next to what discovery finds for the same inverter, and offers two choices: use the entities that were found, or choose them by hand. The by-hand screen has the five power sensors (required) and the six optional ones (inverter temperature and the charge controls), filled in with the current mapping. Emptying an optional entity removes it.

Both routes check that the five required entities exist and are not unavailable. The inverter has to be the one the entry was created for: entities that carry another inverter's serial abort the flow and change nothing. Saving reloads the integration once. Setup data other than the entities, the tariff and every saved option are left as they are. To change the tariff, use Configure.

## Things to know

- **Bill start day.** The month totals reset at midnight on the bill start day. A day saved in Configure takes precedence over the one saved at setup, and applies from the next 30-second cycle.
- **Immersion temperatures.** Target, minimum and restart gap are changed with number entities, not in the wizards. Moving one updates the running integration without a reload. See [Entities](entities.md).
- **Controls.** Dry run, verbose logging, the cheap rate floor, the skip-charge threshold, the two immersion divert thresholds and forecast conservatism are entities too. See [Controls](#controls).
- **Forecast provider.** 0.17 and earlier stored a provider choice that nothing read. The wizards no longer ask for it. An install that has it keeps the stored value untouched.

## Field meanings

These are the fields that are easiest to enter wrongly. The same wording is in the forms.

| Field | Meaning |
|---|---|
| First day of your billing period | The day your bill starts. If your bill runs from the 16th to the 15th, enter 16. The Tariff screen and the confirm screen repeat it back as "Your bill runs from the 16th to the 15th." |
| Base rate | The rate per kWh, before VAT, outside the timed rate periods. It is on your tariff sheet. |
| Time-of-day rate | An optional timed rate that overrides the base rate inside its window. The count on the Tariff screen decides how many rows there are. The cheapest active rate wins. A window that ends before it starts runs overnight, for example 23:00 to 08:00. Start and end must be different times. A rate of 0 means free electricity, so do not use it as a placeholder. |
| VAT rate (%) | The percentage added to energy, the standing charge and the levy. Read it from your bill. Enter 0 if your rates already include tax. A wrong value scales every cost figure. |
| Supplier discount (%) | Taken off the energy rate only, before VAT. It does not apply to the standing charge or the levy. 0 means no discount. |
| PSO levy per billing period | A flat amount, before VAT, charged once per billing period. It is named after the Irish public service obligation levy. Use it for any flat per-period charge. The bill sensors spread it evenly across the days. 0 means no levy. |
| Standing charge per day | A fixed charge per day, before VAT. 0 means none. |
| Export / CEG rate | Paid per kWh sent to the grid, such as a feed-in or export guarantee rate. No VAT or discount applies. |
| Cheap rate floor SoC | A control. During the cheapest rate window the battery is topped up if it falls below this. 0 turns it off. |
| Battery cost (EUR) | Used to put a wear cost on each kWh cycled. Enter the amount in your own currency, as the field does not convert it. 0 turns the wear check off. |
| Daily battery throughput budget (kWh) | A cap on kWh charged plus discharged per day. 0 turns the budget sensors off. |
| Forecast sensors | An empty tomorrow sensor means a seasonal estimate is used. An empty pessimistic sensor means conservatism has no effect, and the charge reason says so. An empty carbon sensor means the carbon sensors have no data. |
| Water temperature sensor | Empty means the heater is not started or stopped by temperature. |

Rates and charges are entered before VAT. VAT is added on top, as set in the VAT rate field.
