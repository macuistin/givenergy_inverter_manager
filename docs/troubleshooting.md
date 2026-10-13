# Troubleshooting

Find your symptom, then follow the steps.

## The integration is not in the Add Integration list

1. Check that `custom_components/givenergy_inverter_manager/` exists in your config folder.
2. Restart Home Assistant. A new custom integration loads only at startup.

## Setup finds no inverter

The first screen says "No GivTCP inverter was found" when nothing matches. The wizard looks for an entity that ends in `_invertor_serial_number`, whatever comes before it, so a device prefix you changed in GivTCP is found too. A Gateway or an EMS may have no serial entity, so a device that reports a GivTCP version together with a state of charge, Gateway or EMS values is found as well. GivTCP spells "inverter" as "invertor".

1. Open **Developer Tools → States** and search for `invertor_serial_number`. If nothing appears, GivTCP has not published to Home Assistant yet.
2. Check GivTCP is running and that it uses the same MQTT broker as Home Assistant. The listen panel under **Settings → Devices & Services → MQTT** shows whether GivTCP is publishing.
3. Wait a minute after GivTCP starts, then start the wizard again.
4. If the first screen says the inverter has some sensors missing, go on. The next screen asks for the five power sensors, with the ones that were found filled in.

The error "A required inverter entity is missing or unavailable" means one of the five power sensors (solar, battery SoC, battery power, grid, house load) is empty, does not exist or reads unavailable.

The by-hand screen does not ask for the charge control entities. Without them the integration cannot write charge targets. If you need them, get GivTCP publishing all its entities, then open **Reconfigure** and use the entities it finds.

## All entities are unavailable

The integration marks every entity unavailable when **both** the solar power sensor and the battery SoC sensor are `unavailable`, `unknown` or missing. This is how it reacts to GivTCP stopping.

1. Open **Settings → System → Logs** and search for `givenergy`. You will see `GivTCP has stopped publishing data` when this starts and `GivTCP is publishing data again` when it clears.
2. Restart the GivTCP add-on, and check the MQTT integration shows as connected.
3. Entities recover on their own within one 30-second cycle after GivTCP returns.

Related behaviour:

- If only one of the two sensors drops out, the integration keeps running and reads the missing value as 0.
- If GivTCP stops and its entities keep their last values, they are not `unavailable`, so this check does not fire. A separate check looks at when the entities were last reported, not at their value. See [GivTCP data is frozen](#givtcp-data-is-frozen).
- At startup, a failed first read raises "First data fetch failed" and Home Assistant retries the setup on its own.
- If both entities are missing from Home Assistant entirely, the repair **GivTCP entities not found** appears. See [GivTCP entities not found](#givtcp-entities-not-found).

## GivTCP data is frozen

The repair **GivTCP has stopped updating** appears when GivTCP's solar, battery and load entities still hold values, but none of them has been reported for 10 minutes. This is what a crashed GivTCP add-on looks like: MQTT keeps the last retained values, so the entities are not `unavailable` and look normal while nothing moves. For example, the state of charge sits at one number all night.

The check uses the time each entity was last reported, which Home Assistant refreshes on every publish even when the value is the same. A steady reading, such as a battery at 100%, does not trip it while GivTCP is running. A GivTCP restart of a few minutes does not trip it either.

While the feed is frozen the integration stops planning and stops writing to the inverter, because every figure would come from old readings. Its entities show unavailable, the same as when GivTCP is silent. A held charge plan is kept and resumes when the feed does. The log has one warning starting `GivTCP data is frozen, not unavailable`, and `GivTCP is reporting again` when it ends. The repair clears by itself on the next cycle after GivTCP reports.

1. Open the GivTCP log and look for a crash or an error since the last upgrade or restart.
2. Check that GivTCP's day rate, night rate and tariff type are filled in. An empty day rate stopped GivTCP v3.6.3 from starting.
3. Check that GivTCP's **Real Time Control** is on. An upgrade can reset it, and writes to the inverter are then not confirmed. See [Writes to the inverter are not confirmed](#writes-to-the-inverter-are-not-confirmed).
4. Restart GivTCP and check that **Settings → Devices & Services → MQTT** shows it connected.

After a Home Assistant restart the entities start as freshly reported, so a GivTCP that is already stopped shows as frozen about 10 minutes later.

## GivTCP is not getting data from the inverter

The repair **GivTCP is not getting data from the inverter** appears when GivTCP is running and reporting, but cannot read the inverter. GivTCP 3.6 and later keep publishing the last good data when a read fails, so the entities stay available and look normal while they are old. GivTCP says so in two sensors: `status` shows `paused` when GivTCP has stopped talking to a struggling inverter on purpose, and `Data_Age` counts the seconds since the last good read. The repair appears when the status is `paused`, or when `Data_Age` is over 10 minutes, or is `-1` because nothing has been read yet. Earlier GivTCP releases do not publish `Data_Age`, so a stale feed cannot be seen there and only the frozen check applies.

While it lasts the integration stops planning and stops writing to the inverter, and its entities show unavailable. The log has one warning starting `GivTCP is not getting data from the inverter`, and `GivTCP is reporting again` when it ends. The repair clears by itself on the next cycle.

1. Check that the inverter is powered and on the network.
2. Check that nothing else is connected to the inverter at the same time. Most inverters allow one connection.
3. Open the GivTCP log and look for connection or timeout errors.
4. Restart GivTCP.

## Energy totals jumped after a GivTCP upgrade

GivTCP publishes cumulative energy for the day (solar, import, export, battery charge and discharge, load and AC charge). An upgrade can change what a counter holds. GivTCP 3.6 changed the units of the energy totals on a Gateway, so a counter can step by about a thousand times.

The integration checks every reading against the one before it. A counter can only rise by what the system could deliver in the time between the two readings: the inverter's maximum output times the elapsed time, with a margin of four and a small allowance for rounding. A rise above that is not energy. When it happens:

- Nothing is booked for the step, in today's totals or in the week, month and year.
- The log has one warning, starting `The ... energy counter went from`, and it says `a probable unit change` when the counter rose by about a thousand times.
- That counter is left out of today's totals, which fall back to the integration's own sum of power, until the counter falls at the next daily reset. After a step its value is wrong for the rest of the day.
- A counter that spikes and then falls back to where it was is trusted again as soon as it does, and only what it added since is booked.

If you see the warning after an upgrade, open **Developer Tools → States** and compare the counter with GivTCP's own display. The **Inverter maximum output** setting (**Configure → Battery**) matters here: a value much lower than your real inverter makes the allowance too small for a house that draws a lot. Home Assistant's own Energy dashboard reads the GivTCP sensors directly, so a Gateway total that changed units shows as one large spike there. Correct it in **Developer Tools → Statistics**.

The guard keeps the AC charge baseline across restarts and the other readings in memory only, so a counter that stepped while Home Assistant was down is judged against what it read before the restart, or, for the counters that are not saved, accepted unless it is larger than a day could hold.

## The system looks different

The repair **The system looks different** appears in **Settings → System → Repairs** when, since the integration last looked, the inverter it manages changed type, or its number of battery modules changed, or a different device would now be managed (a Gateway that has appeared over it, for example). It names what changed, for example `type hybrid inverter to three-phase inverter` or `battery modules 2 to 3`.

The integration looks at start-up, every five minutes, and when GivTCP's version changes. It keeps managing the inverter it was set up with and changes nothing by itself.

1. If you upgraded GivTCP, the entities the integration uses may have been renamed or removed. Open **Settings → Devices & Services → GivEnergy Inverter Manager**, open the menu and select **Reconfigure**. It shows the entities in use next to the ones it finds now.
2. Select **Submit** on the repair to say this is the system to manage. The repair then clears, and the next change raises it again.
3. If you added a second inverter or a Gateway, see [Which serial do I use?](quick-start.md#which-serial-do-i-use).

A new GivTCP version alone is not a change. Neither is a battery module that answers with zeros, which is not counted.

## Upgrading GivTCP

What to expect when you move GivTCP from 3.5 to 3.6, and what the integration does about it.

- **Entity ids can be reset.** GivTCP 3.6 and 3.6.1 reset entity ids to their defaults when a discovery setting changed, so a renamed entity goes back to its default id. The integration remembers each wired entity's registry id as well as its entity id, and finds the entity again under its new id by itself. No repair appears. GivTCP 3.6.2 fixed the reset. Use 3.6.2 or later.
- **A repair names the releases that do it.** When GivTCP reports 3.6 or 3.6.1 the repair **This GivTCP release resets entity ids** appears. Update the GivTCP add-on to 3.6.2 or later and restart it. The repair clears by itself. Releases before 3.6 do not reset ids and raise nothing. It only appears when the version can be read, and nothing is changed or stopped.
- **Entities can be removed or renamed.** A high-voltage Gen 3 hybrid moves from the three-phase entity set to the single-phase one, and the PV string entities are removed on AC-coupled and All-In-One models. An entity the integration uses that cannot be found by either id raises **GivTCP entities not found**, naming it, after five minutes. See below.
- **A Gateway's energy totals change units.** See [Energy totals jumped after a GivTCP upgrade](#energy-totals-jumped-after-a-givtcp-upgrade). Home Assistant's Energy dashboard shows one large spike, which you correct in **Developer Tools → Statistics**.
- **The type can change.** An HV Gen 3 hybrid that GivTCP used to read as three-phase is read as a hybrid from 3.6. That is a different system, so [The system looks different](#the-system-looks-different) appears.

## GivTCP entities not found

The repair **GivTCP entities not found** appears in **Settings → System → Repairs** when entities chosen at setup no longer exist in Home Assistant, and the integration cannot find them under another id either. It names them. This usually means GivTCP was reinstalled with another serial, was upgraded and removed or renamed entities, or its entity IDs changed. A single missing entity raises it after five minutes, so a start-up while GivTCP is still publishing does not.

1. Open **Developer Tools → States** and search for `givtcp_`. Note the new serial in the entity IDs.
2. Open **Settings → Devices & Services → GivEnergy Inverter Manager**, open the menu and select **Reconfigure**. Use the entities it finds, or choose them by hand. Saving reloads the integration once.
3. If you moved to a different inverter, Reconfigure refuses entities with another serial. Remove the integration and add it again, picking the new inverter. Accumulated energy is kept, because the storage file is not deleted.

The repair clears on its own once the entities exist again.

## The GivEnergy charger is not found or does not change mode

The integration finds a GivEnergy charger from the entities GivTCP publishes for it, a device called GivEVC. **It has not been tested against a real GivEnergy charger.** If it is not found:

1. In GivTCP's configuration, turn **EVC Enable** on. Without it GivTCP publishes nothing for the charger.
2. Open **Developer Tools → States** and search for `charging_state`. You need `sensor.<prefix>_charging_state` and `sensor.<prefix>_connection_status` next to each other. If your entity ids differ, open an issue with the list.
3. GivTCP's README records a firmware bug in charger versions 1.12 and below: the charger's local Modbus port works over WiFi only, not over a cable. Connect the charger by WiFi, or update its firmware.

If it is found and the mode never changes, the **EV Protection Reason** sensor says why. A mode select that offers none of Solar, Surplus, Green or Eco+, or only options with `stop`, `grid`, `fast` or similar in their names, is left alone. The integration never starts or stops a session, never writes Plug and Go, and never selects Grid or Hybrid.

## Configure problems

- **"Entity is neither a valid entity ID nor a valid UUID" on save.** This was a bug in v0.2.1 when a forecast or carbon intensity field was empty. Update to v0.3.0. In v0.3.0 an empty field saves as empty, and clearing a saved entity removes it.
- **Configure shows a menu, not one long page.** Open the page you want to change, then choose **Save changes**, which lists every change before saving. See [Configuration](configuration.md#configure).
- **Battery divert threshold or surplus is not in Configure.** They are controls, with the other tuning settings. See [Configuration](configuration.md#controls).
- **A page shows a note starting "Check:" and does not move on.** It is a warning, for example ready-by times with no temperature sensor. Submit the page again to keep what you entered.
- **Entities went unavailable after saving.** Changing the immersion switch or sensor, the main forecast sensor, the currency, or alternative water heating when it appears or goes (turned on with a cost set, turned off, or its last cost cleared), reloads the integration. It takes a few seconds. If entities have not recovered after 30 seconds, check the log for errors.

## Battery minimum SoC is set too high

The repair **Battery minimum SoC is set too high** appears when the saved minimum SoC is above 30%. Older versions accepted higher values. On a skip night the integration writes the minimum SoC as the charge target, so a high value holds the battery at that level all night and imports from the grid.

1. Open **Settings → Devices & Services → GivEnergy Inverter Manager → Configure** and tick **Battery**.
2. Set **Battery minimum charge** to 10 to 20.
3. Submit. The repair clears on the next update cycle.

## Other charge slots are active

The repair **Other charge slots are active** appears when a GivTCP charge slot other than the one the integration writes has a window set. The integration writes slot 1 only, and the inverter charges in every active slot. For example, a leftover slot 2 from 00:00 to 08:00 starts charging at midnight, which can be a dearer rate than a cheaper window later in the night.

A slot counts as active when its start time differs from its end time. 00:00 to 00:00 means unused. Slots 2 to 10 are checked on every update cycle, and a slot whose entities are missing or unavailable is ignored.

To clear the slots in one step:

1. Open **Settings → System → Repairs** and open **Other charge slots are active**.
2. Check the slots named in the text, then select **Submit**.
3. The integration sets the start and end time of each named slot to 00:00. Each change is read back and counted as an inverter register write. The repair clears on the next update cycle.

With the **Dry run** switch on, nothing is changed. **Last Skipped Action (Dry Run)** shows what would have been cleared, and the repair stays.

To clear a slot by hand:

1. Open **Developer Tools → States** and search for `charge_start_time_slot_`.
2. For each active slot, call `select.select_option` with option `00:00:00` on both its `charge_start_time_slot_N` and `charge_end_time_slot_N` entities.

Slot 1 is never changed by this repair.

## Battery cost is not set

The repair **Battery cost is not set** appears when **Battery cost** is 0 and the integration has been tracking the battery for 7 days. With no cost, battery wear is 0, so **Net Saving Today** equals **Saving vs Grid Today**. A battery cost also feeds **Battery Cycle Cost per kWh** and the immersion divert rule. See [Configuration](configuration.md#battery-and-charging).

To set it from the repair:

1. Open **Settings → System → Repairs** and open **Battery cost is not set**.
2. Enter what the battery cost, then select **Submit**.
3. The value is saved to the integration options. Every other saved option is kept. The repair clears on the next update cycle.

You can also set **Battery cost** under **Configure**, on the Battery page.

The repair appears once. If you do not want wear counted, select **Ignore** and it stays out of the way. It is raised again only if the cost is set and then set back to 0.

## EV is charging at the base rate

The repair **EV is charging at the base rate** appears when the car draws from the grid in the base-rate band and your tariff has a cheaper band. The same session in the cheaper band costs less. The repair names the power, the base rate and when the next cheaper band starts, for example `about 7.2 kW at the Day rate, a cheaper band starts at 23:00`.

It needs nothing set up. The integration uses the charger it already found and the tariff you entered. All of these must hold for 5 minutes before the repair appears:

- The car draws at least 1380 W, the same threshold the EV signals use.
- The grid supplies at least 1380 W. A car on solar, or on the battery, does not count.
- The rate in force is the base rate. A session in any timed band, cheap or not, is left alone.
- The tariff has a timed band cheaper than the base rate. A flat tariff, or one whose only timed bands cost more than the base rate, never raises the repair.

The repair is raised once, not every cycle. It clears when the session ends or when the rate drops into a timed band, for example when a night band starts. If the session is still charging when the base rate returns, for example at the end of the night band, a new repair appears after another 5 minutes. **Ignore** hides it until it clears and a later session raises it again.

The integration does not stop or pause the charger. To move the session:

1. Pause the charge, or set the charger to a mode that waits, until the cheaper band starts.
2. Or set the charger's own schedule to start inside the cheaper band. See [Tariff](tariff.md) for the bands in force.

If the repair appears while the car should be on solar, check that **Grid Power** reads correctly and that the charger's power entity is the one the integration found. The charger's power is **EV Charging Power**. An install with no charger, or a charger with no power entity, never raises it.

## The tariff has not been reviewed

The repair **Tariff rates have not been reviewed** appears when the tariff has gone 365 days without being saved changed or confirmed. The date counts from the last saved change to the tariff, the last dated change recorded, the last time you chose **The tariff is still current** in Configure's Tariff menu, or the last time you confirmed the rates in the repair. The first run after an upgrade records that day, so the repair appears 365 days later at the earliest. The repair does not change anything and does not affect any sensor.

1. Check the rates against your latest bill.
2. If a rate changed, open **Settings → Devices & Services → GivEnergy Inverter Manager → Configure**, tick **Tariff** and save the new rates. To start them on a later date, tick **Schedule a rate change**. See [Tariff](tariff.md#change-the-rates-from-a-date).
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

1. Is the **Dry run** switch on? Then nothing is sent. A new install starts with it on, and a test instance (a `.givenergy_test_instance` file in the configuration folder) keeps it on. See [Configuration](configuration.md#dry-run). **Last Skipped Action (Dry Run)** shows what would have been written.
2. Were the charge control entities detected? Without a target SoC entity nothing is written. The tariff step of setup shows how many of the five were found.
3. Does the tariff have at least one timed rate period? With a flat tariff there is no cheap window and no write.
4. The write happens once a day, one minute before the cheapest timed period starts. If your cheapest period starts at 02:00, that is 01:59. If it fails, it is tried again 2, 5, 10 and 20 minutes later, and the **GivTCP Register Write Count** sensor lists each failure in `recent_writes` with the reason `retry`. See [The charge write failed and was retried](#the-charge-write-failed-and-was-retried). With debug logging on (see the next section), search the log for `Writing charge target`.
5. Is **Force Skip Overnight Charge** on? Then the minimum SoC is written as the target.
6. Was the same entity written in the last 5 minutes? The write is skipped. With debug logging on, the log says `write cooldown active`.
7. Check GivTCP's own log for rejected writes. If the integration's log says it wrote a value but could not confirm it, see [Writes to the inverter are not confirmed](#writes-to-the-inverter-are-not-confirmed).

## The charge write failed and was retried

The `recent_writes` attribute of the **GivTCP Register Write Count** sensor shows a line with the reason `retry` each time tonight's charge write failed. The value says which attempt failed, why, and when the next try is, for example `attempt 1 failed: the inverter did not take it, trying again at 02:01`. The write has failed when the inverter feed is not live (see [GivTCP data is frozen](#givtcp-data-is-frozen) and [GivTCP is not getting data from the inverter](#givtcp-is-not-getting-data-from-the-inverter)), or when a setting was sent and the inverter still shows the old value.

- The retries are at +2, +5, +10 and +20 minutes after the trigger. A retry is skipped when less than 15 minutes of the window would remain.
- Each retry writes the plan as it is then, so a charge target override you set in the meantime is what goes out.
- If every attempt fails, the last `retry` line starts with `gave up after`, and the inverter keeps its previous target. Check [Writes to the inverter are not confirmed](#writes-to-the-inverter-are-not-confirmed) first.
- If Home Assistant restarts inside the window and no write was logged since the trigger, the write is made once as it starts.
- Dry run sends nothing, so nothing is retried.

With **Re-plan overnight charge** on, the target can also change after a successful write. Those lines have the reason `replan`. See [Re-planning](concepts.md#re-planning).

## Real Time Control is off

The repair **GivTCP's Real Time Control is off** appears when GivTCP's **Real Time Control** switch has read off for three cycles in a row, about a minute and a half. While it is off, GivTCP accepts a change from Home Assistant and does not send it to the inverter. The charge window and target the integration writes never arrive, so tonight's charge may not follow the plan. An upgrade of GivTCP can reset the setting.

1. Open GivTCP's settings. For the add-on that is **Settings → Add-ons → GivTCP → Configuration**.
2. Turn **Real Time Control** on, save and restart GivTCP.

The repair clears by itself once the switch reads on. A switch that is missing, unknown or unavailable raises nothing, as on an EMS, which has no such switch. Nothing is stopped or changed in the meantime. If the repair does not appear and writes still do not take, see [Writes to the inverter are not confirmed](#writes-to-the-inverter-are-not-confirmed).

## Writes to the inverter are not confirmed

The integration reads each charge setting back after it writes it. When the inverter still shows the old value after three attempts, the log has a warning like this, with the name of the setting in front:

`wrote 75 but could not confirm after 3 attempts`

The integration carries on, so the inverter then runs on its old charge window or target. It also raises the repair **The inverter did not take a charge setting**, which lists each setting that did not take and its entity. The repair clears when a later write to the same setting is read back, when the setting is seen at the value on a later cycle, and when the integration is unloaded or reloaded. It is not raised in dry run. Look for the log warning in **Settings → System → Logs** (search for `could not confirm`), and compare the charge target and charge window entities with what the integration says it wrote under **Find out what changed the charge target**. Work through these checks in order.

1. **Real Time Control is on in GivTCP.** The repair [Real Time Control is off](#real-time-control-is-off) appears when it is not. GivTCP only sends changes from Home Assistant to the inverter when this setting is on. With it off, a write does not reach the inverter, which keeps its old value. An upgrade of GivTCP can reset it. Open GivTCP's settings (for the add-on, **Settings → Add-ons → GivTCP → Configuration**, or the settings page of your own install), turn **Real Time Control** on, save and restart GivTCP.
2. **GivTCP is running and publishing.** Open the GivTCP log and look for a crash or a repeated error since the last upgrade or restart. Under **Settings → Devices & Services → MQTT → Configure**, listen to the topic prefix GivTCP publishes under. New messages should keep arriving. If GivTCP is stopped, its entities keep their last values and do not turn `unavailable`, so a stale value does not prove it is working.
3. **The tariff settings in GivTCP are filled in.** Check that the day rate, the night rate and the tariff type all have a value. An empty day rate stopped GivTCP v3.6.3 from starting. Fill them in, even if you only use the rates in this integration, then restart GivTCP.
4. **GivTCP can reach the inverter.** Check the GivTCP log for connection errors to the inverter. A write sent while the connection is down is not confirmed either.

After a fix, the next write that the inverter takes ends the warnings. To retry at once, change the charge target by hand and check the entity follows.

## Something else is setting the charge target

The dashboard banner **Something else is setting your charge target** and the diagnostic sensor **Charge Target Conflict** (`suspected`) mean the charge target changed at least twice in the last three days, and this integration did not send those changes. Only this integration should set the target. If two controllers write it, the battery follows whichever wrote last, and tonight's plan may not be what the inverter does.

1. Turn off the other controller. Common ones are GivTCP's SmartTarget (a setting in GivTCP's configuration, off by default), Predbat and any automation of yours that sets the target.
2. Open the sensor's attributes. `changes` is how many outside changes were counted, `last_seen` is when the newest happened, and `target_entity` is the entity.
3. To see each change, follow [Find out what changed the charge target](#find-out-what-changed-the-charge-target). A change with a `user_id` is you or someone using Home Assistant on purpose, and is not counted.

The integration cannot tell the causes apart. A change made in the GivEnergy app reaches GivTCP with no Home Assistant user, so it counts too, and so does a plant controller that sets values itself. If you change the target in the app on purpose, expect the banner after two changes. It clears three days after the last one. The integration never undoes a change and never raises a repair for this.

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

- **The reason ends in `…`.** Home Assistant keeps a state of at most 255 characters, so a long reason is cut at the end of a sentence or clause. The whole text is in the `full_text` attribute of **Overnight Charge Reason**, which is there only while the state is cut. Read it in Developer tools, States, or in a template with `{{ state_attr('sensor.givenergy_inverter_manager_overnight_charge_reason', 'full_text') }}`.
- **The target is lower than expected, and the reason ends "capped at configured max".** **Default overnight charge target** caps the calculated target. It is 80 unless you changed it, and the cap applies to the winter 100% target too.
- **The sensor differs by a few points from the value written to the inverter.** **Recommended Overnight Charge Target** holds its value until the calculated target moves 5 points or more and the value has stood for an hour (15 points or more shows at once), so the history stays readable. The write uses the latest calculation, and the sensor matches it from the next cycle. See [Overnight charge target](concepts.md#overnight-charge-target).
- **December to February.** The target is 100% before the cap, whatever the forecast.
- **March, April, October and November.** The minimum SoC is at least 70% in the calculation.
- **No forecast.** Without a tomorrow sensor, the integration uses a seasonal estimate from your latitude. The reason says so.
- **A forecast setting has no effect.** A P10 forecast only matters when the Forecast conservatism control is above 0, and conservatism only matters when a P10 forecast exists. Solcast provides one automatically. The charge reason says `no P10 forecast so conservatism is unused` otherwise. See [Where the P10 comes from](configuration.md#where-the-p10-comes-from).
- **The charge reason shows no `recent accuracy` factor.** The correction needs 5 usable days. Days with clipping, or under 0.5 kWh of forecast or solar, do not count. The attributes of **Overnight Charge Reason** show how many days are usable (`accuracy_status`, for example `Waiting for data: 3 of 5 days`). A new install reads earlier days from the recorder when it first loads, so it shows up to 9 usable days at once. It shows 0 when the recorder is not running, holds no history for the forecast sensor or the GivTCP daily solar counter, or those sensors are new. Then it fills one night at a time, and the first midnight only remembers the forecast. See [Forecast accuracy correction](configuration.md#forecast-accuracy-correction).
- **A manual target.** See [Entities](entities.md#manual-charge-target).

To see every reading and decision, turn on both of these:

1. The **Verbose logging** switch, in the Configuration section of the device page.
2. Debug logging for the integration. Either press **Enable debug logging** on the integration page, or add this to `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.givenergy_inverter_manager: debug
```

## Why does SoC at sunrise read 10%?

There are two sunrise figures, and they answer different questions.

- **Estimated SoC at Sunrise Without a Charge** is what the battery would have at 08:00 if nothing charged it. It leaves tonight's planned charge out, and it stops at the minimum SoC when the battery would run flat. In the evening, with the battery at 50 to 65% and a charge planned for the cheap period, it can read the minimum (10% by default) from dusk until the charge starts. That is the figure Battery Overnight Outlook and Confidence judge, so a "May run low" in the evening is a shortfall without the planned charge. While a planned charge counts, the Battery overnight tile and text say so and give both figures, for example `May run low without a charge · tonight's charge covers it, about 67% at sunrise`, and the level stays as it is.
- **Estimated SoC at Sunrise With the Planned Charge** adds the planned charge window, up to the target, then runs the battery down to 08:00. This is the one to read for where the night will end. Its attributes say how: `soc_at_charge_start` is the SoC when the window opens, `charge_added_pct` is what the window adds, `charge_window` is the window used and `basis` says it in words.

If both read the same, no charge counts: tonight is skipped, no timed charge window is set, or the window is over. A with-charge figure well below the target means the window is too short to reach it at the charge rate, or the load estimate is high. The no-charge figure always spreads the daily average evenly, so it is pessimistic for a quiet night. The with-charge figure uses the learned per-slot load profile once there is one, and its `basis` attribute says which load it used. Check **Overnight Charge Window** and **Overnight Charge Reason**. See [Battery overnight](concepts.md#battery-overnight).

## The immersion does not turn on

Read **Immersion Divert Reason**. It gives the exact block.

| Reason starts with | Fix |
|---|---|
| `No immersion switch configured` | No immersion switch entity is set, so there is nothing to turn on |
| `Manual override` | **Auto Immersion Divert** is off. Turn it on |
| `Water already at` | The water is at the target. Wait for it to cool by the restart gap |
| `Battery SoC ... below threshold` | The divert threshold (default 80%) is set at setup only |
| `Not enough spare solar` | Spare solar is below the minimum (default 500 W). It says how far short: either the house is using more than the panels make, or some watts are spare but fewer than needed. Cloud, or a large house load. A heater that is already on stays on until the house uses more than the minimum beyond what the panels make |
| `Water at ... will restart below` | The restart gap is holding it off. Lower **Immersion Restart Gap** |
| `Cheapest rate window (...): heating from ... to ...` | Scheduled heating is running in the cheapest window |
| `Heating to be ready by 19:00: ...` | A ready time needs the heater now. `too late to be ready in full` means the hours left are fewer than the hours needed |
| `Export rate ... below battery cycle cost` | Battery cost is set and exceeds the export rate. Set battery cost to 0 to turn the check off |

If the reason says to heat but the heater stays off, check that an immersion switch entity was set at setup, and that the 10-minute hold after the last switch has passed. In dry run the real switch is never touched.

## There is no Water Heating Cheapest Source sensor

The sensor exists only while alternative water heating is on, has a cost, and an immersion switch is set. Check the three under **Configure**:

| Missing | Fix |
|---|---|
| **I have another way to heat the water** is off | Turn it on under Alternative water heating |
| No cost and no cost sensor | Set the cost, or a cost sensor, and choose its unit. The log says `no advice until a cost is set` |
| No immersion switch | Set one under Immersion heater. The advice compares the alternative with the immersion. The log says `no advice until an immersion switch is set` |

Saving reloads the integration once, when the sensor appears or goes. The sensor reads unavailable while the cost sensor has no number and no saved cost is set.

**An automation or card still reads `oil`.** Version 0.18 renamed the sensor's state and attributes. The state `oil` is `alternative`, the attributes that began `oil_` begin `alt_`, and `best_hours_for_oil` is `best_hours_for_alt`. Change the automation or card. The entity ID did not change.

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

## The dashboard is missing or shows an error

- **GivEnergy is not listed under Community dashboards.** Reload the browser tab, so the frontend loads the integration's strategy file. If it is still missing, add a dashboard from scratch and use `strategy: type: custom:givenergy-manager` in its Raw configuration editor. See [Dashboard](dashboard.md#add-the-dashboard).
- **The dashboard says "Timeout waiting for strategy element", or choosing GivEnergy under Community dashboards does nothing.** The browser did not load the dashboard script. Home Assistant gives the script to the page when the page is served, and before 0.19.1 that only happened once the integration had finished loading, so a page opened just after a restart missed it. Do a hard refresh (Ctrl+Shift+R, or clear the app cache on a phone). To check, open the browser console (F12) and run `customElements.get('ll-strategy-dashboard-givenergy-manager')`. It should print a class. If it prints `undefined` after a hard refresh, open an issue with your Home Assistant version and anything the console shows in red.
- **I never saw the notification, and there is no dashboard.** The integration adds nothing to your dashboards. Add it yourself from **Settings → Dashboards → Add dashboard**. The notification is shown once, at first setup.
- **The dashboard says GivEnergy Inverter Manager is not loaded.** The integration is not set up, or it is still starting or reloading. Check **Settings → Devices & Services**, and reload the page when it shows as loaded.
- **The dashboard says it could not build the dashboard, with a reason.** Look for lines that contain `givenergy` in **Settings → System → Logs**, and open an issue with them if the reason is not clear.
- **A tile or section is missing.** The dashboard leaves out what has no value to show: a disabled sensor, an optional device that does not exist, or a setting you have not made. See [What is left out](dashboard.md#what-is-left-out).
- **There is no Settings view.** Only Home Assistant administrators get it. Sign in as one and reload the page. A copy made with Take control keeps the view the person had at the time.
- **The live flow card shows an error.** The card needs power-flow-card-plus. The dashboard uses it only when its URL is in **Settings → Dashboards → Resources**, and shows an entities card otherwise.
- **The Refresh Dashboard button and the `get_dashboard_yaml` action are gone.** The dashboard builds itself each time it opens. See [Dashboard](dashboard.md#moving-from-the-generated-file).
- HTML report cards that show plain text: use a built-in `markdown` card and enable the report sensor. See [Dashboard](dashboard.md#html-report-cards).

## Getting help

Open an issue on [GitHub](https://github.com/macuistin/givenergy_inverter_manager/issues). Include:

- the log lines from **Settings → System → Logs** that contain `givenergy`;
- your Home Assistant and GivTCP versions;
- the diagnostics file, from the integration page, **Download diagnostics**. It holds your configuration, including tariff values. The inverter serial and every entity ID that contains it are redacted. Read it before you post it;
- what you expected and what happened.
