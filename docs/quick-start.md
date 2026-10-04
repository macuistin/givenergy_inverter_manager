# Quick start

Ten minutes from install to a working dashboard. Start with dry run on, so the integration decides but sends nothing to your inverter.

## Before you begin

- GivTCP is running and its entities appear in Home Assistant. Open **Developer Tools → States** and search for `givtcp_`. You should see entities such as `sensor.givtcp_<serial>_pv_power`.
- You know your unit rates, standing charge and bill start day. They are on your electricity bill.

## Steps

1. Install through HACS. Open **HACS → Integrations → Custom repositories**, add `https://github.com/macuistin/givenergy_inverter_manager` with category **Integration**, then install **GivEnergy Inverter Manager**.
2. Restart Home Assistant.
3. Open **Settings → Devices & Services → Add Integration** and search for **GivEnergy Inverter Manager**.
4. **Inverter.** Confirm the detected inverter, battery capacity and maximum inverter output. If nothing is detected, see [Troubleshooting](troubleshooting.md#setup-finds-no-inverter).
5. **Tariff.** The form is pre-filled with Electric Ireland Home Electric with Nightboost rates. Replace every value with your own. See [Tariff](tariff.md).
6. **Forecast, immersion, EV charger, battery.** Fill in what you have and submit the rest as is. Each step can stay at its defaults. See [Configuration](configuration.md).
7. Turn on dry run. Open **Settings → Devices & Services → GivEnergy Inverter Manager → Configure**, expand **Battery & charging thresholds**, switch on **Dry run mode** and submit. The integration reloads.
8. Check the readings (next section).
9. Press **Refresh Dashboard** on the device page, then add the generated file as a dashboard. See [Dashboard](dashboard.md).
10. When the decisions look right, switch **Dry run mode** off.

## Check the readings

Open **Developer Tools → States** and filter for `givenergy_inverter_manager`.

| Check | Expect |
|---|---|
| Grid Power while the house is importing | A positive number. If it is negative, see [sign conventions](concepts.md#givtcp-sign-conventions) |
| Battery Power while the battery charges | A positive number |
| Current Rate Period | The name of the period active now, or your base rate name |
| Recommended Overnight Charge Target | A percentage |
| Overnight Charge Reason | A sentence that explains the target |
| Last Skipped Action (Dry Run) | What the integration would have written to the inverter, once the next write is due |

Entity IDs start with `sensor.givenergy_inverter_manager_` followed by the sensor name in snake case.

## What happens next

- Every 30 seconds the integration reads GivTCP, updates all sensors and re-evaluates its decisions.
- Once a day, one minute before your cheapest timed rate period starts, it writes the charge target to GivTCP. With dry run on it records the action instead.
- Daily totals reset at local midnight.

Next: read [Concepts](concepts.md), then open [Configuration](configuration.md) for the options.
