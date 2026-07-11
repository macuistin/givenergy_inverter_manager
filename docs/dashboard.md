# Dashboard

The integration generates a ready-to-use Lovelace dashboard pre-filled with your actual entity IDs and writes it directly to your HA config directory as `givenergy_dashboard.yaml`.

---

## Generating the dashboard

Run the **Refresh Dashboard** action in one of two ways:

**From the device page (recommended):**
1. Go to **Settings → Integrations → GivEnergy Inverter Manager**
2. Click the device card
3. Press the **Refresh Dashboard** button

**From Developer Tools:**
1. Go to **Developer Tools → Actions**
2. Search for `givenergy_inverter_manager.get_dashboard_yaml`
3. Click **Perform Action**

A notification appears confirming the file was written and showing setup instructions.

---

## Setting up the dashboard

### UI mode (most users)

1. Open `givenergy_dashboard.yaml` in your HA config directory (e.g. via the File Editor add-on or SSH)
2. Copy the entire contents
3. Go to **Settings → Dashboards → Add Dashboard → Blank**
4. Give it a name, click the three-dot menu → **Edit dashboard → Raw configuration editor**
5. Replace everything with the copied YAML and save

### YAML mode

If you manage your Lovelace dashboards in `configuration.yaml`, add this block once:

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

Then restart HA. The dashboard will appear in the sidebar and will use the generated file directly.

---

## Keeping the dashboard up to date

After reconfiguring the integration (e.g. changing tariff rates or adding a second forecast sensor), press the **Refresh Dashboard** button again. The file is overwritten in place. Restart HA or reload the dashboard to pick up the changes.

The Controls tab of the dashboard also includes a **Refresh Dashboard** button card.

---

## The four views

### Power Flow

Live animated energy flows between solar, battery, grid, and home. Shows the current unit rate on the grid node, battery SoC, and whether the inverter is clipping. Also shows immersion temperature history when a temperature sensor is configured.

> This view requires **power-flow-card-plus** from HACS. If you see a "Configuration error", install it from HACS → Frontend → search "power-flow-card-plus".

> The immersion temperature graph requires **apexcharts-card** from HACS.

### Today

Current rate and rate period at the top, followed by today's energy totals (solar, import, export, EV, immersion), cost breakdown by load including immersion savings, self-sufficiency gauges, and bill prediction.

### Battery

Battery SoC gauge, live charge/discharge power, tonight's charge plan (recommended target, reason, estimated cost, estimated SoC at sunrise, night survival status, cheap rate floor activity), and battery health stats.

### Controls

Switches and overrides for overnight charging, immersion heater (including inline temperature sliders), and EV charger status. Also includes a **Refresh Dashboard** button.

A yellow warning banner appears at the top if dry run mode is active.

---

## Using HTML report cards

Three sensors expose formatted HTML reports. To display them, add a Markdown card:

```yaml
type: markdown
content: "{{ state_attr('sensor.givenergy_inverter_manager_today_summary', 'html') }}"
```

These use inline styles only and work with the default Markdown card — no HACS dependency needed. The `today_summary`, `charge_plan`, and `week_summary` sensors are disabled by default; enable them in the entity list before using them.
