# Troubleshooting

---

## Integration not appearing after install

Restart Home Assistant after copying the files. The integration won't be visible until HA loads it on startup.

---

## GivTCP auto-discovery finds nothing

The integration scans for `sensor.givtcp_{SERIAL}_*` entities when you run the setup wizard. If none are found:

- Check GivTCP is running and healthy in **Settings → Add-ons**
- Open **Settings → Devices & Services → MQTT** and use the Listen panel to check that GivTCP is publishing — subscribe to `GivEnergy/#` and you should see messages
- Make sure the MQTT broker is the same one both GivTCP and Home Assistant are connected to
- Wait 30 seconds after starting GivTCP before running setup — it takes a moment to begin publishing

---

## All entities show as Unavailable

This usually means the integration failed to start up. Check **Settings → System → Logs** and filter for `givenergy`.

Common causes:
- GivTCP stopped publishing after setup — restart GivTCP
- MQTT broker became unreachable — check your MQTT integration is connected
- A misconfigured option causing the coordinator to crash — check the error message in the logs and compare against your configuration

---

## Charge target is not being applied

1. Check that **Enable Charge Target Override** is off if you want automatic mode — when it's on, the integration uses your manual target instead of calculating one
2. Check that GivTCP has write access to your inverter — look in GivTCP's own logs for write errors
3. The **Overnight Charge Reason** sensor shows the current decision; if it says "Skipping — battery already above threshold", the integration has decided not to charge

---

## Charge decision seems wrong

Turn on **Verbose Logging** in Settings → Configure, then watch **Settings → System → Logs** during the next cycle. The integration logs every sensor reading and intermediate calculation at DEBUG level, so you can see exactly what it read and why it made that decision.

---

## Immersion heater is not turning on despite solar surplus

Check the **Immersion Divert Reason** sensor — it will tell you exactly why the immersion is off. Common reasons:

- **Enable Solar Immersion Divert** is off — this is the master switch; the integration won't touch the immersion when it's off
- Solar surplus is below the minimum threshold (default 500W)
- Battery SoC is below the divert threshold (default 80%)
- Water is already at target temperature

---

## Solar forecast not updating

- Verify your forecast provider credentials in Settings → Configure
- Solcast free tier allows 10 API calls per day; the integration caches results and only fetches when needed, but if you've hit the limit it will use yesterday's forecast until tomorrow
- Check that the forecast entity you've selected in configuration is actually updating — open the entity in Developer Tools to see its last updated time

---

## HTML report cards showing plain text

Make sure you are using `type: markdown` in your card configuration, not a custom card type. The reports use inline styles and work with the built-in Markdown card with no dependencies. Also confirm the sensor is enabled (HTML report sensors are disabled by default).

---

## Sensors stuck after changing configuration

When you save the options, the integration reloads automatically. This takes a few seconds — entities will briefly show as Unavailable and then recover. If they don't recover after 30 seconds, check the logs for errors.

---

## Using dry run mode

If you're not sure about the integration's decisions, turn on **Dry Run Mode** in Settings → Configure. The integration will calculate everything normally and update all sensors, but send no commands to GivTCP. The **Last Skipped Action** sensor shows what it would have done.

This is the safest way to monitor the integration's behaviour before letting it control your inverter.

---

## Getting help

If none of the above helps, open an issue on [GitHub](https://github.com/macuistin/givenergy_inverter_manager/issues). Include:

- The error from **Settings → System → Logs** (filter for `givenergy`)
- Your HA version
- Your GivTCP version
- A description of what you expected vs what happened