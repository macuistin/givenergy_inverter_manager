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

The file only contains tiles and cards that will show a value.

- A tile is left out when its entity is disabled or not registered. Many sensors are disabled by default. The file header and the **GivEnergy Dashboard Ready** notification list the disabled sensors the dashboard would have used. Enable them in **Settings → Devices & services → Entities**, then generate the file again.
- A section with no tiles left is left out too, so there is never a heading on its own.
- EV tiles and the EV charger sub-view need an EV charger. The dashboard counts a charger the integration has discovered, or one of the external power sensors listed under Power Flow.
- Immersion tiles, the Immersion heater section and the immersion charts need an immersion switch or temperature sensor in the options. The charts need the temperature sensor.
- Inverter temperature tiles need the inverter temperature entity in the options.
- The forecast tiles need a forecast entity in the options.

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

## Layout

Every view is a Home Assistant **sections** view. Each section is a column of cards that starts with a heading, and the sections sit side by side on a wide screen: one column on a phone, two on a tablet, three on a desktop. Tiles are the main building block. They are all horizontal, two to a row on a phone (six of the twelve grid columns), and use colour the same way everywhere: amber for solar, green for the battery and savings, blue for the grid and money, orange for the immersion, teal for the EV charger and indigo for the night.

Controls use tile features: a slider on the number entities, a toggle on the switches and a bar on state of charge. Charts take the full width of their section.

The dashboard has five tabs. Detail sits in six sub-views that have no tab. A tile or heading on a tab opens each sub-view, and the back arrow at the top of the sub-view returns to that tab. A heading that opens a view shows a chevron.

| Tab | Sub-views it opens |
|---|---|
| Power Flow | Immersion and EV charger (the Devices tiles), Battery detail (Night survival tile) |
| Today | Cost breakdown (Cost heading), Solar and forecast (Solar heading) |
| Bill | Tariff (the Tariff button in the Bill so far heading) |
| Battery | Battery detail (Battery heading) |
| Controls | none |

A sub-view and the tile that opens it are left out when the sub-view would be empty, for example Immersion without an immersion heater.

The links use relative paths, so they work at any dashboard URL.

### Power Flow

- **Now**: Battery (state of charge with a bar), Night survival, Rate now, Cost today, Cheap from (Next Cheap Rate Start) and Cheap in (Hours to Cheap Rate). Night Survival Confidence and the two cheap rate sensors are disabled by default, so a new install shows three of the six until you enable them. Night survival reads Safe, Warning or Critical. Tap it to open Battery detail, which says in words why. Tap the Battery tile to open the Battery tab.
- **Live power flow**: a power-flow-card-plus card with solar, battery, grid, home and two individual loads: the EV charger and the immersion. Solar shows a clipping marker. The battery node reads Battery Power for the flow and Battery State of Charge for the percentage. The grid node shows the Live Grid Cost Rate.
- **Energy today**: Generated, Used (House Load Today), Imported and Exported. Tap the heading to open the Today tab.
- **Devices**: an Immersion tile (the water temperature) and an EV charger tile (the charger state). Each opens its sub-view.

For the EV load, the dashboard uses the first of these entities that exists, else the integration's own EV Charging Power: `sensor.myenergi_zappi_power_ct_internal_load`, `..._2`, `sensor.myenergi_zappi2_power_ct_internal_load`, `sensor.wallbox_charging_power`, `sensor.ohme_current_power`.

### Immersion (sub-view)

Only when an immersion heater or water temperature sensor is configured.

- **Water temperature**: a 12-hour chart of water temperature with the target and minimum, and the divert reason under it in words.
- **Heater power**: a 12-hour step chart of the immersion's power in watts.
- **Today**: energy, cost and what solar saved.

The charts need a water temperature sensor.

### EV charger (sub-view)

- **Charging now**: charger state, charge power, session energy and charging source.
- **Why**: whether the EV is draining the battery, the solar surplus available and the mode decision in words.

### Today

- **Energy**: Generated, Used, Imported, Exported, EV and Immersion.
- **Cost**: Import cost, Export earnings, Rate now and Rate period. The heading opens Cost breakdown.
- **Solar**: Self-sufficiency and Self-consumption, each with a bar. The heading opens Solar and forecast.

### Cost breakdown (sub-view)

A tile for every cost line today (grid import, export earnings, rest of house, EV charging, immersion and what solar saved the immersion) and a bar graph of cost per day over 14 days.

### Solar and forecast (sub-view)

Generated today, today's forecast, how generation tracks the forecast and yesterday's accuracy, when a forecast is configured, and a bar graph of solar generation per hour over 2 days.

The two graphs on the sub-views are statistics graphs, not history graphs. The daily sensors fall to zero at midnight, so a history graph of them draws a sawtooth. The graphs plot the change in each period instead, from the long-term statistics. They stay empty until Home Assistant has compiled statistics for the sensors, which takes up to an hour.

### Bill

Figures for the current bill period, so you can hold them against a real bill.

- **Bill so far**: Accrued bill, Projected bill, Import cost and Export credit. A **Tariff** button in the heading opens the Tariff sub-view.
- **This bill period**: Days elapsed, Days left, Avg import rate and Cheap share (the cheap rate share of import).

Days Elapsed in Bill Period, Average Import Rate This Month and Cheap rate import fraction this month are disabled by default. Enable them to see those tiles.

Accrued Bill This Period is worked out line by line from the month totals: energy less the supplier saving, standing charge, PSO levy and VAT, minus the export credit. Projected Bill This Period scales it to the whole period. See [Tariff](tariff.md#bill-sensors). Import cost this month is the import energy for the period after discount and VAT. It leaves out the standing charge, the PSO levy and the export credit.

### Tariff (sub-view)

A table of the base rate and each timed rate period with its window, the rate, and the rate billed per kWh after the supplier discount and VAT. It also lists the export rate, standing charge, PSO levy and bill start day.

The table is read from your options when the file is generated, so generate the file again after you change the tariff. It uses the same defaults as the integration for any field you have not set.

### Battery

- **Battery**: state of charge with a bar, battery power with a 24-hour trend, and a 24-hour history of state of charge. The heading opens Battery detail.
- **Tonight's charge plan**: Target tonight, Est. cost, At sunrise (estimated state of charge) and Rate floor (the cheap rate floor).

State of charge and power are not drawn on one graph, because a percentage and watts share no scale.

### Battery detail (sub-view)

- **Tonight in words**: the overnight charge reason and the night survival status. They are sentences, and a tile cuts them off, so they sit in a Markdown card.
- **Battery health**: total cycles, life remaining, days since full charge, and the inverter temperature and status.

### Controls

- **Overnight charging**: a slider for the charge target, and the Use target and Skip tonight switches.
- **Immersion heater**: the Auto divert and Managed switches, the divert reason in words and sliders for the target temperature, the minimum temperature and the restart gap.
- **Dry run is on**: a banner with the last skipped action. It appears only while Dry Run Mode Active is true.

There is no Refresh Dashboard card. Use the button on the device page.

## HTML report cards

Three sensors carry a styled HTML report in their `html` attribute: Today's energy summary, Tonight's charge plan and This week's energy summary. They use inline styles, so the built-in Markdown card renders them.

They are disabled by default. Enable them in the entity list first.

```yaml
type: markdown
content: "{{ state_attr('sensor.givenergy_inverter_manager_todays_energy_summary', 'html') }}"
```

Replace the entity ID with the real one from **Settings → Entities**.
