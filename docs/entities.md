# Entities

Everything except sensors. For sensors, see [Sensors](sensors.md).

The immersion switches and numbers exist only while the device they need is set. The Auto Immersion Divert and Immersion Heater (Managed) switches and the two Immersion divert numbers need an immersion switch. Immersion Scheduled Heating and the three immersion temperature numbers need an immersion switch and a temperature sensor. They are created when the options set the device, and removed when the options clear it. See [Sensors](sensors.md) for the sensors that follow the same rule.

All entities belong to one device, **GivEnergy Inverter Manager** (manufacturer macuistin, model Inverter Manager). Home Assistant builds entity IDs from the device name and the entity name, for example `switch.givenergy_inverter_manager_force_skip_overnight_charge`. Check yours in **Settings → Entities**.

## Switches

| Entity | Default | Restored after restart | What it does |
|---|---|---|---|
| Auto Immersion Divert | on | yes | On: the immersion rule runs. Off: the rule is bypassed and the managed switch asks for the real immersion switch to be off. The minimum temperature rule does not run while it is off. See [Concepts](concepts.md#immersion-divert) |
| Immersion Heater (Managed) | follows the decision | no | Created only while an immersion switch is set. Shows whether the integration wants the heater on. Turning it on starts a run to target temperature. Turning it off switches the heater off and holds off automatic control for 10 minutes |
| Immersion Scheduled Heating | off | yes | Created only while an immersion switch and a water temperature sensor are set. On: the heater runs to the target in the cheapest rate window and in time for the hot water ready times. Surplus diversion is unchanged. See [Concepts](concepts.md#scheduled-immersion-heating) |
| Force Skip Overnight Charge | off | no | On: tonight's decision becomes skip, with the reason `Manual override: skip overnight charge`. At the write time the minimum SoC is written as the target. It is off again after a restart |
| Enable Charge Target Override | off | yes | On: tonight's target is the Overnight Charge Target Override value. Off: the automatic target. See the note below |
| Dry run | off, on for a new install | no, it is a saved setting | A control, in the Configuration section. On: nothing is sent to the inverter, the immersion or the EV charger. Reads on and cannot be turned off while the test instance file exists. See [Configuration](configuration.md#dry-run) |
| Verbose logging | off | no, it is a saved setting | A control, in the Configuration section. Writes per-cycle detail at debug level |

### Manual charge target

Use the **Overnight Charge Target Override** number to set a target yourself, then turn on **Enable Charge Target Override**. The Overnight Charge Reason sensor reads `Manual override: charge to <n>%`. Turning the switch off returns to the automatic target.

The switch decides whether the override applies and the slider holds the value. Turning the switch on uses the slider's current value, which is 80 until you move it. Moving the slider while the switch is off changes nothing until you turn the switch on. Both are restored after a restart, so what the two entities show is what the integration applies.

The configured cap does not limit a manual target. Force Skip takes priority over a manual target.

## Numbers

| Entity | Range | Default | What it does |
|---|---|---|---|
| Overnight Charge Target Override | 10 to 100, step 5 | 80 | The manual charge target. Restored after a restart. See above |
| Immersion Target Temperature | 40 to 75 °C, step 1 | 55 | The immersion stops heating at this temperature. Kept at least 1 °C above the minimum |
| Immersion Minimum Temperature | 30 to 60 °C, step 1 | 50 | Below this the immersion heats whatever the surplus. Kept at least 1 °C below the target |
| Immersion Restart Gap | 1 to 15 °C, step 1 | 5 | After reaching the target, the heater restarts only once the water is this far below it |
| Immersion divert minimum SoC | 50 to 100 %, step 5 | 80 | A control. Created only while an immersion switch is set. Solar surplus only goes to the immersion once the battery is above this |
| Immersion divert minimum surplus | 100 to 2000 W, step 100 | 500 | A control. Created only while an immersion switch is set. The smallest surplus that starts diverting power |
| Cheap rate floor SoC | 0 to 80 %, step 5 | 40 | A control. The battery is topped up in the cheapest window if it falls below this. 0 turns it off |
| Skip-charge SoC threshold | 20 to 100 %, step 1 | 75 | A control. Above this and with a good forecast, the overnight grid charge is skipped |
| Forecast conservatism | 0 to 1, step 0.05 | 0.35 | A control. 0 uses the plain forecast, 1 the pessimistic (P10) one |

The seven controls (Dry run, Verbose logging and the five numbers marked as controls) are configuration entities. Each saves the setting it always used, applies on the next 30-second cycle and shows the value in force. They are not restored from the last state: the saved setting is the value. See [Configuration](configuration.md#controls).

The three immersion temperature numbers are restored after a restart and saved to the integration's data. Changing one of them updates the running integration. It does not reload it.

The restart gap stops rapid switching near the target. With the defaults the heater turns off at 55 °C and does not restart until the water drops below 50 °C.

## Button

| Entity | What it does |
|---|---|
| Refresh Dashboard | Runs the `get_dashboard_yaml` action, which rewrites `givenergy_dashboard.yaml` in the config folder. See [Dashboard](dashboard.md) |
