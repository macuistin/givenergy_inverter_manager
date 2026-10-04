# Upgrade notes: v0.2.1 to v0.3.0

## Do this after upgrading

1. Update through HACS and restart Home Assistant. A restart reloads the nine daily sensors that were frozen in v0.2.1.
2. Open **Settings → Devices & Services → GivEnergy Inverter Manager → Configure** and review the new options (below). Nothing else needs changing.
3. Check **Overnight Charge Reason** the next day. The charge calculation changed.
4. Press **Refresh Dashboard** to regenerate the dashboard.
5. Check **Developer Tools → Statistics** for the nine sensors in the next section.

No config entry migration runs. Existing setups keep working.

## Charge calculation

The charge target logic changed. Expect different targets.

| Before (v0.2.1) | Now |
|---|---|
| Three tiers (strong, moderate, poor forecast) set the target | A forward simulation finds the lowest start SoC that keeps the battery above the minimum all day |
| No seasonal rules | December to February charge to 100%. March, April, October and November raise the minimum SoC to at least 70% |
| Forecast used as given | A Solcast P10 sensor can pull the forecast down (Forecast conservatism, default 0.35) |

The **Default overnight charge target** still caps the result. At its default of 80 that now also caps the winter 100% target. Raise it if you want the full 100% in winter.

See [Concepts](concepts.md#overnight-charge-target) for the full order of rules.

## Safer inverter writes

- Every GivTCP write reads first, skips when the value is already set, and retries up to 3 times with a 2-second wait.
- The same entity is not written more than once in 5 minutes.
- A new diagnostic sensor, GivTCP Register Write Count, counts the writes.
- The cheap rate floor now uses these safeguards too.
- Solar power used for the immersion and EV decisions is smoothed, so a passing cloud no longer switches the immersion.
- The EV charger is only sent to Eco+ at 1380 W of surplus or more.

## Sensors

v0.2.1 had 93 sensors. v0.3.0 has 144. None were removed. Of the 51 new sensors, two are enabled by default: House Load Today and GivTCP Register Write Count. The other 49 are disabled. See [Sensors](sensors.md).

### Nine daily sensors changed state class

These moved from `total_increasing` to `total`:

Import at cheap rate, Import at peak rate, Import cost at cheap rate, Import cost at peak rate, Immersion solar savings, Immersion solar diverted, Battery throughput, Missed solar today and Inverter Derating Today.

In v0.2.1 they reported `last_reset` with a class that does not allow it, so Home Assistant refused to write their state and the values froze until a reload. See [Troubleshooting](troubleshooting.md#daily-sensors-are-frozen-after-an-upgrade) and [Long-term statistics](long-term-statistics.md).

## New options

| Where | Option |
|---|---|
| Battery & charging thresholds | Battery cost, Daily battery throughput budget |
| Hardware (new section) | Battery capacity, Inverter max output, Immersion element power |
| Solar forecast | Solcast P10 sensor, Day-after-tomorrow sensor, Grid carbon intensity sensor, Forecast conservatism |
| Electric vehicle (new section) | Car efficiency |

Setup also asks for car efficiency (EV step) and the P10, day-after-tomorrow, carbon and conservatism fields (forecast step). The day-after-tomorrow sensor lowers tonight's target when that day's solar would overfill the battery.

See [Configuration](configuration.md#options).

## New actions

`get_roi_summary`, `compare_tariff`, `year_on_year_summary` and `export_energy_data`. See [Actions](actions.md).

## Other fixes

- The options page no longer fails with "Entity is neither a valid entity ID nor a valid UUID" when a forecast or carbon field is empty.
- The manual entity form in the setup wizard no longer crashes, and now moves on to the tariff step.
- The generated dashboard no longer has a Refresh Dashboard card in the Controls view. The Refresh Dashboard button on the device page remains. The Power Flow view gains an Energy Today row.
- A repair issue appears when Battery minimum SoC is above 30%.

## Known limits in v0.3.0

- Year-to-date sensors, Missed Solar Today and Inverter Derating Today are not saved over a restart.
- Per-slot load history is collected but the charge calculation does not use it.
- The day-after-tomorrow forecast is read but not used.
- Forecast provider is stored but not used.
