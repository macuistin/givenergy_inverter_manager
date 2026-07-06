# Dashboard

The integration includes a built-in dashboard generator that creates a ready-to-use Lovelace dashboard pre-filled with your actual entity IDs.

---

## Generating the dashboard

1. Go to **Developer Tools → Actions**
2. Search for `givenergy_inverter_manager.get_dashboard_yaml`
3. Click **Perform Action**
4. A notification appears with the complete dashboard YAML

<!-- screenshot: developer tools action panel showing the service -->

---

## Creating the dashboard

1. Go to **Settings → Dashboards → Add Dashboard**
2. Give it a name (e.g. "GivEnergy") and choose a blank dashboard
3. Open the new dashboard, click the three-dot menu, and select **Edit dashboard**
4. Click the three-dot menu again and select **Raw configuration editor**
5. Replace everything with the YAML from the notification and save

<!-- screenshot: raw configuration editor with YAML pasted in -->

---

## The four views

### Power Flow

Shows live energy flows between solar, battery, grid, and home. Also shows the current rate period, unit rate, and whether the inverter is clipping.

<!-- screenshot: power flow view -->

> This view requires **power-flow-card-plus** from HACS. If you see a "Configuration error", install it from HACS → Frontend → search "power-flow-card-plus", then clear your browser cache.

### Today

Shows today's energy totals (solar, import, export, EV, immersion), cost breakdown by load, self-sufficiency gauges, and bill prediction.

<!-- screenshot: today view -->

### Battery

Shows the current battery SoC gauge, tonight's charge plan with the recommended target and reason, estimated SoC at sunrise, night survival status, and battery health stats.

<!-- screenshot: battery view -->

### Controls

Shows the overnight charging controls (charge target override, force skip), immersion heater controls, and EV charger status.

<!-- screenshot: controls view -->

A yellow warning banner appears at the top of this view if dry run mode is active.

---

## Keeping the dashboard up to date

If you add entities or the integration is updated, run the `get_dashboard_yaml` service again and paste the updated YAML into the raw configuration editor. Your layout customisations will be replaced, so keep a copy if you've made significant changes.

---

## Using HTML report cards

Three sensors expose formatted HTML reports. To display them, add a Markdown card:

```yaml
type: markdown
content: "{{ state_attr('sensor.givenergy_inverter_manager_today_summary', 'html') }}"
```

These use inline styles only and work with the default Markdown card — no HACS dependency needed. The `today_summary`, `charge_plan`, and `week_summary` sensors are disabled by default; enable them in the entity list before using them.