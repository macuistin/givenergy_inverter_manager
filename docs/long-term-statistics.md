# Long-term statistics

Home Assistant keeps long-term statistics for sensors that declare a state class. This page explains the state classes the integration uses and why daily sensors reset at midnight.

## Midnight reset

Today's sensors count from local midnight. At 00:00:00 the integration:

1. copies today's totals to the Yesterday sensors;
2. starts a new, empty set of today's totals;
3. records the new midnight as `last_reset` on the daily sensors.

The first cycle after the reset adds no energy. The values grow again from the second cycle, or jump to the GivTCP counter value if you have the GivTCP daily counters.

The week resets at midnight on Monday. The month resets at midnight on the bill start day chosen at setup. The year resets at midnight on 1 January, and also whenever the integration restarts or reloads, because the year totals are not saved.

## State class total, with last_reset

A daily sensor goes up all day and drops to zero at midnight. The state class `total_increasing` fits a counter that only goes up. The state class `total` fits a value that can fall. Home Assistant rejects `last_reset` on any other class, and raises an error when it writes the state.

So the daily sensors use state class `total` and report `last_reset`. That tells Home Assistant the drop at midnight is a reset, not a negative use of energy.

The sensors that do this are the ones marked **yes** in the Midnight reset column of [Sensors](sensors.md).

Other classes in use:

| State class | Used for |
|---|---|
| `measurement` | Power, SoC, rates, percentages and other values that move up and down freely |
| `total`, no `last_reset` | Yesterday, week, month, year and trailing sensors, and the running bill and cycle counts |
| none | Text sensors, estimates such as Projected Bill This Period, and the pre-boost export estimates |

## When last_reset is missing

`last_reset` is set from the most recent midnight the integration has run through. After a restart or a reload it is empty until the next midnight. The daily values themselves are restored from storage, so they are unaffected.

## Restarts and gaps

- Accumulated energy is saved about every 5 minutes and at midnight, not at shutdown. A restart can lose up to about 5 minutes of energy that the integration adds up itself.
- Solar, import, export, battery charged, battery discharged and house load for today use the GivTCP counters when they exist, so these recover at once after a restart.
- Missed Solar Today and Inverter Derating Today are not saved. They restart from zero after any restart or reload.

## If daily sensors stop moving

A sensor whose state class does not allow `last_reset` makes Home Assistant refuse to write its state, and the value stays frozen until the integration reloads. Version 0.2.1 had nine such sensors. See [Troubleshooting](troubleshooting.md#daily-sensors-are-frozen-after-an-upgrade).
