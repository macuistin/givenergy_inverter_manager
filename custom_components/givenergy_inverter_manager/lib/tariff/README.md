# lib/tariff

The tariff model and the money maths: timed rate periods (including ones that run past midnight),
the cheapest rate in force, running energy and cost totals for a billing period, a bill line by
line and the value of energy held in a battery. It needs no Home Assistant objects and does not
read option keys.

## Public names

- `RatePeriod`, `TariffConfig`: the tariff, built from typed fields
- `EnergyAccumulator`, `CounterMemory`: running totals for a billing period
- `BillBreakdown`, `money`: a bill rounded to cents, halves upward (`Decimal`, `ROUND_HALF_UP`)
- `SlotDay`, `SlotHistory`, `SERIES`: energy in half-hour slots, a local day at a time, kept for
  about 400 days (see below)
- `StoredEnergy`, `stored_energy_change`, `value_per_stored_kwh`: the value of stored energy

## Half-hourly slots

`SlotDay` holds one local day: kWh per slot for each series in `SERIES` (grid import and export,
house, EV, immersion, solar, grid-to-battery) and the seconds actually observed in each slot.
Slots are counted in real elapsed time from local midnight, so a day has 46, 48 or 50 of them
across a clock change. Observed seconds tell a slot with no data from one that used nothing.

`SlotHistory.record` spreads an interval over the slots it touches by time, splits it at
midnight, ignores an interval over 30 minutes (a gap) and drops days past the retention.
`to_storage` writes whole watt-hours and seconds, and `restore` skips and counts unreadable days.
The data does not depend on any tariff, so it can be priced under any of them later.

## Allowed dependencies

The standard library and `lib/timeutil`.

## Not here

Reading the saved options by `CONF_` key (`core/tariff.py`: `build_tariff`, the dated rate
changes and the option saves) and the tariff snapshot (`core/tariff_snapshot.py`) stay in the
integration, because they name the integration's own keys. The stored bill rows themselves
(`bill_days`: `day_row`, `with_day`, `tariff_in_effect`, `tariff_changes`) are here.
