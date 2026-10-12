# Quick start

Ten minutes from install to a working dashboard. Start with dry run on, so the integration decides but sends nothing to your inverter.

## Before you begin

- GivTCP is running and its entities appear in Home Assistant. Open **Developer Tools → States** and search for `givtcp_`. You should see entities such as `sensor.givtcp_<serial>_pv_power`.
- GivTCP's **Real Time Control** setting is on, and its day rate, night rate and tariff type are filled in. Without Real Time Control the inverter ignores the charge settings the integration writes. See [Writes to the inverter are not confirmed](troubleshooting.md#writes-to-the-inverter-are-not-confirmed).
- Leave GivTCP's SmartTarget off. Only this integration should set the charge target. A banner on the dashboard warns you if something else seems to. See [Something else is setting the charge target](troubleshooting.md#something-else-is-setting-the-charge-target).
- You know your unit rates, standing charge, VAT rate (if any), discount (if any) and bill start day. They are on your electricity bill or tariff sheet.

## Which serial do I use?

You do not enter a serial. The first screen finds the GivTCP devices in Home Assistant and uses the rules below. The serial you see is the one printed on the inverter label, and it is the name the integration is stored under.

| What GivTCP shows | What the integration manages |
|---|---|
| One inverter (hybrid, AC-coupled, All-In-One or three-phase) | That inverter |
| A Gateway over two or more All-In-Ones in parallel | The Gateway. The All-In-Ones behind it are read-only, because GivEnergy says to control only the Gateway |
| One All-In-One and a Gateway that is not in parallel | The All-In-One |
| Two or more other inverters | It asks you to choose one. It never adds two inverters together, and it does not pick for you |
| An EMS | It cannot write to an EMS. You choose the entities by hand and no charge settings are written |

GivTCP lets you change the device prefix for each inverter, so the entity ids need not start with `givtcp_`. The integration finds a device by what it publishes. A custom prefix works.

**What has been tested.** Only a single-phase hybrid has been run on real hardware. The other types are tested against entity lists built from GivTCP's published datapoint reference, and the screen says "not tested on real hardware" for them. If you run one, please open an issue with an anonymised entity list from **Developer Tools → States**.

## Steps

1. Install through HACS. Open **HACS → Integrations → Custom repositories**, add `https://github.com/macuistin/givenergy_inverter_manager` with category **Integration**, then install **GivEnergy Inverter Manager**.
2. Restart Home Assistant.
3. Open **Settings → Devices & Services → Add Integration** and search for **GivEnergy Inverter Manager**.
4. **Your system.** The first screen lists what was found and will be used: the inverter, an EV charger and a solar forecast sensor. Check the battery capacity and the maximum inverter output, then tick what to set up now. The tariff is ticked for you. If nothing is detected, see [Troubleshooting](troubleshooting.md#setup-finds-no-inverter).
5. **Tariff.** Enter your base rate and export rate from your bill or tariff sheet. If you set rates in GivTCP, the screen starts from them and says so. Check them against your bill. Then choose how many time-of-day rates you have besides the base rate: 0 for one rate all day, 1 for a day and night tariff. The rates screen after it has that many rows. Open **Bill details** if you have your bill to hand. Any tariff with time-of-day rates works, and so does a flat rate. See [Tariff](tariff.md).
6. **Hot water and forecast.** Tick them if you have an immersion heater, or no solar forecast was found. Every field is optional, and anything you skip can be set up later from **Configure**. See [Configuration](configuration.md).
7. Check the last screen and submit it. Then check that dry run is on. A new install starts with it on. The **Dry run** switch is in the Configuration section of **Settings → Devices & Services → GivEnergy Inverter Manager**, and on the dashboard's Settings view. It takes effect on the next update cycle.
8. Check the readings (next section).
9. Add the dashboard. Go to **Settings → Dashboards → Add dashboard** and pick **GivEnergy** under **Community dashboards**. A notification at setup says the same. See [Dashboard](dashboard.md). It opens with a dry run banner and, until the required setup is done, a checklist.
10. When the decisions look right, switch **Dry run** off.

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
