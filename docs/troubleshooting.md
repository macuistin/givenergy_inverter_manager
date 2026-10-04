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
- If both entities are missing from Home Assistant entirely, the repair **GivTCP entities not found** appears in **Settings → System → Repairs**. This usually means GivTCP was reinstalled with another serial. The repair text points to Reconfigure, but Reconfigure only edits the tariff. Remove and re-add the integration instead. Accumulated energy is kept, because the storage file is not deleted.

## Options form errors

- **"Entity is neither a valid entity ID nor a valid UUID" on save.** This was a bug in v0.2.1 when a forecast or carbon intensity field was empty. Update to v0.3.0. In v0.3.0 an empty field saves as empty, and clearing a saved entity removes it.
- **Tariff changes made in Reconfigure have no effect.** Once you have saved the Configure page, its saved copy overrides Reconfigure. Change the tariff in Configure.
- **Battery divert threshold or surplus is not on the page.** They are set at setup only. See [Configuration](configuration.md#step-6-battery).
- **Entities went unavailable after saving.** Saving reloads the integration. It takes a few seconds. If entities have not recovered after 30 seconds, check the log for errors.

## Daily sensors are frozen after an upgrade

Version 0.2.1 gave nine daily sensors the state class `total_increasing` together with `last_reset`. Home Assistant refuses that combination, so the sensors stopped updating until the integration reloaded. In one install, battery throughput stayed at one value for about 46 hours.

The nine sensors are Import at cheap rate, Import at peak rate, Import cost at cheap rate, Import cost at peak rate, Immersion solar savings, Immersion solar diverted, Battery throughput, Missed solar today and Inverter Derating Today.

1. Update to v0.3.0 or later, where they use state class `total`.
2. Restart Home Assistant, or reload the integration.
3. Watch one of the nine for a minute. It should change while the house uses power.

See [Long-term statistics](long-term-statistics.md) and [Upgrade notes](upgrade-v0.3.0.md).

## Daily totals do not reset at midnight

Solar, import, export, battery charged, battery discharged and house load for today follow the GivTCP daily counters when those exist. The sensor then follows the GivTCP counter, including the moment that counter resets. Compare the six `sensor.givtcp_<serial>_*_energy_today_kwh` entities.

## Grid import and export look swapped

The integration expects GivTCP's grid power to be positive when exporting. Export to the grid on a sunny day, then compare the GivTCP grid power entity with **Grid Power** in **Developer Tools → States**. They must have opposite signs. See [sign conventions](concepts.md#givtcp-sign-conventions).

## The charge target is not written to the inverter

Work through this list.

1. Is **Dry run mode** on? Then nothing is sent. **Last Skipped Action (Dry Run)** shows what would have been written.
2. Were the charge control entities detected? Without a target SoC entity nothing is written. The tariff step of setup shows how many of the five were found.
3. Does the tariff have at least one timed rate period? With a flat tariff there is no cheap window and no write.
4. The write happens once a day, one minute before the cheapest timed period starts. With the default tariff that is 01:59. With debug logging on (see the next section), search the log for `Writing charge target`.
5. Is **Force Skip Overnight Charge** on? Then the minimum SoC is written as the target.
6. Was the same entity written in the last 5 minutes? The write is skipped. With debug logging on, the log says `write cooldown active`.
7. Check GivTCP's own log for rejected writes.

## A charge decision looks wrong

Read **Overnight Charge Reason** first. Then check these:

- **The target is lower than expected, and the reason ends "capped at configured max".** **Default overnight charge target** caps the calculated target. It is 80 unless you changed it, and the cap applies to the winter 100% target too.
- **December to February.** The target is 100% before the cap, whatever the forecast.
- **March, April, October and November.** The minimum SoC is at least 70% in the calculation.
- **No forecast.** Without a tomorrow sensor, the integration uses a seasonal estimate from your latitude. The reason says so.
- **A forecast setting has no effect.** Forecast provider is stored and unused. The P10 sensor only matters when conservatism is above 0.
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
| `Manual override` | **Auto Immersion Divert** is off. Turn it on |
| `Water already at` | The water is at the target. Wait for it to cool by the restart gap |
| `Battery SoC ... below threshold` | The divert threshold (default 80%) is set at setup only |
| `Insufficient surplus` | Surplus is below the minimum (default 500 W). Cloud, or a large house load |
| `Water at ... will restart below` | The restart gap is holding it off. Lower **Immersion Restart Gap** |
| `Export rate ... below battery cycle cost` | Battery cost is set and exceeds the export rate. Set battery cost to 0 to turn the check off |

If the reason says to heat but the heater stays off, check that an immersion switch entity was set at setup, and that the 10-minute hold after the last switch has passed. In dry run the real switch is never touched.

## The Zappi changed to Eco+

With a Zappi that has a charge mode entity, a car plugged in and net solar surplus of at least 1380 W, the integration selects Eco+. It never selects Stopped. The only way to stop it is dry run. See [Concepts](concepts.md#ev-charger).

## Totals are lower after a restart

Accumulated energy is saved every 5 minutes and at midnight, not at shutdown. See [Concepts](concepts.md#the-30-second-cycle). Saving the options reloads the integration, which has the same effect. Moving an immersion temperature slider also reloads it.

The year sensors, Missed Solar Today and Inverter Derating Today are not saved at all.

## The bill sensors look low early in the period

Accrued Bill This Period is built from the month totals, which start again on the bill start day. Early in a period it is low because few days have passed. See [Tariff](tariff.md#bill-sensors).

## A sensor shows unknown

| Sensor | Reason |
|---|---|
| EV sensors | Unavailable until an EV charger is discovered. Discovery retries about every 5 minutes |
| Inverter Temperature and its status | The inverter temperature entity was not detected. The status shows Unknown |
| Solar actual vs forecast and the carbon sensors | No forecast has been recorded today, or no carbon intensity sensor is set |
| Minutes Remaining in Rate Period | You are on the base rate |
| Battery Years Remaining | Fewer than 7 days of cycle data |
| Battery Cycle Cost per kWh, Throughput Budget sensors | Battery cost or budget is 0 |
| Average Import Rate sensors | Nothing imported yet in that period |

Many sensors are disabled by default. See [Sensors](sensors.md).

## Dashboard cards show errors

- The live flow card in the Power Flow view needs power-flow-card-plus. Install it from HACS if the card shows an error.
- The immersion charts need apexcharts-card.
- HTML report cards that show plain text: use a built-in `markdown` card and enable the report sensor. See [Dashboard](dashboard.md#html-report-cards).

## Getting help

Open an issue on [GitHub](https://github.com/macuistin/givenergy_inverter_manager/issues). Include:

- the log lines from **Settings → System → Logs** that contain `givenergy`;
- your Home Assistant and GivTCP versions;
- the diagnostics file, from the integration page, **Download diagnostics**. It holds your configuration, including entity IDs and tariff values, and is not redacted. Read it before you post it;
- what you expected and what happened.
