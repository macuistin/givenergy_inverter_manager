# Automation Examples

Example Home Assistant automations that use GivEnergy Inverter Manager sensors and services.

Replace `sensor.givenergy_inverter_manager_*` with your actual entity IDs — use the
`get_dashboard_yaml` service to generate a dashboard pre-filled with your real entity IDs,
which also reveals the correct names.

---

## Notify when GivTCP goes offline

Sends a mobile notification if GivTCP stops publishing data. The integration marks sensors
as `unavailable` after both solar and battery sensors go stale.

```yaml
alias: GivTCP offline alert
trigger:
  - platform: state
    entity_id: sensor.givenergy_inverter_manager_solar_power
    to: unavailable
    for:
      minutes: 2
action:
  - service: notify.mobile_app_your_phone
    data:
      title: GivEnergy — GivTCP offline
      message: Solar power sensor is unavailable. Check GivTCP is running.
```

---

## Notify when charge target is written

Fires each morning when the overnight charge target is applied to the inverter.

```yaml
alias: Charge target applied
trigger:
  - platform: state
    entity_id: sensor.givenergy_inverter_manager_overnight_charge_target
condition:
  - condition: time
    after: "01:00:00"
    before: "08:00:00"
action:
  - service: notify.mobile_app_your_phone
    data:
      title: GivEnergy — charge plan set
      message: >
        Charging to {{ states('sensor.givenergy_inverter_manager_overnight_charge_target') }}%
        — {{ states('sensor.givenergy_inverter_manager_overnight_charge_reason') }}
```

---

## Alert when night survival is at risk

Warns if the battery is predicted to run flat before sunrise.

```yaml
alias: Battery night survival warning
trigger:
  - platform: numeric_state
    entity_id: sensor.givenergy_inverter_manager_estimated_soc_at_sunrise
    below: 10
action:
  - service: notify.mobile_app_your_phone
    data:
      title: GivEnergy — battery may run flat
      message: >
        Estimated SoC at sunrise:
        {{ states('sensor.givenergy_inverter_manager_estimated_soc_at_sunrise') }}%.
        {{ states('sensor.givenergy_inverter_manager_night_survival_reason') }}
```

---

## Log daily energy totals to a helper

Creates a daily record of solar generation and import cost using an input_text helper.
Useful for external tracking or Google Sheets export.

```yaml
alias: Log daily energy summary
trigger:
  - platform: time
    at: "23:55:00"
action:
  - service: input_text.set_value
    target:
      entity_id: input_text.givenergy_daily_log
    data:
      value: >
        {{ now().date() }}: solar={{ states('sensor.givenergy_inverter_manager_solar_today') }}kWh,
        import={{ states('sensor.givenergy_inverter_manager_import_today') }}kWh,
        cost={{ states('sensor.givenergy_inverter_manager_import_cost_today') }}
```

---

## Force-skip charge on a specific night

Useful before a weekend when prices are higher and you have a strong forecast.

```yaml
alias: Skip charge this Saturday night
trigger:
  - platform: time
    at: "22:00:00"
condition:
  - condition: time
    weekday:
      - sat
action:
  - service: switch.turn_on
    target:
      entity_id: switch.givenergy_inverter_manager_skip_charge_override
  - service: notify.mobile_app_your_phone
    data:
      message: Overnight charge skipped for tonight.
```

---

## Weekly energy report

Sends a summary of the week's import cost and solar generation every Sunday evening.

```yaml
alias: Weekly energy report
trigger:
  - platform: time
    at: "19:00:00"
condition:
  - condition: time
    weekday:
      - sun
action:
  - service: notify.mobile_app_your_phone
    data:
      title: GivEnergy — weekly summary
      message: >
        This week: solar={{ states('sensor.givenergy_inverter_manager_solar_this_week') }}kWh,
        import cost={{ states('sensor.givenergy_inverter_manager_import_cost_this_week') }},
        self-sufficiency={{ states('sensor.givenergy_inverter_manager_self_sufficiency_this_week') }}%
```

---

## Check appliance run time before starting the dishwasher

Calls the `suggest_appliance_run` service and sends the verdict as a notification.

```yaml
alias: Dishwasher run suggestion
trigger:
  - platform: state
    entity_id: input_button.check_dishwasher
action:
  - service: givenergy_inverter_manager.suggest_appliance_run
    data:
      appliance_name: Dishwasher
      appliance_power_w: 1800
```

The integration fires a persistent notification with the recommendation. You can
redirect this to a mobile notification by listening for the `persistent_notifications_updated`
event or by using the [HA Companion App](https://companion.home-assistant.io/) notification
actions.

---

## Switch Zappi to Eco+ when solar surplus is available for EV charging

Uses `ev_solar_surplus_available` (ON when surplus > 1,400W and battery > protection threshold) to automatically switch the Zappi to solar absorption mode. Without this, the Zappi stays in Fast or Stopped mode and charges from the grid even when there's enough solar to cover it.

Requires the myenergi HA integration.

```yaml
alias: Zappi Eco+ on solar surplus
trigger:
  - platform: state
    entity_id: sensor.givenergy_inverter_manager_ev_solar_surplus_available
    to: Available
condition:
  - condition: not
    conditions:
      - condition: state
        entity_id: sensor.givenergy_inverter_manager_ev_charger_state
        state: Disconnected
action:
  - service: myenergi.set_zappi_mode
    data:
      serial: YOUR_ZAPPI_SERIAL
      mode: eco_plus
mode: single
```

Replace `YOUR_ZAPPI_SERIAL` with your Zappi's serial number (visible in the myenergi app).

---

## Alert when inverter is derating due to high temperature

Fires a notification when the inverter has been throttling generation for more than 30 minutes. Based on the 30-day analysis, derating can reduce generation by 50% or more on peak summer days.

```yaml
alias: Inverter derating alert
trigger:
  - platform: state
    entity_id: sensor.givenergy_inverter_manager_inverter_temperature_status
    to: Derating
    for:
      minutes: 30
action:
  - service: notify.mobile_app_your_phone
    data:
      title: "⚠️ Inverter Derating"
      message: >
        Inverter at {{ states('sensor.givenergy_inverter_manager_inverter_temperature') }}°C
        and has been derating for 30+ minutes. Check ventilation clearances.
        Generation losses typically 30–50% during derating.
mode: single
```

---

## Daily derating summary

Sends a summary at sunset of how many minutes the inverter spent derating today. Enable `sensor.inverter_derating_today_minutes` in the entity list first.

```yaml
alias: Daily derating summary
trigger:
  - platform: sun
    event: sunset
condition:
  - condition: numeric_state
    entity_id: sensor.givenergy_inverter_manager_inverter_derating_today_minutes
    above: 0
action:
  - service: notify.mobile_app_your_phone
    data:
      title: Inverter derating today
      message: >
        Inverter spent
        {{ states('sensor.givenergy_inverter_manager_inverter_derating_today_minutes') }}
        minutes derating today. Max temperature:
        {{ states('sensor.givenergy_inverter_manager_inverter_temperature') }}°C.
```
