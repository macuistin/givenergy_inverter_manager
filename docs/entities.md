# Entities

Everything except sensors. For sensors, see [Sensors](sensors.md).

All entities belong to one device, **GivEnergy Inverter Manager** (manufacturer GivEnergy, model Inverter Manager). Home Assistant builds entity IDs from the device name and the entity name, for example `switch.givenergy_inverter_manager_force_skip_overnight_charge`. Check yours in **Settings → Entities**.

## Switches

| Entity | Default | Restored after restart | What it does |
|---|---|---|---|
| Auto Immersion Divert | on | yes | On: the immersion rule runs. Off: the rule is bypassed and the managed switch asks for the real immersion switch to be off. The minimum temperature rule does not run while it is off. See [Concepts](concepts.md#immersion-divert) |
| Immersion Heater (Managed) | follows the decision | no | Only created when an immersion switch was set at setup. Shows whether the integration wants the heater on. Turning it on starts a run to target temperature. Turning it off switches the heater off and holds off automatic control for 10 minutes |
| Force Skip Overnight Charge | off | no | On: tonight's decision becomes skip, with the reason `Manual override: skip overnight charge`. At the write time the minimum SoC is written as the target. It is off again after a restart |
| Enable Charge Target Override | off | yes | Turning it off clears the manual target. See the note below |

### Manual charge target

Use the **Overnight Charge Target Override** number to set a target yourself. Moving the slider applies the override straight away, and the Overnight Charge Reason sensor reads `Manual override: charge to <n>%`. Turning **Enable Charge Target Override** off clears it and returns to the automatic target.

Turning the switch on does not apply the slider's value by itself. Move the slider after turning the switch on. The slider starts at 80 after every restart, and a switch restored as on does not re-apply a target, so set the slider again after a restart.

The configured cap does not limit a manual target. Force Skip takes priority over a manual target.

## Numbers

| Entity | Range | Default | What it does |
|---|---|---|---|
| Overnight Charge Target Override | 10 to 100, step 5 | 80 | The manual charge target. See above |
| Immersion Target Temperature | 40 to 75 °C, step 1 | 55 | The immersion stops heating at this temperature. Kept at least 1 °C above the minimum |
| Immersion Minimum Temperature | 30 to 60 °C, step 1 | 50 | Below this the immersion heats whatever the surplus. Kept at least 1 °C below the target |
| Immersion Restart Gap | 1 to 15 °C, step 1 | 5 | After reaching the target, the heater restarts only once the water is this far below it |

The three immersion numbers are restored after a restart and saved to the integration's data. Changing one of them updates the running integration. It does not reload it.

The restart gap stops rapid switching near the target. With the defaults the heater turns off at 55 °C and does not restart until the water drops below 50 °C.

## Button

| Entity | What it does |
|---|---|
| Refresh Dashboard | Runs the `get_dashboard_yaml` action, which rewrites `givenergy_dashboard.yaml` in the config folder. See [Dashboard](dashboard.md) |
