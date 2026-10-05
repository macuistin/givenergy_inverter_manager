# Dashboard

The integration writes a Lovelace dashboard, filled in with your real entity IDs, to `givenergy_dashboard.yaml` in the Home Assistant config folder.

## Generate the file

Either:

- Press **Refresh Dashboard** on the device page (**Settings → Devices & Services → GivEnergy Inverter Manager**), or
- Run the `givenergy_inverter_manager.get_dashboard_yaml` action in **Developer Tools → Actions**.

A notification, **GivEnergy Dashboard Ready**, confirms the write. The first time the integration is set up it also creates a placeholder file containing `views: []`, so a YAML-mode dashboard can point at the file straight away.

Generate the file again after you change the options, rename entities, or add an immersion temperature sensor. The file is overwritten.

## Example

[`dashboard-example.yaml`](dashboard-example.yaml) is a complete dashboard you can copy and edit. It shows the output for a setup with an immersion heater, an EV charger, an inverter temperature sensor and a solar forecast configured, and with every sensor enabled. The entity IDs are the ones Home Assistant gives a fresh install. If you renamed entities, generate your own file instead.

A test regenerates the example and fails when it no longer matches the generator, so it always shows the current layout.

## What is left out

The file only contains rows and cards that will show a value.

- A row is left out when its entity is disabled or not registered. Many sensors are disabled by default. The file header and the **GivEnergy Dashboard Ready** notification list the disabled sensors the dashboard would have used. Enable them in **Settings → Devices & services → Entities**, then generate the file again.
- EV rows and the EV Charger card need an EV charger. The dashboard counts a charger the integration has discovered, or one of the external power sensors listed under Power Flow.
- Immersion rows, the Immersion Heater card and the immersion charts need an immersion switch or temperature sensor in the options. The charts need the temperature sensor.
- Inverter temperature rows need the inverter temperature entity in the options.
- The Solar vs Forecast card needs a forecast entity in the options.

## Add the dashboard

### UI mode

1. Open `givenergy_dashboard.yaml` in your config folder, for example with the File editor add-on.
2. Copy the whole file.
3. Go to **Settings → Dashboards → Add Dashboard → Blank**.
4. Open the new dashboard, then the three-dot menu, **Edit dashboard**, then the three-dot menu again and **Raw configuration editor**.
5. Replace the content with the copied YAML and save.

After regenerating, repeat steps 1 to 5.

### YAML mode

Add this once to `configuration.yaml`, then restart Home Assistant:

```yaml
lovelace:
  dashboards:
    givenergy:
      mode: yaml
      filename: givenergy_dashboard.yaml
      title: GivEnergy Inverter Manager
      icon: mdi:solar-power-variant
      show_in_sidebar: true
```

After regenerating, reload the dashboard or restart Home Assistant.

## Dashboard strategy (optional)

Instead of a generated file, a dashboard can build itself each time it opens. Create a dashboard, open the Raw configuration editor and use this as the whole configuration:

```yaml
strategy:
  type: custom:givenergy-manager
```

The integration serves a small JavaScript file at `/givenergy_inverter_manager/givenergy-manager-strategy.js` and adds it to the frontend as a module. The file asks Home Assistant for the dashboard over a websocket command, `givenergy_inverter_manager/dashboard`, which returns the same dashboard as the action, built from the current entity registry, options and Lovelace resources. Changing the tariff, enabling a sensor or installing a HACS card shows up on the next page load, with no file to regenerate.

- Reload the browser tab after you first set up or upgrade the integration, so the frontend loads the file.
- The strategy needs a loaded config entry. Without one the dashboard shows a short message instead.
- The skipped sensor list and the header notes in the file are not part of the strategy output.
- The generated file and the action work the same with or without the strategy.

## HACS cards

| Card | Needed for | Behaviour without it |
|---|---|---|
| [power-flow-card-plus](https://github.com/flixlix/power-flow-card-plus) | The live flow card in the Power Flow tab | An entities card lists the same values |
| [apexcharts-card](https://github.com/RomRider/apexcharts-card) | The immersion charts in the Immersion sub-view | A history graph of the temperatures and a statistics graph of immersion energy replace them |

When you generate the file, the integration reads the Lovelace resource list (**Settings → Dashboards → Resources**). A card whose URL is not in the list is treated as not installed, and the built-in cards are used. The file header names the cards it replaced. Install the card from HACS and generate the file again to get the custom card.

A card loaded some other way, for example by another integration, does not appear in the resource list. Add it as a resource, or the generator will replace it. If the list cannot be read, the generator assumes both cards are installed.

Everything else uses built-in Home Assistant cards.

## Tabs and sub-views

The dashboard has five tabs. Detail sits in six sub-views that have no tab. A card on a tab opens each sub-view, and the back arrow at the top of the sub-view returns to that tab. Cards that open a sub-view have a tap action; they are tiles, buttons or the rows of the Energy Today strip.

| Tab | Sub-views it opens |
|---|---|
| Power Flow | Immersion, EV charger, Today (tap the Energy Today strip) |
| Today | Cost breakdown, Solar and forecast |
| Bill | Tariff |
| Battery | Battery detail |
| Controls | EV charger |

A sub-view and the card that opens it are left out when the sub-view would be empty, for example Immersion without an immersion heater.

The links use relative paths, so they work at any dashboard URL.

### Power Flow

- A **Now** strip at the top with six core cards: Battery state of charge, Night Survival Confidence, Current Rate, Cheap from (Next Cheap Rate Start), Cheap in (Hours to Cheap Rate) and Import Cost Today. Night Survival Confidence and the two cheap rate sensors are disabled by default, so a new install shows three of the six until you enable them.
- A power-flow-card-plus card with solar, battery, grid, home and two individual loads: the EV charger and the immersion. Solar shows a clipping marker. The battery card reads Battery Power for the flow and Battery State of Charge for the percentage. The grid node shows the Live Grid Cost Rate.
- An **Energy Today** row: Generated, Imported, Exported and Used (House Load Today). Tap it to open the Today tab.
- A **Devices** grid with an Immersion tile (the water temperature) and an EV charger tile (the charger state). Each opens its sub-view.

For the EV load, the dashboard uses the first of these entities that exists, else the integration's own EV Charging Power: `sensor.myenergi_zappi_power_ct_internal_load`, `..._2`, `sensor.myenergi_zappi2_power_ct_internal_load`, `sensor.wallbox_charging_power`, `sensor.ohme_current_power`.

### Immersion (sub-view)

Only when an immersion heater or water temperature sensor is configured. A 12-hour chart of water temperature with the target and minimum, a tile with the divert reason, a 12-hour chart of the immersion's power in watts, and a card with energy, cost and savings today. The charts need a water temperature sensor.

### EV charger (sub-view)

Charger state, charge power, session energy, whether the EV is draining the battery, the mode decision, the charging source and the solar surplus available.

### Today

Energy totals (Generated, Import, Export, EV, Immersion), the current rate and rate period, import cost and export earnings, and self-sufficiency and self-consumption gauges. Two buttons open the sub-views below.

### Cost breakdown (sub-view)

Every cost line for today (import, export, EV, immersion, immersion savings, rest of house) and a bar graph of cost per day over 14 days.

### Solar and forecast (sub-view)

A solar against forecast card, when a forecast is configured, and a bar graph of solar generation per hour over 2 days.

The two graphs on the sub-views are statistics graphs, not history graphs. The daily sensors fall to zero at midnight, so a history graph of them draws a sawtooth. The graphs plot the change in each period instead, from the long-term statistics. They stay empty until Home Assistant has compiled statistics for the sensors, which takes up to an hour.

### Bill

Figures for the current bill period, so you can hold them against a real bill.

- **Bill so far**: Import cost this month, Export earnings this month, Accrued Bill This Period and Projected Bill This Period.
- **Bill period**: Days Elapsed in Bill Period and Days Remaining in Bill Period.
- **Import mix this month**: Average Import Rate This Month and Cheap rate import fraction this month.
- A **Tariff in use** button that opens the Tariff sub-view.

Days Elapsed in Bill Period, Average Import Rate This Month and Cheap rate import fraction this month are disabled by default. Enable them to see those rows.

Accrued Bill This Period is worked out line by line from the month totals: energy less the supplier saving, standing charge, PSO levy and VAT, minus the export credit. Projected Bill This Period scales it to the whole period. See [Tariff](tariff.md#bill-sensors). Import cost this month is the import energy for the period after discount and VAT. It leaves out the standing charge, the PSO levy and the export credit.

### Tariff (sub-view)

A table of the base rate and each timed rate period with its window, the rate, and the rate billed per kWh after the supplier discount and VAT. It also lists the export rate, standing charge, PSO levy and bill start day.

The table is read from your options when the file is generated, so generate the file again after you change the tariff. It uses the same defaults as the integration for any field you have not set.

### Battery

A 24-hour history of SoC and power, **Tonight's Charge Plan** (target, estimated cost, SoC at sunrise, cheap rate floor) and a **Battery detail** button. The state of charge gauge is only on the Power Flow tab.

### Battery detail (sub-view)

A **Tonight in words** card with the overnight charge reason and the night survival status, and battery health (cycles, remaining life, days since full charge, inverter temperature and status).

The charge reason and the night survival status are sentences. An entities row cuts them off, so they sit in a Markdown card.

### Controls

The charge target override switch and slider, Force Skip Charge Tonight, the immersion switches, divert reason and the three temperature numbers, and an EV charger button. A dry run banner and a dry run status card appear only while Dry Run Mode Active is true.

There is no Refresh Dashboard card. Use the button on the device page.

## HTML report cards

Three sensors carry a styled HTML report in their `html` attribute: Today's energy summary, Tonight's charge plan and This week's energy summary. They use inline styles, so the built-in Markdown card renders them.

They are disabled by default. Enable them in the entity list first.

```yaml
type: markdown
content: "{{ state_attr('sensor.givenergy_inverter_manager_todays_energy_summary', 'html') }}"
```

Replace the entity ID with the real one from **Settings → Entities**.
