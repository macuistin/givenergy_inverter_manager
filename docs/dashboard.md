# Dashboard

The integration builds a Lovelace dashboard for you, filled in with your real entity IDs. It is a Home Assistant **dashboard strategy**, so it builds itself each time you open it, from your entity registry, your options and your Lovelace resources. Nothing is written to a file, and there is no step to repeat when something changes.

## Add the dashboard

1. Go to **Settings → Dashboards → Add dashboard**.
2. Under **Community dashboards**, pick **GivEnergy**.
3. Keep the suggested title and icon, or change them, and add the dashboard.

When the integration is first set up, a notification says the same. The integration cannot create the dashboard for you, because Home Assistant gives an integration no supported way to do it. Adding it takes one pick, and the dashboard is yours: rename it, hide it or delete it as you like. The integration never adds it again.

If **GivEnergy** is not listed, reload the browser tab so the frontend loads the integration's strategy file, then try again. If it is still missing, add a new dashboard from scratch, open it, then the three-dot menu, **Edit dashboard**, then the three-dot menu again and **Raw configuration editor**. Use this as the whole configuration:

```yaml
strategy:
  type: custom:givenergy-manager
```

How it works: the integration serves a small JavaScript file at `/givenergy_inverter_manager/givenergy-manager-strategy.js` and adds it to the frontend as a module. The file asks Home Assistant for the dashboard over a websocket command, `givenergy_inverter_manager/dashboard`. The server builds it for the person who is signed in.

- The strategy needs a loaded config entry. Without one the dashboard shows a short message that the integration is not loaded.
- Reload the browser tab after you first set up or upgrade the integration, so the frontend loads the file.

## Moving from the generated file

Versions before 0.18 wrote `givenergy_dashboard.yaml` to the configuration folder. The Refresh Dashboard button and the `get_dashboard_yaml` action wrote it again on request. Both are gone, and so is the file the integration used to create.

1. Add the dashboard as above.
2. Delete the old dashboard, and `givenergy_dashboard.yaml` if it is still in the configuration folder. The integration no longer reads or writes it.
3. Remove any automation or script that calls `givenergy_inverter_manager.get_dashboard_yaml`. The call now fails.

A dashboard from the file keeps showing what it showed, but it no longer follows your devices or your tariff.

## What changes on its own

The dashboard is built when the page opens. A reload of the page is enough after you:

- change the tariff, or schedule a rate change
- enable or rename a sensor
- install or remove a HACS card
- add or remove an EV charger, an immersion switch or an immersion temperature sensor
- promote or demote a Home Assistant user

## What is left out

The dashboard only contains tiles and cards that will show a value.

- A tile is left out when its entity is disabled or not registered. Many sensors are disabled by default. Enable them in **Settings → Devices & services → Entities**, then reload the page.
- A section with no tiles left is left out too, so there is never a heading on its own.
- EV tiles and the EV charger sub-view need an EV charger the integration has discovered. They are hidden until it has, and shown when it does. See [Devices you add or remove later](#devices-you-add-or-remove-later).
- The heater tiles, the heater chart and the divert reason need an immersion switch. The water temperature tile and chart need an immersion temperature sensor. The Scheduled tile, the Ready by section, and the Target, Minimum and Restart gap tiles and sliders need both, because they act on nothing without a sensor to read.
- Inverter temperature tiles need an inverter temperature entity: the one stored at setup, or GivTCP's `sensor.givtcp_<serial>_invertor_temperature` when it exists.
- The forecast tiles need a forecast entity in the options.

## Devices you add or remove later

The EV charger, the immersion switch, the immersion temperature sensor and alternative water heating are optional, and you can add or remove any of them at any time. The dashboard follows, with no step from you.

- **A card for a device is hidden until the device exists.** Each card, tile, chart and section that needs a device carries a Lovelace visibility condition on one entity of that device. The condition hides the card while the entity is missing or unavailable. It shows the card as soon as the entity exists, and hides it again when the entity goes.
- **The cards wait for the device.** Without a device, they point at the entity IDs Home Assistant will give the device's entities, which follow from the entity names. When the device arrives, the cards show. This also keeps a copy of the dashboard working, if you [keep your own copy](#keep-your-own-copy).
- **The power flow card and the cost chart are built once for each combination of devices** and the condition shows the one that matches, as a card cannot hide a single row.
- **The Immersion and EV charger sub-views are always there.** They have no tab, and nothing opens them while their tiles are hidden.

What each device brings:

| Device | How the integration knows | Shown when it is there |
|---|---|---|
| EV charger | Discovery finds a supported charger. This runs again every five minutes until one is found | Car charger on the flow card, the EV charger tile and sub-view, EV energy and cost tiles |
| Immersion switch | The switch is set under Configure, Immersion heater (or at setup) | Heater power, energy, cost and savings, the heater chart, the divert reason, the Auto divert and Managed settings, the immersion node on the flow card |
| Immersion temperature sensor | The sensor is set under Configure, Immersion heater (or at setup) | The Immersion tile with the water temperature, the water temperature chart |
| Switch and sensor together | Both are set | The Scheduled tile and toggle, the Ready by section (while scheduled heating is on), the Target, Minimum and Restart gap tiles and sliders, and the target and minimum lines on the chart |
| Alternative water heating with the switch | Alternative water heating is on under Configure with a cost or a cost sensor set, and an immersion switch is set | The Cheapest way to heat the water section of the Immersion view (the cheapest source, the schedule line and, while Immersion Scheduled Heating is off, the live suggestion), and the advice sentence in the Ready by section |

With only a switch, the Immersion tile shows the heater power and the sub-view has a small chart of the heater's power. With only a sensor, it shows the water temperature and nothing about a heater. With both, the water temperature chart also draws the heater's power, and a tile above it shows the power now.

The integration creates the entities of a device only while the device exists. See [Sensors](sensors.md). So the sensor the dashboard hides on is not a dead entity. It is the entity that arrives with the device. The water temperature sensor mirrors the sensor you set, so the dashboard has a stable entity to chart.

## Keep your own copy

The strategy dashboard always has the layout the integration gives it. To change the layout, open the dashboard's three-dot menu, then **Edit dashboard**, and use **Take control** when Home Assistant offers it. That turns the dashboard into ordinary cards you can edit. The copy holds the dashboard as it was built for the person who took control, at that moment:

- A device that comes or goes still shows or hides its cards, because the visibility conditions are in the copy.
- A tariff change, a renamed entity, a sensor you enable later and a new HACS card do not reach the copy. Its tables read the options they were built from.
- A copy made by an administrator keeps the Settings view and a list of the administrators who may see it. Other users do not see the view, even though it is in the copy.

If Home Assistant does not offer Take control for this dashboard, build your own dashboard from the cards you want. The sections of this page name what each view holds.

## HACS cards

The dashboard needs no custom card. It is built from the cards that come with Home Assistant.

| Card | Needed for | Behaviour without it |
|---|---|---|
| [power-flow-card-plus](https://github.com/flixlix/power-flow-card-plus) | The live flow card in the Power Flow tab | An entities card lists the same values |

The integration reads the Lovelace resource list (**Settings → Dashboards → Resources**) each time the dashboard builds. The card is used only when its URL is in the list. When the list cannot be read, or the card is not in it, the entities card is used.

A card loaded some other way, for example by another integration, does not appear in the resource list. Add it as a resource, or the dashboard will use the entities card.

apexcharts-card is optional. When it is in the resource list, the immersion chart is one chart with the heater shaded behind the water temperature while it is on, as earlier versions drew it. Without it the chart is a built-in history graph. The Bill and Solar charts never use it.

## Layout

The screenshots in this section use the dark theme. The values are from a working install and will differ on yours.

Every view is a Home Assistant **sections** view. Each section is a column of cards that starts with a heading, and the sections sit side by side on a wide screen: one column on a phone, two on a tablet, three on a desktop. Tiles are the main building block. They are all horizontal, two to a row on a phone (six of the twelve grid columns), and use colour the same way everywhere: amber for solar, green for the battery and savings, blue for the grid and money, orange for the immersion, teal for the EV charger and indigo for the night.

The controls use tile features: a slider on the number entities and a toggle on the switches. They sit in the Settings sub-view, which only administrators see. Everywhere else a tile shows a setting's value and does nothing when tapped. A bar shows state of charge. Charts take the full width of their section.

The dashboard has four tabs. Detail sits in seven sub-views that have no tab. A tile, heading or button on a tab opens each sub-view, and the back arrow at the top of the sub-view returns to that tab. A heading that opens a view shows a chevron.

| Tab | Sub-views it opens |
|---|---|
| Power Flow | Immersion and EV charger (the Devices tiles), Battery detail (Battery overnight tile), Settings (the Settings button in the Now heading, administrators only) |
| Today | Cost breakdown (Cost heading), Solar and forecast (Solar heading) |
| Bill | Tariff (the Tariff button in the Bill so far heading) |
| Battery | Battery detail (Battery heading) |

A sub-view and the tile that opens it are left out when the sub-view would be empty. The Immersion and EV charger sub-views are the exception: they are always built so a device added later has somewhere to show, and their tiles are hidden until the device exists.

A rate tile says per kWh in its name (Rate per kWh, Avg import/kWh). The rate sensors report a bare currency amount, and their unit stays that so long-term statistics are not affected.

The links use relative paths, so they work at any dashboard URL.

On a phone the sections stack in one column:

![Power Flow view on a phone, with the cards stacked in one column.](images/dashboard-power-flow-mobile.png)

### Settings and administrators

Everything that changes a setting is in the **Settings** sub-view. A small **Settings** button in the Now heading of the Power Flow tab opens it. Both are for Home Assistant administrators only. Everyone else sees neither, and the rest of the dashboard only shows state.

Home Assistant has no admin option for a dashboard. A view takes a list of users in `visible`, and a card or heading button takes a user condition. The integration uses both, and the server's own check on top.

- **The server decides.** Home Assistant tells the integration whether the person who opened the dashboard is an administrator. A person who is not one is sent a dashboard with no Settings view and no button, so there is nothing for the browser to hide. The request carries no flag the browser could set, and a request with extra fields is refused.
- **A list of administrators stays in the view.** For an administrator, the Settings view and the button also carry the list of administrators, as a visibility condition. A copy made with [Take control](#keep-your-own-copy) still hides Settings from other users.
- **Administrator roles change.** The dashboard asks again each time it opens, so a reload of the page is enough after you promote or demote a user.
- **No administrator found.** The Settings view and its button are left out for everyone. Home Assistant always has at least one administrator, so this only happens when the user list could not be read.

This hides the controls. It is not security. Home Assistant has no permissions for single entities, so a user who is not an administrator can still change the switches and numbers from the entity page, the Entities list, another dashboard, an automation or the API. The server sends a person who is not an administrator no Settings view, but a copy made with Take control holds it and Home Assistant only hides it from them. Use it to keep a shared wall tablet or a family dashboard tidy, not to protect the inverter.

### Power Flow

![Power Flow view with the battery, the Cheap from tile, live solar, grid, home and battery flow, and today's energy with the forecast tiles.](images/dashboard-power-flow.png)

- **Now**: Battery (state of charge with a bar), Rate per kWh, Cost today, Battery overnight and Cheap from (Next Cheap Rate Start). Cheap from is a full-width tile that reads the start and the wait in one line, such as `23:00 (in 8 h 56 min)`, or `Now (ends in 5 h 30 min)` while one is active. The end is where the run of cheaper-than-base periods stops, so a cheaper period inside a longer one does not cut it short. Battery overnight is a full-width tile that says whether the battery lasts until solar starts, and the charge expected at sunrise, such as `Lasts the night · 36% at sunrise`. The other phrases are `Only just lasts the night` and `May run low`. While tonight's planned charge counts, the tile gives both figures (`Lasts the night · 36% at sunrise without a charge, about 89% with tonight's charge`), and a tight or short night says whether the charge covers it (`May run low without a charge · tonight's charge covers it, about 67% at sunrise`, or `May run low, even with tonight's charge · about 13% at sunrise`). A long line is cut to the width of the tile, and the Battery detail view has the whole sentence. It reads the Battery Overnight Confidence sensor, which is disabled by default, so a new install shows four of the five until you enable it. The sensor's state stays Safe, Warning or Critical. Tap the tile to open Battery detail, which says in words why. Tap the Battery tile to open the Battery tab.
For administrators the heading also holds a **Settings** button.
- **Dry run is on**: a banner below Now with the last skipped action and tonight's charge plan, so you can see what the integration would do next. The plan is the Tonight's charge plan sensor, which the Battery tab also shows. The banner appears only while Dry Run Mode Active is true. It says how to go live: an administrator turns off the Dry run switch in Settings. On a test instance, where a `.givenergy_test_instance` file forces dry run on, it says so and names the file to delete instead.
- **Something else is setting your charge target**: a banner below the dry run banner, shown only while the Charge Target Conflict sensor says `suspected`. It means the charge target changed at least twice in three days without a write from this integration and without a Home Assistant user making the change. Common causes are GivTCP's SmartTarget, Predbat and the GivEnergy app. The banner names no cause, because the integration cannot tell them apart. It goes after three days without a change. See [Something else is setting the charge target](troubleshooting.md#something-else-is-setting-the-charge-target).
- **Finish setting up**: a checklist below the banners, drawn from the Setup Progress sensor. It lists the required steps as done or to do: inverter found, tariff set, cheap rate window set, solar forecast added and dry run turned off. Below them, in smaller text, it lists the optional things you have not set up yet, such as hot water or an EV charger. It shows while the sensor says `incomplete`, and goes when the required steps are done. It has no dismiss button. Two steps can hold it open for a good reason: a flat rate tariff has no timed rate, and an install without a solar forecast has nothing to add. On a test instance, turning dry run off is not a step.
- **Live power flow**: a power-flow-card-plus card with solar, battery, grid, home and, when they exist, two individual loads: the EV charger and the immersion. Solar shows a clipping marker. The battery node reads Battery Power for the flow and Battery State of Charge for the percentage. Battery Power is positive while charging and the card expects the opposite, so the node sets `invert_state: true`. The grid node shows the Live Grid Cost Rate with the unit of your currency symbol per hour, for example `0.0412 €/h`. The rate is what the current grid flow costs each hour, negative while you earn from export.
- **Energy today**: Generated, Forecast and % of forecast (with a forecast sensor set), Used (House Load Today), Imported, Exported and Self-sufficient. Forecast is the provider's own figure for today and % of forecast is the solar generated so far against it. Self-sufficient is the share of what the house used that did not come from the grid. Tap the heading to open the Today tab, which shows where the energy came from.
- **Devices**: an Immersion tile (the water temperature, or the heater power when there is no sensor) and an EV charger tile (the charger state). Each opens its sub-view. The heading and each tile show only while their device exists.

For the EV load, the dashboard uses the first of these entities that exists, else the integration's own EV Charging Power: `sensor.myenergi_zappi_power_ct_internal_load`, `..._2`, `sensor.myenergi_zappi2_power_ct_internal_load`, `sensor.wallbox_charging_power`, `sensor.ohme_current_power`.

### Immersion (sub-view)

![Immersion view with the water temperature and heater power graphs, the reason for the divert decision, the ready-by plan, the cheapest way to heat the water, and the settings in force.](images/dashboard-immersion.png)

Each section shows only while the device it needs exists.

- **Water temperature** (needs the sensor): a 12-hour chart of water temperature. With a switch as well, it also draws the target and minimum and when the heater was on, and a **Heater power** tile above it shows the power now. With apexcharts-card installed it is one chart with the on times shaded. Without it, it is a history graph with the heater's power as a second chart under the temperatures. The heater's power is a fixed number, so it reads as 0 while the heater is off and your heater's wattage while it is on.
- **Heater on or off** (needs the switch and no sensor): the Heater power tile and a small 12-hour history graph of the heater's power, for an install with a switch but no temperature sensor. It hides itself when a sensor is set, as the water temperature section then carries the heater.
- **Why** (needs the switch): the divert reason in words.
- **Ready by** (needs the switch and the sensor, and shows only while Immersion Scheduled Heating is on): the next hot water ready time, whether the water is expected to be at the target by then, and the heating rate the plan uses. It reads the `ready_by`, `expected_ready` and `heating_rate_c_per_h` attributes of the Immersion Water Temperature sensor, so there is no helper sensor. Below it a line from the `planned_heating` attribute says what the immersion plans, for example `Heating planned for the 19:00 ready time: 17:10 to 18:30 at the Day rate.` or `No heating planned for the 19:00 ready time (water 54.4°C, ready). Next possible heating: 02:00 to 04:00 slot, only if the water is below 51°C by then.` With no water reading yet it says the plan shows once the temperature is read. See [Scheduled immersion heating](concepts.md#scheduled-immersion-heating). With alternative water heating set it adds the advice sentence below it, which says when to start the alternative for that ready time, for example `For the 19:00 ready time: turn the oil water heating on at 16:30 (about 90 minutes). The immersion will only top up.` It follows the advice, so it is hidden while that sensor is unavailable. The Cheapest way to heat the water section leaves the same sentence out while this section shows, so the page has one copy. Home Assistant cannot hide a card on a missing attribute, so with the switch on and no ready time set, the card says where to add one.
- **Cheapest way to heat the water** (needs alternative water heating with a cost, and the switch): a tile with the cheapest source now (electricity, solar or alternative) and the suggestion in a sentence, for example `Oil is cheaper than electricity until 23:00 (saves about 0.16 per kWh of heat). Heat the water with the oil system now.` With a water temperature sensor the sentence also says when to start the alternative for the next ready time, when to run it to keep the water warm, that the water is already at the target, or that it is expected to be ready with no heating needed. While Immersion Scheduled Heating is on, the Ready by section above prints this sentence, so this section leaves it out and shows the tile and the schedule line. It is advice only: the integration does not switch the other system. The section hides itself while the sensor has no reading, for example when a cost sensor is unavailable and no cost is saved. See [Alternative water heating advice](concepts.md#alternative-water-heating-advice). Below the suggestion is a separate line for the recurring schedule, for example `Over the last 14 days the immersion used about 14 kWh of grid electricity that cost more than oil, mostly around 13:00 and 19:00. Running the oil from 12:30 to 13:00 and 18:00 to 19:00 would have saved about 6.00 over those days.` Until the integration has seen 7 days it says it is still learning, and with 7 days or more and nothing worth suggesting it says so. The schedule is advice too, and the integration does not switch the other system. The lines name the alternative by the name you set, Oil by default.
- **Today** (needs the switch): energy, cost and what solar saved.
- **Settings in force** (needs the switch): Auto divert and Managed, to read. With a sensor as well it adds Scheduled (the Immersion Scheduled Heating switch), Target temp, Minimum temp and Restart gap. Change them in Settings. Under the tiles, two short lines say what Managed and Restart gap mean: Managed forces a heating run when turned on and holds the heater off for 10 minutes when turned off, and Restart gap is how far the water must fall below the target before a new heating run starts. The Managed line shows with the switch, and the Restart gap line needs the sensor as well.

### EV charger (sub-view)

- **Charging now**: charger state, charge power, session energy and charging source.
- **Why**: whether the EV is draining the battery, the solar surplus available and the mode decision in words.
- **Today**: the energy the charger delivered and what it cost.
- **Charge power, last 24 hours**: a line graph of the charger's power. It uses the same power entity as the Charge power tile. Power does not reset at midnight, so a history graph draws it without a sawtooth.

The sections show only while a charger exists.

### Today

![Today view with energy generated, used, imported and exported, the card that says where today's energy came from, cost tiles, and self-sufficiency gauges.](images/dashboard-today.png)
- **Energy**: Generated, Used, Imported, Exported, EV and Immersion.
- **Where today's energy came from**: three lines in plain words, then one line for each of the EV and the immersion that exists.
  - House used: what the house used, split into solar, battery and grid. Solar and battery show as one figure when the Battery Discharged Today sensor is disabled. The integration enables it on start, unless you disabled it yourself.
  - Grid import: what came in from the grid, split into the part the house used and the part that went into the battery. The split needs the inverter's AC charge counter. Without it the card says the split is not known and counts all of the import as used by the house.
  - Self-sufficiency: the share of what the house used that did not come from the grid.
  - EV and immersion: how much of the house use went to each. They are part of the house use, not added to it. A line shows only while its device exists.

  The card reads four attributes of the Self Sufficiency sensor: `house_load_kwh`, `from_grid_kwh`, `grid_to_battery_kwh` and `basis`. Where one is missing it uses the House Load Today and Grid Import Today totals. The whole group is left out when Self Sufficiency, House Load Today or Grid Import Today is missing.
- **Cost**: Import cost, Export earnings, Rate per kWh and Rate period. The heading opens Cost breakdown.
- **Solar**: Home use from solar and Solar kept at home, each with a bar. Home use from solar is the Solar Share sensor: the share of what the house used that solar supplied. Solar kept at home is the Self Consumption sensor: the share of today's solar that was not exported. The heading opens Solar and forecast. Self-sufficiency has no bar here, because the card above it states the figure with what it means. The Power Flow tab keeps its Self-sufficient tile, as the glance. The bar comes back on this tab when that card cannot be built, which happens when Self Sufficiency, House Load Today or Grid Import Today is missing, so the figure is never lost.

### Cost breakdown (sub-view)

![Cost breakdown view with grid import, house, EV and immersion costs and a 14 day bar chart.](images/dashboard-cost-breakdown.png)

A tile for every cost line today (grid import, export earnings, rest of house, EV charging, immersion and Immersion solar saving, which is what solar saved on the immersion) and a bar graph, **Cost per day, last 14 days**. The graph names its series as the tiles do. It plots Rest of house, EV charging and Immersion (the last two only while that device exists) and Export earnings. It does not plot Grid import, because that is the whole of the import cost, the sum of the three, and drawing it beside them would count the same cost twice. Read the total from the Grid import tile.

### Solar and forecast (sub-view)

With a forecast sensor set: Generated today, Forecast, % of forecast, Plan forecast and Yesterday's accuracy (yesterday's solar as a share of the forecast for that day). Next to them are two charts: a bar graph of solar generation per hour over 2 days, and **Last 7 days**, a bar graph of what was generated on each of the last 7 days.

The forecast sensor keeps no long-term statistics, so no chart plots the forecast. The Forecast and Yesterday's accuracy tiles carry it. The Last 7 days chart needs a forecast sensor, so it is left out without one.

Forecast is what your forecast service predicted for today, as it stood just before midnight. % of forecast compares solar generated so far with that figure. Plan forecast is the figure the overnight charge calculation used: blended toward the pessimistic estimate and scaled by the accuracy correction, so it can differ from the provider's figure. The tile's sensor also says in its `solar_profile_source` attribute whether the plan spread that figure with the forecast's own shape (`forecast`) or the standard curve (`standard curve`). Judge the day against Forecast. A line under the tiles says the same in one sentence, and shows while the Plan forecast tile does. Forecast and % of forecast read empty on a new install until the first midnight, because the provider forecast is remembered then.

The graphs on the Bill tab and on the Cost breakdown and Solar and forecast sub-views are statistics graphs, not history graphs. The daily sensors fall to zero at midnight, so a history graph of them draws a sawtooth. The graphs plot the change in each period instead, from the long-term statistics. They stay empty until Home Assistant has compiled statistics for the sensors, which takes up to an hour.

### Bill

![Bill view with accrued and projected bill, import cost, export credit and days left in the period.](images/dashboard-bill.png)

Figures for the current bill period, so you can hold them against your supplier bill.

- **Bill so far**: Accrued bill, Projected bill, Import cost and Export credit. A **Tariff** button in the heading opens the Tariff sub-view.
- **This bill period**: Days elapsed, Days left, Avg import/kWh and Cheap share (the cheap rate share of import).
- **Cost per day, last 31 days**: a bar graph of the import cost and the export credit of each day, so you can see which days made the bill. It reads long-term statistics, so it stays empty until Home Assistant has compiled them (up to an hour), and it reaches back 31 days because a bill period is a calendar month at most. The graph cannot mark where your bill period starts, because that moves each month.

Days Elapsed in Bill Period, Average Import Rate This Month and Cheap rate import fraction this month are disabled by default. Enable them to see those tiles.

Accrued Bill This Period is worked out line by line from the month totals: energy less the supplier saving, standing charge, PSO levy and VAT, minus the export credit. Projected Bill This Period scales it to the whole period. See [Tariff](tariff.md#bill-sensors). Import cost this month is the import energy for the period after discount and VAT. It leaves out the standing charge, the PSO levy and the export credit.

### Tariff (sub-view)

A table of the base rate and each timed rate period with its window, the rate, and the rate billed per kWh after the supplier discount and VAT. It also lists the export rate, standing charge, PSO levy and bill start day.

The table is read from your options each time the dashboard opens, so a reload of the page shows a change. It uses the same defaults as the integration for any field you have not set.

Under it, **Scheduled rate changes** lists each dated change that has not started: the date it starts, the new base rate, the timed rates with their windows, and the export rate. The line below the table gives the date the tariff was last reviewed. The list is left out when no change is scheduled, and so is the heading. A change that has started is not listed, because the table above already shows its rates. A change replaces the base rate, the timed rates and the export rate on its date, and the standing charge, levy, VAT, discount and bill start day stay as they are in the table above.

Like the table, the list is read from your options each time the dashboard opens, so a change that has started drops out of the list on the next page load. To schedule a change, see [Change the rates from a date](tariff.md#change-the-rates-from-a-date).

### Battery

![Battery view with the state of charge graph, tonight's charge plan with the sunrise figures without and with the planned charge, and the charge settings in force.](images/dashboard-battery.png)

- **Battery**: state of charge with a bar, battery power with a 24-hour trend, and a 24-hour history of state of charge. The heading opens Battery detail.
- **Tonight's charge plan**: the plan in one sentence first, then Target if charging (the target the plan would set if tonight charges, which is not a promise that it does, on a full-width tile), Sunrise (no charge) and Sunrise (with charge) on full-width tiles (the estimated state of charge at sunrise without and with tonight's planned charge), Est. cost and Rate floor (the cheap rate floor). The sentence is the Tonight's charge plan sensor, and says outright whether tonight charges (`Target 78% · Add 34% · Cost €0.51`) or is skipped (`Skip charge · Plan forecast 8.2 kWh · SoC 64%`). The sensor is enabled by default. If you disabled it, the tiles show alone.
- **Charge settings in force**: Override on, the Target override value, Skip tonight and Dry run, to read. Target override shows only while Override on is on, because the value is not used otherwise. Dry run reads On or Off. Change all four in Settings.

State of charge and power are not drawn on one graph, because a percentage and watts share no scale.

### Battery detail (sub-view)

- **Battery overnight**: the outlook in bold, with no repeat of the heading, then why. Where the Battery Overnight Confidence sensor has an `explanation` attribute, that is shown, with the figure with tonight's planned charge and whether it covers the night while a charge counts. Otherwise a Warning is explained from the estimated state of charge at sunrise without a charge ("about 14% at sunrise without a charge, close to your minimum charge") and, when a charge adds something, the figure with the planned charge. Safe and Critical show the Battery Overnight Outlook text, which carries any kWh shortfall. Without the confidence sensor, which is disabled by default, only the status text is shown. Under the outlook come the same two Sunrise tiles, so the figure the outlook judges (no charge) sits next to where the night ends with the planned charge. Under that, the reason for tonight's charge target. Both are sentences, and a tile cuts them off, so they sit in Markdown cards. The cards print the `full_text` attribute of the sensor when it has one and otherwise its state, because the state of a long reason is cut to 255 characters. The divert reason and the EV mode decision cards do the same.
- **Battery health**: total cycles, life remaining and days since full charge.
- **Inverter**: the inverter temperature and status. The section needs an inverter temperature entity.

### Settings (sub-view, administrators only)

![Settings view with the Dry run switch, the overnight charging controls, the Tuning sliders and the immersion heater controls.](images/dashboard-settings.png)

- **Dry run**: the Dry run switch. Turn it off to go live. It cannot be turned off on a test instance.
- **Overnight charging**: a Target override slider, and the Override on and Skip tonight switches. They carry the names the Battery tab gives the same settings.
- **Tuning**: a short note on what each control does, then sliders for the cheap rate floor, the skip-charge threshold and forecast caution, the Re-plan charge switch and the Verbose logging switch.
- **Immersion heater**: the Auto divert and Managed switches, then sliders for the minimum battery charge and the minimum surplus that start diverting. With a temperature sensor as well, the Scheduled switch (Immersion Scheduled Heating) and sliders for the target temperature, the minimum temperature and the restart gap. The same two lines as on the Immersion view explain Managed and Restart gap under the controls, each only while its controls exist. The section ends with **Heater decision now**, the divert reason in words, so the controls come before the sentence and the sentence has a label.

The view is left out when there is no administrator to show it to, and the immersion section is hidden while there is no immersion switch. The dry run banner is not here. It sits on the Power Flow tab, below Now, and appears only while Dry Run Mode Active is true.

## HTML report cards

Three sensors carry a styled HTML report in their `html` attribute: Today's energy summary, Tonight's charge plan and This week's energy summary. They use inline styles, so the built-in Markdown card renders them.

Today's energy summary and This week's energy summary are disabled by default. Enable them in the entity list first. Tonight's charge plan is enabled by default, because the Battery view reads its sentence. The `html` attribute is kept out of the recorder.

```yaml
type: markdown
content: "{{ state_attr('sensor.givenergy_inverter_manager_todays_energy_summary', 'html') }}"
```

Replace the entity ID with the real one from **Settings → Entities**.

The Solar row of Today's energy summary carries the same forecast as the dashboard: the provider's own forecast for today and the share of it generated so far, matching Forecast and % of forecast. The row shows no forecast until the provider's figure has been remembered at the first midnight. Tonight's charge plan shows the plan's forecast on its own row, labelled Plan forecast, because the charge calculation blends it toward the pessimistic estimate. The accuracy rows of This week's energy summary measure against the provider's forecast too.
