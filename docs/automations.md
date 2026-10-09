# Automation examples

Example automations that use GivEnergy Inverter Manager entities and actions.

Entity IDs are built by Home Assistant from the device name and the entity name, so the examples use the default English names, such as `sensor.givenergy_inverter_manager_recommended_overnight_charge_target`. Check each ID in **Settings → Entities** before you use an example. The generated [dashboard](dashboard.md) also uses your real IDs.

---

## Notify when GivTCP goes offline

Sends a mobile notification if the integration marks its sensors unavailable. That happens when both the solar power and battery SoC sensors are `unavailable`, `unknown` or missing. See [Troubleshooting](troubleshooting.md#all-entities-are-unavailable).

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
      title: GivEnergy, GivTCP offline
      message: Solar power sensor is unavailable. Check GivTCP is running.
```

---

## Report tonight's charge plan at the start of the cheap window

Set the time to the start of your cheapest timed rate period. The integration writes the target one minute earlier.

```yaml
alias: Charge plan report
trigger:
  - platform: time
    at: "02:00:00"
action:
  - service: notify.mobile_app_your_phone
    data:
      title: GivEnergy, charge plan
      message: >
        Target {{ states('sensor.givenergy_inverter_manager_recommended_overnight_charge_target') }}%.
        {{ states('sensor.givenergy_inverter_manager_overnight_charge_reason') }}
```

---

## Alert when the battery may run flat

Warns if the estimated SoC at 08:00 falls below 10%.

```yaml
alias: Battery overnight warning
trigger:
  - platform: numeric_state
    entity_id: sensor.givenergy_inverter_manager_estimated_soc_at_sunrise
    below: 10
action:
  - service: notify.mobile_app_your_phone
    data:
      title: GivEnergy, battery may run flat
      message: >
        Estimated SoC at sunrise:
        {{ states('sensor.givenergy_inverter_manager_estimated_soc_at_sunrise') }}%.
        {{ states('sensor.givenergy_inverter_manager_battery_overnight_outlook') }}
```

---

## Log daily energy totals to a helper

Writes a one-line daily record to an `input_text` helper. Create the helper first and set its maximum length to 255.

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
        {{ now().date() }}: solar={{ states('sensor.givenergy_inverter_manager_solar_generation_today') }}kWh,
        import={{ states('sensor.givenergy_inverter_manager_grid_import_today') }}kWh,
        cost={{ states('sensor.givenergy_inverter_manager_import_cost_today') }}
```

---

## Skip the charge on a specific night

Turns on Force Skip Overnight Charge before the cheap window, and off again in the morning. The switch stays on until something turns it off, so keep both automations.

```yaml
alias: Skip charge on Saturday night
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
      entity_id: switch.givenergy_inverter_manager_force_skip_overnight_charge
  - service: notify.mobile_app_your_phone
    data:
      message: Overnight charge skipped for tonight.
```

```yaml
alias: Clear the skip switch
trigger:
  - platform: time
    at: "08:00:00"
action:
  - service: switch.turn_off
    target:
      entity_id: switch.givenergy_inverter_manager_force_skip_overnight_charge
```

---

## Weekly energy report

Sends this week's solar, import cost and self-sufficiency every Sunday evening.

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
      title: GivEnergy, weekly summary
      message: >
        This week: solar={{ states('sensor.givenergy_inverter_manager_solar_generated_this_week') }}kWh,
        import cost={{ states('sensor.givenergy_inverter_manager_import_cost_this_week') }},
        self-sufficiency={{ states('sensor.givenergy_inverter_manager_self_sufficiency_this_week') }}%
```

---

## Check appliance run time

Calls `suggest_appliance_run`. The verdict arrives as a persistent notification.

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

The action returns no data, so the verdict appears only in the Home Assistant notifications panel. The notification ID is `givenergy_appliance_dishwasher`, built from the appliance name.

---

## Start another EV charger on solar surplus

The integration switches a Zappi to Eco+ by itself. For a charger it cannot control, use the EV Solar Surplus sensor, which reads `Available` at 1380 W of net surplus or more. Replace `switch.your_ev_charger` with your charger's switch.

```yaml
alias: EV charger on solar surplus
trigger:
  - platform: state
    entity_id: sensor.givenergy_inverter_manager_ev_solar_surplus
    to: Available
    for:
      minutes: 5
condition:
  - condition: not
    conditions:
      - condition: state
        entity_id: sensor.givenergy_inverter_manager_ev_charger_state
        state: disconnected
action:
  - service: switch.turn_on
    target:
      entity_id: switch.your_ev_charger
mode: single
```

---

## Alert when the inverter is derating

Fires when the inverter temperature status has been Derating for 30 minutes. Derating starts at 65 °C.

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
      title: GivEnergy, inverter derating
      message: >
        Inverter at {{ states('sensor.givenergy_inverter_manager_inverter_temperature') }} °C
        and derating for 30 minutes. Check ventilation around the inverter.
mode: single
```

---

## Daily derating summary

Sends the minutes spent at 65 °C or more, at sunset. Enable the Inverter Derating Today sensor first. It is disabled by default.

```yaml
alias: Daily derating summary
trigger:
  - platform: sun
    event: sunset
condition:
  - condition: numeric_state
    entity_id: sensor.givenergy_inverter_manager_inverter_derating_today
    above: 0
action:
  - service: notify.mobile_app_your_phone
    data:
      title: Inverter derating today
      message: >
        The inverter spent
        {{ states('sensor.givenergy_inverter_manager_inverter_derating_today') }}
        minutes derating today. Temperature now:
        {{ states('sensor.givenergy_inverter_manager_inverter_temperature') }} °C.
```
