# lib/guards

Guards for inverter data. The counter guard tells energy from a daily counter that jumped (a rise
the system could not have delivered, a change of units) and keeps the memory of what each counter
last read. It needs no Home Assistant objects. The frozen-feed check lives in `lib/givtcp`.

## Public names

- `counter`: `screen`, `judge`, `Verdict`, `allowed_rise_kwh`, `largest_day_kwh`
- `defaults`: `COUNTER_RISE_MARGIN`, `COUNTER_RISE_FLOOR_KWH`, `COUNTER_UNIT_CHANGE_RATIO`,
  `COUNTER_UNIT_CHANGE_MIN_KWH`

`screen` takes any dataclass that has `inverter_max_w` and the counter readings it names, and
returns the same type.

## Allowed dependencies

The standard library, `lib/timeutil` and `lib/tariff` (for `CounterMemory`).

## Logging

One standard `logging` logger per module, named after the module. The warning text is the same as
before the move.

## Not here

The write log, the window guard and the charge hold are write-safety logic tied to charge
planning and stay in `core/`.
