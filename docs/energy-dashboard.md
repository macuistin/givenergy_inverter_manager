# Energy dashboard

Home Assistant's Energy dashboard needs sensors with device class `energy`, a total-type state class and a kWh unit. The Today sensors below meet that. Pick them in **Settings → Dashboards → Energy**.

| Energy dashboard slot | Sensor | Enabled by default |
|---|---|---|
| Solar production | Solar Generation Today | yes |
| Grid consumption | Grid Import Today | yes |
| Return to grid | Grid Export Today | yes |
| Home battery storage, energy going in | Battery Charged Today | no |
| Home battery storage, energy coming out | Battery Discharged Today | yes |
| Individual device | EV Charging Today | yes |
| Individual device | Immersion Heater Today | yes |

Enable Battery Charged Today in **Settings → Devices & Services → GivEnergy Inverter Manager → entities** before you pick it.

## Why these sensors

- They have state class `total` and report `last_reset` at local midnight. See [Long-term statistics](long-term-statistics.md).
- Solar, import, export and the two battery sensors use the GivTCP daily counters when those exist, so the figures match the inverter's own metering. See [Concepts](concepts.md#givtcp-daily-counters).
- Do not use the Yesterday, This week, This month, This year or trailing 12-month sensors. The Energy dashboard builds its own weekly and monthly views from the daily sensors, and Yesterday and trailing values have no state class.

## Costs

Import Cost Today and Export Earnings Today are monetary sensors with state class `total` and the same midnight reset. They apply your tariff rates, supplier discount and VAT, and the currency symbol you chose. See [Tariff](tariff.md#bill-line-items).

Current Rate uses the bare currency symbol as its unit, not a per-kWh unit. Use the two cost sensors above for costs.

## If a total looks wrong

- Daily values come from the inverter's counters when present. If your totals do not match GivTCP, compare the six `sensor.givtcp_<serial>_*_energy_today_kwh` entities first.
- The sign of grid power matters for import and export. See [sign conventions](concepts.md#givtcp-sign-conventions).
