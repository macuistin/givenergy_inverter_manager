# Dashboard

The integration writes a Lovelace dashboard, filled in with your real entity IDs, to `givenergy_dashboard.yaml` in the Home Assistant config folder.

## Generate the file

Either:

- Press **Refresh Dashboard** on the device page (**Settings → Devices & Services → GivEnergy Inverter Manager**), or
- Run the `givenergy_inverter_manager.get_dashboard_yaml` action in **Developer Tools → Actions**.

A notification, **GivEnergy Dashboard Ready**, confirms the write. The first time the integration is set up it also creates a placeholder file containing `views: []`, so a YAML-mode dashboard can point at the file straight away.

Generate the file again after you change the options, rename entities, or add an immersion temperature sensor. The file is overwritten.

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

## The four views

### Power Flow

- A power-flow-card-plus card with solar, battery, grid, home and two individual loads: the EV charger and the immersion. Solar shows a clipping marker. The battery card reads Battery Power for the flow and Battery State of Charge for the percentage. The grid node shows the Live Grid Cost Rate.
- An **Energy Today** row: Generated, Imported, Exported, Used (House Load Today) and Immersion.
- An immersion block, only when an immersion water temperature sensor is configured. It has a 12-hour chart of water temperature with the target and minimum, a tile with the divert reason, and a 12-hour chart of Immersion Heater Today.

For the EV load, the dashboard uses the first of these entities that exists, else the integration's own EV Charging Power: `sensor.myenergi_zappi_power_ct_internal_load`, `..._2`, `sensor.myenergi_zappi2_power_ct_internal_load`, `sensor.wallbox_charging_power`, `sensor.ohme_current_power`.

### Today

Energy totals, current rate and rate period, a cost breakdown (import, export, EV, immersion, immersion savings, rest of house), two 24-hour history graphs, a solar against forecast card, self-sufficiency and self-consumption gauges, and the bill prediction card.

### Battery

A SoC gauge, a 24-hour history of SoC and power, **Tonight's Charge Plan** (target, reason, estimated cost, SoC at sunrise, night survival, cheap rate floor), and battery health (cycles, remaining life, days since full charge, inverter temperature and status).

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
