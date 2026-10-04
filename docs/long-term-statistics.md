# Long-term statistics

Home Assistant keeps long-term statistics for sensors that declare a state class. This page explains the state classes the integration uses, when each sensor resets, and what happens to the totals across a restart.

## Resets

Each accumulating sensor counts from the start of a period. The integration resets the period at local midnight.

| Period | Resets at | Sensors |
|---|---|---|
| Day | 00:00:00 every day | The Today sensors |
| Week | 00:00:00 on Monday | The This week sensors |
| Month | 00:00:00 on the bill start day chosen at setup | The This month sensors and Accrued Bill This Period |
| Year | 00:00:00 on 1 January | The This year sensors |

At the daily reset the integration:

1. copies today's totals to the Yesterday sensors;
2. starts a new, empty set of today's totals;
3. records the new midnight as `last_reset` on the daily sensors.

The first cycle after a reset adds no energy. The values grow again from the second cycle, or jump to the GivTCP counter value if you have the GivTCP daily counters.

## State class total, with last_reset

A sensor that goes up for a period and drops to zero at its reset needs the state class `total` and a `last_reset`. The state class `total_increasing` fits a counter that only goes up. Home Assistant rejects `last_reset` on any other class, and raises an error when it writes the state.

Without `last_reset`, Home Assistant reads the drop at a reset as a negative use of energy. With it, Home Assistant starts a new cycle in the statistics.

Every sensor that resets reports `last_reset` as the start of its own period: the latest midnight for day sensors, the latest Monday for week sensors, the latest bill start day for month sensors and the latest 1 January for year sensors. The Last reset column of [Sensors](sensors.md) shows the period for each sensor.

Other classes in use:

| State class | Used for |
|---|---|
| `measurement` | Power, SoC, rates, percentages and other values that move up and down freely |
| `total`, no `last_reset` | Battery Total Cycles and GivTCP Register Write Count, which only go up |
| `total_increasing` | EV Session Energy. Home Assistant detects the drop when a new session starts |
| none | Yesterday values, trailing 12-month sensors, estimates such as Projected Bill This Period, the solar forecast, text sensors and the pre-boost export estimates |

Yesterday and trailing 12-month values are not cumulative. They are a snapshot that is replaced once a day or once a bill period, so they have no state class and Home Assistant keeps no statistics for them.

## Restarts and gaps

- Accumulated energy is saved when the integration unloads (including a reload after saving options), when Home Assistant stops, at midnight, and about every 5 minutes. A crash can lose up to about 5 minutes of energy that the integration adds up itself.
- Solar, import, export, battery charged, battery discharged and house load for today use the GivTCP counters when they exist, so these recover at once after a restart.
- The year totals, Missed Solar Today and Inverter Derating Today are saved with the rest.
- On start-up the integration compares the date of its last midnight reset with today. It then applies every reset it missed. After one missed midnight, the saved today moves to Yesterday. After a longer gap, Yesterday is empty because nothing was recorded. A missed Monday, bill start day or 1 January resets the week, month (with a snapshot) or year.
- `last_reset` is restored from storage, so it does not go empty after a restart.

## When last_reset is missing

On a fresh install the period start is set to the start of the current day, week, bill period and year. `last_reset` is empty only for a moment, before the first update after the integration loads.

## If daily sensors stop moving

A sensor whose state class does not allow `last_reset` makes Home Assistant refuse to write its state, and the value stays frozen until the integration reloads. Version 0.2.1 had nine such sensors. See [Troubleshooting](troubleshooting.md#daily-sensors-are-frozen-after-an-upgrade).

## Upgrading: statistics that change

Existing statistics keep their history. Home Assistant may raise a repair for a sensor whose state class changed. Choose to fix the issue and, for the sensors that now have no state class, delete their statistics. The old sums for the sensors below contain negative steps at every reset.

Gain `last_reset` (state class stays `total`):

- Week: `solar_this_week`, `import_this_week`, `export_this_week`, `import_cost_this_week`, `export_earnings_this_week`, `import_kwh_cheap_this_week`, `import_kwh_peak_this_week`, `immersion_savings_this_week`
- Month: `accrued_bill`, `solar_this_month`, `import_this_month`, `export_this_month`, `import_cost_this_month`, `export_earnings_this_month`, `import_kwh_cheap_this_month`, `import_kwh_peak_this_month`, `immersion_savings_this_month`, `net_position_this_month`
- Year: `solar_this_year`, `export_this_year`, `export_earnings_this_year`

State class changes from `total` to none:

- Yesterday: `solar_yesterday`, `import_yesterday`, `export_yesterday`, `import_cost_yesterday`, `import_kwh_cheap_yesterday`, `import_kwh_peak_yesterday`, `immersion_savings_yesterday`
- Trailing 12 months: `solar_trailing_12m`, `import_trailing_12m`, `export_trailing_12m`, `import_cost_trailing_12m`, `export_earnings_trailing_12m`
- Forecast: `solar_forecast_kwh_today`

State class changes from `total` to `total_increasing`: `ev_session_energy`.

## Known limitation: currency unit

Monetary sensors use the currency symbol you chose in the tariff, such as `€` or `£`, as their unit. Home Assistant documents the monetary device class as taking an ISO 4217 code such as `EUR` or `GBP`. The symbol works for display and for statistics, but Home Assistant cannot tell that it is a currency code.

Switching to the ISO code would change the unit of every monetary sensor. Home Assistant then treats the existing statistics as belonging to a different unit and stops recording them until each one is repaired. The integration keeps the symbol for now so that existing statistics are not broken. See the [Roadmap](../ROADMAP.md).
