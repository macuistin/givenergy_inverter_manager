# Troubleshooting

Find your symptom, then follow the steps.

## The integration is not in the Add Integration list

1. Check that `custom_components/givenergy_inverter_manager/` exists in your config folder.
2. Restart Home Assistant. A new custom integration loads only at startup.

## Setup finds no inverter

The wizard looks for an entity whose ID contains `givtcp_` and ends in `_invertor_serial_number`. GivTCP spells "inverter" as "invertor".

1. Open **Developer Tools → States** and search for `invertor_serial_number`. If nothing appears, GivTCP has not published to Home Assistant yet.
2. Check GivTCP is running and that it uses the same MQTT broker as Home Assistant. The listen panel under **Settings → Devices & Services → MQTT** shows whether GivTCP is publishing.
3. Wait a minute after GivTCP starts, then start the wizard again.
4. If the inverter shows "(some sensors missing)", pick it anyway and fill in the five power sensors by hand.

The error "One or more required inverter entities are missing" means one of the five power sensors (solar, battery SoC, battery power, grid, house load) is empty.

The manual path does not ask for the charge control entities. Without them the integration cannot write charge targets. If you need them, get GivTCP publishing all its entities and set the integration up again.

## All entities are unavailable

The integration marks every entity unavailable when **both** the solar power sensor and the battery SoC sensor are `unavailable`, `unknown` or missing. This is how it reacts to GivTCP stopping.

1. Open **Settings → System → Logs** and search for `givenergy`. You will see `GivTCP has stopped publishing data` when this starts and `GivTCP is publishing data again` when it clears.
2. Restart the GivTCP add-on, and check the MQTT integration shows as connected.
3. Entities recover on their own within one 30-second cycle after GivTCP returns.

Related behaviour:

- If only one of the two sensors drops out, the integration keeps running and reads the missing value as 0.
- The integration judges by the entity's state, not its age. If GivTCP leaves the last value in place when it stops, the integration keeps using it.
- At startup, a failed first read raises "First data fetch failed" and Home Assistant retries the setup on its own.
- If both entities are missing from Home Assistant entirely, the repair **GivTCP entities not found** appears. See [GivTCP entities not found](#givtcp-entities-not-found).

## GivTCP entities not found

The repair **GivTCP entities not found** appears in **Settings → System → Repairs** when the solar power and battery SoC entities chosen at setup no longer exist in Home Assistant. This usually means GivTCP was reinstalled with another serial, or its entity IDs changed.

1. Open **Developer Tools → States** and search for `givtcp_`. Note the new serial in the entity IDs.
2. Remove the integration and add it again, picking the new inverter. The repair text points to Reconfigure, but Reconfigure only edits the tariff.
3. Accumulated energy is kept, because the storage file is not deleted.

The repair clears on its own once both entities exist again.

## Options form errors

- **"Entity is neither a valid entity ID nor a valid UUID" on save.** This was a bug in v0.2.1 when a forecast or carbon intensity field was empty. Update to v0.3.0. In v0.3.0 an empty field saves as empty, and clearing a saved entity removes it.
- **Battery divert threshold or surplus is not on the page.** They are set at setup only. See [Configuration](configuration.md#step-6-battery).
- **Entities went unavailable after saving.** Saving reloads the integration. It takes a few seconds. If entities have not recovered after 30 seconds, check the log for errors.

## Battery minimum SoC is set too high

The repair **Battery minimum SoC is set too high** appears when the saved minimum SoC is above 30%. Older versions accepted higher values. On a skip night the integration writes the minimum SoC as the charge target, so a high value holds the battery at that level all night and imports from the grid.

1. Open **Settings → Devices & Services → GivEnergy Inverter Manager → Configure**.
2. In the Battery & charging thresholds section, set **Minimum battery SoC** to 10 to 20.
3. Save. The repair clears on the next update cycle after the integration reloads.

## Other charge slots are active

The repair **Other charge slots are active** appears when a GivTCP charge slot other than the one the integration writes has a window set. The integration writes slot 1 only, and the inverter charges in every active slot. For example, a leftover slot 2 from 00:00 to 08:00 starts charging at midnight, which can be a dearer rate than a cheaper window later in the night.

A slot counts as active when its start time differs from its end time. 00:00 to 00:00 means unused. Slots 2 to 10 are checked on every update cycle, and a slot whose entities are missing or unavailable is ignored.

To clear the slots in one step:

1. Open **Settings → System → Repairs** and open **Other charge slots are active**.
2. Check the slots named in the text, then select **Submit**.
3. The integration sets the start and end time of each named slot to 00:00. Each change is read back and counted as an inverter register write. The repair clears on the next update cycle.

With **Dry run mode** on, nothing is changed. **Last Skipped Action (Dry Run)** shows what would have been cleared, and the repair stays.

To clear a slot by hand:

1. Open **Developer Tools → States** and search for `charge_start_time_slot_`.
2. For each active slot, call `select.select_option` with option `00:00:00` on both its `charge_start_time_slot_N` and `charge_end_time_slot_N` entities.

Slot 1 is never changed by this repair.

## Battery cost is not set

The repair **Battery cost is not set** appears when **Battery cost** is 0 and the integration has been tracking the battery for 7 days. With no cost, battery wear is 0, so **Net Saving Today** equals **Saving vs Grid Today**. A battery cost also feeds **Battery Cycle Cost per kWh** and the immersion divert rule. See [Configuration](configuration.md#battery--charging-thresholds).

To set it from the repair:

1. Open **Settings → System → Repairs** and open **Battery cost is not set**.
2. Enter what the battery cost, then select **Submit**.
3. The value is saved to the integration options and the integration reloads. Every other saved option is kept. The repair clears on the next update cycle.

You can also set **Battery cost** under **Configure**, in the Battery & charging thresholds section.

The repair appears once. If you do not want wear counted, select **Ignore** and it stays out of the way. It is raised again only if the cost is set and then set back to 0.

## GivTCP rates differ from the tariff

The repair **GivTCP rates differ from your tariff** appears when GivTCP holds a day, night or export rate that disagrees with the tariff entered in this integration. A wrong rate scales every cost figure, so both values are shown, for example `Day rate: 0.3334 here, 0.395 in GivTCP`.

The integration reads these GivTCP sensors for your inverter serial: `day_rate`, `night_rate` and `export_rate`. Nothing is set up for this. If the sensors are missing, unavailable or 0, nothing is shown.

How the rates are compared:

- The GivTCP day rate is compared with the base rate, and the export rate with the export rate.
- GivTCP has one night rate. It agrees when it matches any timed rate period, so a tariff with a night and a boost period is not flagged for either. A tariff with no timed period has no night rate to compare.
- A rate counts as different when it is more than 2% away from the rate entered here.

The rates entered here always win. Every cost figure in this integration uses them, and GivTCP's rates are shown for comparison only. The repair does not change either side. To clear it:

1. Decide which rate is right, using your latest bill.
2. If the rate here is wrong, open **Configure** and correct it. See [Tariff](tariff.md).
3. If the GivTCP rate is wrong, correct it in GivTCP. This only affects GivTCP's own cost sensors.

The repair clears on the next update cycle once the rates agree. It appears once, and **Ignore** keeps it out of the way until the rates agree and then differ again. While GivTCP is unavailable, the repair is left as it is.

## The tariff has not been reviewed

The repair **Tariff rates have not been reviewed** appears when the tariff has gone 365 days without being saved changed or confirmed. The date counts from the last saved change to the tariff, the last dated change recorded, the last Reconfigure, or the last time you confirmed the rates in the repair. The first run after an upgrade records that day, so the repair appears 365 days later at the earliest. The repair does not change anything and does not affect any sensor.

1. Check the rates against your latest bill.
2. If a rate changed, open **Settings → Devices & Services → GivEnergy Inverter Manager → Configure** and save the new rates. To start them on a later date, use the **Dated rate change** section. See [Tariff](tariff.md#change-the-rates-from-a-date).
3. If the rates are right, open **Settings → System → Repairs**, open **Tariff rates have not been reviewed** and select **Submit**. The repair clears on the next update cycle and returns after another 365 days.

## Daily sensors are frozen after an upgrade

Version 0.2.1 gave nine daily sensors the state class `total_increasing` together with `last_reset`. Home Assistant refuses that combination, so the sensors stopped updating until the integration reloaded. Battery throughput, for example, stayed at one value until the integration reloaded.

The nine sensors are Import at cheap rate, Import at base rate, Import cost at cheap rate, Import cost at base rate, Immersion solar savings, Immersion solar diverted, Battery throughput, Missed solar today and Inverter Derating Today. The two base rate sensors were called Import at peak rate and Import cost at peak rate before they were renamed (see [Renamed sensors](sensors.md#renamed-sensors)).

1. Update to v0.3.0 or later, where they use state class `total`.
2. Restart Home Assistant, or reload the integration.
3. Watch one of the nine for a minute. It should change while the house uses power.

See [Long-term statistics](long-term-statistics.md) and [Upgrade notes](upgrade-v0.3.0.md).

## Repairs say a sensor "no longer has a state class"

After an upgrade, Settings → System → Repairs can list sensors such as `grid_import_yesterday` or `solar_trailing_12_months`. They are snapshot values, not running totals, so the integration no longer gives them a state class. Home Assistant is pointing out that statistics it already holds for them are now stale.

Open **Developer Tools → Statistics**, choose **Fix issue** on each sensor and delete the old statistics. See [Long-term statistics](long-term-statistics.md#upgrading-statistics-that-change) for the full list.

## Daily totals do not reset at midnight

Solar, import, export, battery charged, battery discharged and house load for today follow the GivTCP daily counters when those exist. The sensor then follows the GivTCP counter, including the moment that counter resets. Compare the six `sensor.givtcp_<serial>_*_energy_today_kwh` entities.

## Grid import and export look swapped

The integration expects GivTCP's grid power to be positive when exporting. Export to the grid on a sunny day, then compare the GivTCP grid power entity with **Grid Power** in **Developer Tools → States**. They must have opposite signs. See [sign conventions](concepts.md#givtcp-sign-conventions).

## The charge target is not written to the inverter

Work through this list.

1. Is **Dry run mode** on? Then nothing is sent. **Last Skipped Action (Dry Run)** shows what would have been written.
2. Were the charge control entities detected? Without a target SoC entity nothing is written. The tariff step of setup shows how many of the five were found.
3. Does the tariff have at least one timed rate period? With a flat tariff there is no cheap window and no write.
4. The write happens once a day, one minute before the cheapest timed period starts. If your cheapest period starts at 02:00, that is 01:59. With debug logging on (see the next section), search the log for `Writing charge target`.
5. Is **Force Skip Overnight Charge** on? Then the minimum SoC is written as the target.
6. Was the same entity written in the last 5 minutes? The write is skipped. With debug logging on, the log says `write cooldown active`.
7. Check GivTCP's own log for rejected writes.

## Find out what changed the charge target

The charge target, the charge window start and the charge window end can be changed by the integration, by you, by an automation, by GivTCP or by the inverter app. The integration keeps a log of the last 20 changes to these entities, plus the switches it turns on and off with them.

1. Open **Developer Tools → States** and search for `register_write_count`. The **GivTCP Register Write Count** sensor holds the log in its `recent_writes` attribute, newest first.
2. Read each entry. `time`, `entity_id` and `value` say what changed and when. `reason` says why: `charge target`, `charge window start`, `charge window end`, `floor top-up`, `clear other slot` and similar mean the integration wrote it. `external` means something else changed it.
3. For an `external` entry, look at `user_id` and `parent_id`. A `user_id` is the Home Assistant user who made the change, for example from a dashboard card. Look it up under **Settings → People**. A `parent_id` is the context of the automation or script that made the change. Search your automation traces for it.
4. If `user_id` and `parent_id` are both empty, the change did not come through a Home Assistant service call. GivTCP, the inverter app or the inverter itself made it.
5. Search **Settings → System → Logs** for `outside the manager` to see the same entries as log lines, with the old and new value.

The integration only records these changes. It does not undo them. The log is saved with the integration's other stored data, so it survives restarts. The `external` entries cover the charge target, window start and window end entities only.

## A charge decision looks wrong

Read **Overnight Charge Reason** first. Then check these:

- **The target is lower than expected, and the reason ends "capped at configured max".** **Default overnight charge target** caps the calculated target. It is 80 unless you changed it, and the cap applies to the winter 100% target too.
- **The sensor differs by a few points from the value written to the inverter.** **Recommended Overnight Charge Target** holds its value until the calculated target moves 5 points or more, so the history stays readable. The write uses the latest calculation, and the sensor matches it from the next cycle. See [Overnight charge target](concepts.md#overnight-charge-target).
- **December to February.** The target is 100% before the cap, whatever the forecast.
- **March, April, October and November.** The minimum SoC is at least 70% in the calculation.
- **No forecast.** Without a tomorrow sensor, the integration uses a seasonal estimate from your latitude. The reason says so.
- **A forecast setting has no effect.** Forecast provider is stored and unused. A P10 forecast only matters when conservatism is above 0, and conservatism only matters when a P10 forecast exists. Solcast provides one automatically. The charge reason says `no P10 forecast so conservatism is unused` otherwise. See [Where the P10 comes from](configuration.md#where-the-p10-comes-from).
- **The charge reason shows no `recent accuracy` factor.** The correction needs 5 usable days. Days with clipping, or under 0.5 kWh of forecast or solar, do not count. The attributes of **Overnight Charge Reason** show how many days are usable (`accuracy_status`, for example `Waiting for data: 3 of 5 days`). A new install reads earlier days from the recorder when it first loads, so it shows up to 9 usable days at once. It shows 0 when the recorder is not running, holds no history for the forecast sensor or the GivTCP daily solar counter, or those sensors are new. Then it fills one night at a time, and the first midnight only remembers the forecast. See [Forecast accuracy correction](configuration.md#forecast-accuracy-correction).
- **A manual target.** See [Entities](entities.md#manual-charge-target).

To see every reading and decision, turn on both of these:

1. **Verbose logging** in Configure, under Battery & charging thresholds.
2. Debug logging for the integration. Either press **Enable debug logging** on the integration page, or add this to `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.givenergy_inverter_manager: debug
```

## The immersion does not turn on

Read **Immersion Divert Reason**. It gives the exact block.

| Reason starts with | Fix |
|---|---|
| `No immersion switch configured` | No immersion switch entity is set, so there is nothing to turn on |
| `Manual override` | **Auto Immersion Divert** is off. Turn it on |
| `Water already at` | The water is at the target. Wait for it to cool by the restart gap |
| `Battery SoC ... below threshold` | The divert threshold (default 80%) is set at setup only |
| `Insufficient surplus` | Surplus is below the minimum (default 500 W). Cloud, or a large house load |
| `Water at ... will restart below` | The restart gap is holding it off. Lower **Immersion Restart Gap** |
| `Export rate ... below battery cycle cost` | Battery cost is set and exceeds the export rate. Set battery cost to 0 to turn the check off |

If the reason says to heat but the heater stays off, check that an immersion switch entity was set at setup, and that the 10-minute hold after the last switch has passed. In dry run the real switch is never touched.

## The Zappi changed to Eco+

With a Zappi that has a charge mode entity, a car plugged in and net solar surplus of at least 1380 W, the integration selects Eco+. It never selects Stopped. The only way to stop it is dry run. See [Concepts](concepts.md#ev-charger).

## Totals are lower after a crash

Accumulated energy is saved every 5 minutes, at midnight, when the integration unloads and when Home Assistant stops. See [Concepts](concepts.md#the-30-second-cycle). Only a crash or a power cut can lose up to about 5 minutes of energy.

## The bill sensors look low early in the period

Accrued Bill This Period is built from the month totals, which start again on the bill start day. Early in a period it is low because few days have passed. See [Tariff](tariff.md#bill-sensors).

## A sensor shows unknown

| Sensor | Reason |
|---|---|
| EV sensors | Unavailable until an EV charger is discovered. Discovery retries about every 5 minutes, until the charger's power, session and charge mode entities are all found |
| Inverter Temperature and its status | GivTCP has no `sensor.givtcp_<serial>_invertor_temperature` entity (GivTCP spells it "invertor") and none is stored in the entry. The integration looks for that entity from the inverter serial on every cycle, so it picks the sensor up once GivTCP creates it. The status shows Unknown until then |
| Solar forecast today (provider), Solar vs provider forecast and the carbon sensors | No provider forecast was seen before midnight (a new install has none until its first midnight, and a forecast sensor that was unavailable then leaves the day without one), or no carbon intensity sensor is set |
| Minutes Remaining in Rate Period | You are on the base rate |
| Battery Years Remaining | Fewer than 7 days of cycle data |
| Battery Cycle Cost per kWh, Throughput Budget sensors | Battery cost or budget is 0 |
| Average Import Rate sensors | Nothing imported yet in that period |

Many sensors are disabled by default. See [Sensors](sensors.md).

## Dashboard cards show errors

- The live flow card in the Power Flow view needs power-flow-card-plus. Install it from HACS if the card shows an error.
- The immersion chart needs apexcharts-card. Without it the sub-view uses a built-in history graph, which draws the heater's power as a line and cannot shade the times it was on.
- HTML report cards that show plain text: use a built-in `markdown` card and enable the report sensor. See [Dashboard](dashboard.md#html-report-cards).

## Getting help

Open an issue on [GitHub](https://github.com/macuistin/givenergy_inverter_manager/issues). Include:

- the log lines from **Settings → System → Logs** that contain `givenergy`;
- your Home Assistant and GivTCP versions;
- the diagnostics file, from the integration page, **Download diagnostics**. It holds your configuration, including tariff values. The inverter serial and every entity ID that contains it are redacted. Read it before you post it;
- what you expected and what happened.
