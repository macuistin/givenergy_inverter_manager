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

## HACS cards

| Card | Needed for | Behaviour without it |
|---|---|---|
| [power-flow-card-plus](https://github.com/flixlix/power-flow-card-plus) | The live flow card in the Power Flow view | The card shows a configuration error |
| [apexcharts-card](https://github.com/RomRider/apexcharts-card) | The immersion charts in the Power Flow view | Those two charts show an error |

Everything else uses built-in Home Assistant cards.

## The five views

### Power Flow

- A **Now** strip at the top with six core cards: Battery state of charge, Night Survival Confidence, Current Rate, Next Cheap Rate Start, Hours to Cheap Rate and Import Cost Today. Night Survival Confidence and the two cheap rate sensors are disabled by default, so a new install shows three of the six until you enable them.
- A power-flow-card-plus card with solar, battery, grid, home and two individual loads: the EV charger and the immersion. Solar shows a clipping marker. The battery card reads Battery Power for the flow and Battery State of Charge for the percentage. The grid node shows the Live Grid Cost Rate.
- An **Energy Today** row: Generated, Imported, Exported, Used (House Load Today) and Immersion.
- An immersion block, only when an immersion water temperature sensor is configured. It has a 12-hour chart of water temperature with the target and minimum, a tile with the divert reason, and a 12-hour chart of Immersion Heater Today.

For the EV load, the dashboard uses the first of these entities that exists, else the integration's own EV Charging Power: `sensor.myenergi_zappi_power_ct_internal_load`, `..._2`, `sensor.myenergi_zappi2_power_ct_internal_load`, `sensor.wallbox_charging_power`, `sensor.ohme_current_power`.

### Today

Energy totals, current rate and rate period, a cost breakdown (import, export, EV, immersion, immersion savings, rest of house), a bar graph of cost per day over 14 days, a bar graph of solar generation per hour over 2 days, a solar against forecast card, and self-sufficiency and self-consumption gauges.

The two graphs are statistics graphs, not history graphs. The daily sensors fall to zero at midnight, so a history graph of them draws a sawtooth. The graphs plot the change in each period instead, from the long-term statistics. They stay empty until Home Assistant has compiled statistics for the sensors, which takes up to an hour.

### Bill

Figures for the current bill period, next to the tariff they were worked out from, so you can hold them against a real bill.

- **Bill so far**: Import cost this month, Export earnings this month, Accrued Bill This Period and Projected Bill This Period.
- **Bill period**: Days Elapsed in Bill Period and Days Remaining in Bill Period.
- **Import mix this month**: Average Import Rate This Month and Cheap rate import fraction this month.
- **Tariff in use**: a table of the base rate and each timed rate period with its window, the rate, and the rate billed per kWh after the supplier discount and VAT. It also lists the export rate, standing charge, PSO levy and bill start day.

The tariff table is read from your options when the file is generated, so generate the file again after you change the tariff. It uses the same defaults as the integration for any field you have not set.

Days Elapsed in Bill Period, Average Import Rate This Month and Cheap rate import fraction this month are disabled by default. Enable them to see those rows.

Accrued Bill This Period is worked out line by line from the month totals: energy less the supplier saving, standing charge, PSO levy and VAT, minus the export credit. Projected Bill This Period scales it to the whole period. See [Tariff](tariff.md#bill-sensors). Import cost this month is the import energy for the period after discount and VAT. It leaves out the standing charge, the PSO levy and the export credit.

### Battery

A SoC gauge, a 24-hour history of SoC and power, **Tonight's Charge Plan** (target, estimated cost, SoC at sunrise, cheap rate floor), a **Tonight in words** card with the overnight charge reason and the night survival status, and battery health (cycles, remaining life, days since full charge, inverter temperature and status).

The charge reason and the night survival status are sentences. An entities row cuts them off, so they sit in a Markdown card.

### Controls

The charge target override switch and slider, Force Skip Charge Tonight, the immersion switches, divert reason and the three temperature numbers, and the EV charger card. A dry run banner and a dry run status card appear only while Dry Run Mode Active is true.

There is no Refresh Dashboard card. Use the button on the device page.

## HTML report cards

Three sensors carry a styled HTML report in their `html` attribute: Today's energy summary, Tonight's charge plan and This week's energy summary. They use inline styles, so the built-in Markdown card renders them.

They are disabled by default. Enable them in the entity list first.

```yaml
type: markdown
content: "{{ state_attr('sensor.givenergy_inverter_manager_todays_energy_summary', 'html') }}"
```

Replace the entity ID with the real one from **Settings → Entities**.
