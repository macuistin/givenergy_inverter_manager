# lib/tariff

The tariff model and the money maths: timed rate periods (including ones that run past midnight),
the cheapest rate in force, running energy and cost totals for a billing period, a bill line by
line and the value of energy held in a battery. It needs no Home Assistant objects and does not
read option keys.

## Public names

- `RatePeriod`, `TariffConfig`: the tariff, built from typed fields
- `EnergyAccumulator`, `CounterMemory`: running totals for a billing period
- `BillBreakdown`, `money`: a bill rounded to cents, halves upward (`Decimal`, `ROUND_HALF_UP`)
- `StoredEnergy`, `stored_energy_change`, `value_per_stored_kwh`: the value of stored energy

## Allowed dependencies

The standard library and `lib/timeutil`.

## Not here

Reading the saved options by `CONF_` key (`core/tariff.py`: `build_tariff`, the dated rate
changes and the option saves) and the stored bill rows (`core/bill_days.py`) stay in the
integration, because they name the integration's own keys.
